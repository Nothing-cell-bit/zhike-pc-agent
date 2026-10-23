"""Persistent OpenDesign plan → image → visual critique → at most one repair."""
import asyncio
import base64
import io
import json
import time
from pathlib import Path

import httpx
from PIL import Image

from . import opendesign_engine as design_engine
from .ai import job_active,job_update,text_lock
from .config import DATA,IMAGE_BASE
from . import image_settings
from .db import Asset,Job,Session,Work,now
from .images import SIZES
from .marketing import has_source_conflict


def persist(jid,payload,**changes):
    job_update(jid,payload=json.dumps(payload,ensure_ascii=False),**changes)


def complete(jid,payload,state,note=''):
    attempts=state['attempts']
    if not attempts:raise ValueError('没有可保存的海报成图')
    best=max(attempts,key=lambda item:(item.get('review',{}).get('verdict')=='pass',item.get('review',{}).get('score',0)))
    review=best.get('review',{'verdict':'fail','score':0,'review_state':'unavailable','summary':'视觉检查未完成','issues':[]})
    with Session() as session:
        job=session.get(Job,jid)
        if job.status=='cancelled':return
        asset=session.get(Asset,best['asset_id']);metadata=json.loads(asset.metadata_json)
        metadata.update(design_engine='OpenDesign',design_revision=design_engine.REVISION,review=review,
                        attempts=[{'asset_id':a['asset_id'],'task_id':a['remote_id'],'review':a.get('review')} for a in attempts],
                        design_spec=best['design']['spec'],planner_model=best['design'].get('model'))
        asset.kind='ai_poster';asset.metadata_json=json.dumps(metadata,ensure_ascii=False)
        job.status='completed';job.updated_at=now()
        if review.get('review_state')!='completed':job.step='海报已保存，视觉检查未完成，请人工核对'
        elif review.get('verdict')=='pass':job.step='OpenDesign视觉检查通过，请核对后使用'
        else:job.step='海报已保存，仍有检查项需要人工确认'
        job.error=note
        job.result=json.dumps({'asset_id':asset.id,'work_id':payload['work_id'],'work_version':payload['work_version'],
                               'model':payload['model'],'design_engine':'OpenDesign','review':review,
                               'attempts':metadata['attempts']},ensure_ascii=False)
        job.payload=json.dumps(payload,ensure_ascii=False);session.commit()


async def run_workflow(jid,reference_encoder,poll_seconds,image_key,downloader,service=None):
    with Session() as session:
        job=session.get(Job,jid);payload=json.loads(job.payload);actor=job.actor_id;existing_remote=job.remote_id
    service=service or image_settings.get_config(base=IMAGE_BASE,model=payload['model'],key=image_key)
    state=payload.setdefault('opendesign',{'round':0,'attempts':[],'phase':'planning'})
    if existing_remote and not state.get('remote_id'):state['remote_id']=existing_remote
    folder=DATA/'poster_runs'/jid;folder.mkdir(parents=True,exist_ok=True)
    reference=folder/'reference.png'
    terminal=False
    try:
        if not reference.exists():
            encoded=reference_encoder(payload)
            reference.write_bytes(base64.b64decode(encoded.split(',',1)[1]))
        async with image_settings.client(service,timeout=httpx.Timeout(90,connect=15)) as client:
            image_settings.bind_job(payload,service,remote=bool(state.get("remote_id")))
            persist(jid,payload)
            headers={'Authorization':'Bearer '+service.key,'Content-Type':'application/json'}
            while state['round']<2:
                if not job_active(jid):return
                if not state.get('design'):
                    job_update(jid,step='OpenDesign正在规划构图、配色和文案')
                    feedback={'review':state['attempts'][-1]['review'],'previous_spec':state['attempts'][-1]['design']['spec']} if state['attempts'] else None
                    async with text_lock:
                        design=await design_engine.plan(payload,reference,folder,feedback=feedback)
                    if not job_active(jid):return
                    state.update(design=design,phase='ready',submission='not_started')
                    persist(jid,payload)
                    (folder/f'design-{state["round"]}.json').write_text(json.dumps(design,ensure_ascii=False,indent=2),encoding='utf-8')
                if not state.get('remote_id') and not state.get('candidate_id'):
                    if state.get('submission')=='in_flight':
                        raise ValueError('上次提交结果未确认，请先核查魔搭任务记录；不会自动再次提交')
                    with Session() as session:
                        work=session.get(Work,payload['work_id'])
                        if not work or work.version!=payload['work_version']:raise ValueError('作品已变化，请重新确认后生成')
                        report=json.loads(work.report)
                        if has_source_conflict(report) or report.get('status') not in {'passed','manual_passed'}:raise ValueError('作品尚未通过内容检查')
                    image=reference_encoder(payload)
                    if not job_active(jid):return
                    width,height=SIZES[payload['ratio']]
                    state.update(submission='in_flight',phase='submitting')
                    persist(jid,payload,step='AI正在根据设计方案生成整张海报')
                    response=await client.post(service.base+'/images/generations',headers={**headers,'X-ModelScope-Async-Mode':'true'},
                        json={'model':payload['model'],'prompt':state['design']['prompt'],'image_url':[image],'size':f'{width}x{height}'})
                    if response.status_code!=200:
                        state['submission']='rejected'
                        try:detail=str(response.json().get('errors',{}).get('message',''))[:400]
                        except (ValueError,AttributeError):detail=''
                        state['provider_error']=detail;persist(jid,payload)
                        if response.status_code in {401,403}:raise ValueError('图片服务鉴权或模型权限不足')
                        if response.status_code==429:raise ValueError('图片额度不足或服务限流')
                        raise ValueError(f'图片服务拒绝请求（HTTP {response.status_code}）：{detail}')
                    remote=response.json().get('task_id')
                    if not remote:raise ValueError('提交结果未确认，已停止自动重试，请核查魔搭任务记录')
                    state.update(remote_id=remote,submission='accepted',phase='generating')
                    persist(jid,payload,remote_id=remote,step='AI正在生成海报画面和文字')
                if not state.get('candidate_id'):
                    deadline=time.monotonic()+poll_seconds
                    while time.monotonic()<deadline:
                        if not job_active(jid):return
                        response=await client.get(service.base+'/tasks/'+state['remote_id'],headers={**headers,'X-ModelScope-Task-Type':'image_generation'})
                        response.raise_for_status();result=response.json();status=result.get('task_status')
                        if status=='SUCCEED':
                            urls=result.get('output_images',[])
                            if not urls:raise ValueError('远端成功但未返回图片')
                            blob=await downloader(urls[0])
                            if not job_active(jid):return
                            with Session() as session:
                                current=session.get(Job,jid)
                                if current.status=='cancelled':return
                                assets=DATA/'assets';assets.mkdir(exist_ok=True);destination=assets/f'{jid}-r{state["round"]}.png'
                                with Image.open(io.BytesIO(blob)) as image:image.convert('RGB').save(destination,format='PNG')
                                metadata={'work_id':payload['work_id'],'work_version':payload['work_version'],'generation':'full_image',
                                    'product_image_id':payload['image_id'],'product_source':payload['source'],'reference_sha256':payload['source_sha256'],
                                    'model':payload['model'],'task_id':state['remote_id'],'scene':payload['scene'],'ratio':payload['ratio'],
                                    'design_engine':'OpenDesign','design_revision':design_engine.REVISION,'prompt':state['design']['prompt'],
                                    'review':{'review_state':'pending'},'label':'AI创意效果，需对照参考原图核对'}
                                asset=Asset(actor_id=actor,kind='ai_poster_candidate',path=str(destination),metadata_json=json.dumps(metadata,ensure_ascii=False))
                                session.add(asset);session.flush();state.update(candidate_id=asset.id,phase='reviewing')
                                state['attempts'].append({'asset_id':asset.id,'remote_id':state['remote_id'],'design':state['design']})
                                current.payload=json.dumps(payload,ensure_ascii=False);session.commit()
                            break
                        if status in {'FAILED','CANCELED','CANCELLED'}:
                            terminal=True;raise ValueError('远端海报生成失败，已保留此前成图')
                        await asyncio.sleep(5)
                    if not state.get('candidate_id'):
                        persist(jid,payload,status='waiting_remote',step='海报仍在生成，可继续查询原任务',error='远端任务编号已保存，不会重新提交')
                        return
                attempt=state['attempts'][-1]
                if not attempt.get('review'):
                    if not job_active(jid):return
                    job_update(jid,step='OpenDesign正在对照原图检查产品外观、文字和版式')
                    with Session() as session:poster_path=Path(session.get(Asset,state['candidate_id']).path)
                    async with text_lock:
                        report=await design_engine.review(payload,state['design'],poster_path,reference,folder,state['round']+1)
                    if not job_active(jid):return
                    attempt['review']=report;persist(jid,payload)
                    (folder/f'review-{state["round"]}.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
                report=attempt['review']
                if report.get('review_state')=='completed' and report.get('verdict') in {'revise','fail'} and state['round']==0:
                    state.update(round=1,phase='planning',design=None,candidate_id=None,remote_id=None,submission='not_started')
                    persist(jid,payload,remote_id='',step='OpenDesign正在按检查意见调整设计（最多一次）')
                    continue
                complete(jid,payload,state);return
    except Exception as error:
        if not job_active(jid):return
        message=str(error)[:500] if isinstance(error,ValueError) else '设计或图片服务暂时异常，已保留现有进度'
        if state.get('remote_id') and not state.get('candidate_id') and not terminal:
            persist(jid,payload,status='waiting_remote',step='服务暂时异常，可继续查询原任务',error=message)
        elif state['attempts']:
            complete(jid,payload,state,note=message)
        else:
            persist(jid,payload,status='failed',step='OpenDesign海报任务尚未完成',error=message)
