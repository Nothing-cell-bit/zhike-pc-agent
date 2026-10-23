import asyncio
import io
import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image
from .config import DATA,IMAGE_BASE,IMAGE_KEY,IMAGE_MODEL
from .db import Session,Job,Asset,Work,now
from .ai import job_update,job_active,model_json,text_lock,redact_brief
from .knowledge import knowledge,work_images
from .marketing import has_source_conflict
from .poster_renderer import render_poster

image_lock=asyncio.Lock()
SIZES={'1:1':(1024,1024),'3:4':(960,1280),'16:9':(1280,720)}

def private_asset(path):
    path=Path(path).resolve()
    if not path.is_relative_to(DATA):raise ValueError('非法资产路径')
    return path

async def download_image(url):
    """Never forward API auth to generated media URLs or follow private redirects."""
    async with httpx.AsyncClient(timeout=30,trust_env=False,follow_redirects=False) as client:
        for _ in range(4):
            p=urlparse(url)
            if p.scheme!='https' or not p.hostname or p.username:raise ValueError('图片下载地址不安全')
            for info in await asyncio.to_thread(socket.getaddrinfo,p.hostname,443):
                if not ipaddress.ip_address(info[4][0]).is_global:raise ValueError('拒绝内网图片下载地址')
            async with client.stream('GET',url) as r:
                if r.status_code in {301,302,303,307,308}:
                    from urllib.parse import urljoin
                    url=urljoin(url,r.headers.get('location',''));continue
                r.raise_for_status();chunks=[];size=0
                async for chunk in r.aiter_bytes():
                    size+=len(chunk)
                    if size>20_000_000:raise ValueError('生成图片超过20MB限制')
                    chunks.append(chunk)
                data=b''.join(chunks)
                with Image.open(io.BytesIO(data)) as im:
                    if im.width*im.height>25_000_000:raise ValueError('生成图像尺寸过大')
                    im.verify()
                return data
    raise ValueError('图片下载重定向过多')

async def run_image(jid):
    async with image_lock:
        with Session() as s:
            j=s.get(Job,jid)
            if not j or j.status in {'cancelled','completed'}:return
            payload=json.loads(j.payload);remote=j.remote_id;actor=j.actor_id
        if not IMAGE_KEY:job_update(jid,status='failed',step='未配置',error='魔搭图片Token尚未配置');return
        job_update(jid,status='running',step='准备生成场景背景')
        terminal_failure=False
        try:
            headers={'Authorization':'Bearer '+IMAGE_KEY,'Content-Type':'application/json'}
            async with httpx.AsyncClient(timeout=httpx.Timeout(35,connect=8),trust_env=False) as c:
                if not remote:
                    async with text_lock:
                        if not job_active(jid):return
                        obj,_=await model_json('为营销海报生成一个英文背景提示词，返回prompt。必须只有场景环境，不出现电脑、手机、产品、logo、文字、数字；中央留白适合放产品卡片。不含人物隐私，不生成产品外观。60英文单词以内。',redact_brief({'scene':payload['scene'],'ratio':payload.get('ratio','3:4')}),300)
                    if not job_active(jid):return
                    prompt=str(obj.get('prompt',''))[:900]+' Empty environment only. No computers, no devices, no text, no logo. Clear central negative space.'
                    payload['generated_prompt']=prompt;job_update(jid,payload=json.dumps(payload,ensure_ascii=False),step='正在提交魔搭背景任务')
                    width,height=SIZES.get(payload.get('ratio'),SIZES['3:4'])
                    r=await c.post(IMAGE_BASE+'/images/generations',headers={**headers,'X-ModelScope-Async-Mode':'true'},json={'model':IMAGE_MODEL,'prompt':prompt,'size':f'{width}x{height}'})
                    if r.status_code in {401,403}:
                        if 'email verification' in r.text.lower():raise ValueError('魔搭账号需要先完成邮箱验证，才能使用魔粒生图。请在魔搭账号设置完成验证后重新生成。')
                        raise ValueError('魔搭鉴权或模型权限不足，请检查Token归属和权限')
                    if r.status_code==429:raise ValueError('魔搭额度不足或服务限流，请稍后查询账号额度')
                    r.raise_for_status();remote=r.json().get('task_id')
                    if not remote:raise ValueError('魔搭没有返回任务编号')
                    job_update(jid,remote_id=remote,step='魔搭正在生成背景')
                deadline=time.monotonic()+180
                while time.monotonic()<deadline:
                    with Session() as s:
                        if s.get(Job,jid).status=='cancelled':return
                    r=await c.get(IMAGE_BASE+'/tasks/'+remote,headers={**headers,'X-ModelScope-Task-Type':'image_generation'})
                    r.raise_for_status();out=r.json();status=out.get('task_status','')
                    if status=='SUCCEED':
                        urls=out.get('output_images',[])
                        if not urls:raise ValueError('远端任务成功但没有图片')
                        blob=await download_image(urls[0]);folder=DATA/'assets';folder.mkdir(exist_ok=True)
                        with Image.open(io.BytesIO(blob)) as im:
                            dest=folder/(jid+'.png');im.convert('RGB').save(dest)
                        with Session() as s:
                            asset=Asset(actor_id=actor,kind='generated_background',path=str(dest),metadata_json=json.dumps({'model':IMAGE_MODEL,'task_id':remote,'prompt':payload.get('generated_prompt'),'source':'ModelScope','ratio':payload.get('ratio'),'account_verified':False},ensure_ascii=False))
                            s.add(asset);s.commit();aid=asset.id
                        job_update(jid,status='completed',step='背景已生成',result=json.dumps({'asset_id':aid,'remote_id':remote,'model':IMAGE_MODEL}));return
                    if status in {'FAILED','CANCELED','CANCELLED'}:
                        terminal_failure=True
                        raise ValueError('魔搭生成失败，请检查模型权限、额度或提示词')
                    await asyncio.sleep(5)
                job_update(jid,status='waiting_remote',step='远端仍在处理，可继续查询原任务',error='已等待180秒；任务编号已保存，不会自动再次提交')
        except Exception as e:
            safe=str(e) if isinstance(e,ValueError) else f'图片服务异常（{type(e).__name__}）；远端编号如已生成会保留，可继续查询'
            job_update(jid,status='waiting_remote' if remote and not terminal_failure else 'failed',step='图片任务未完成',error=safe[:600])

def compose(work_id,actor,image_id,background_id='',ratio='3:4',style='studio'):
    with Session() as s:
        work=s.get(Work,work_id)
        if not work:raise ValueError('作品不存在')
        report=json.loads(work.report)
        if has_source_conflict(report):raise ValueError('资料存在冲突，请人工确认并重新检查后制作海报')
        if report.get('status') not in {'passed','manual_passed'}:raise ValueError('请先保存并通过内容检查或人工确认，再制作海报')
        content=json.loads(work.content);brief=json.loads(work.brief)
        product=knowledge.product(brief['product_id'])
        image=next((x for x in work_images(content,brief) if x['id']==image_id),None)
        if not image:raise ValueError('产品图与作品型号不一致')
        background=s.get(Asset,background_id) if background_id else None
        if background_id and (not background or background.kind!='generated_background'):raise ValueError('背景不存在')
        source='ima 共享知识库' if content.get('source_type')=='ima' else '本地知识库'
        label=('AI 场景背景 · ' if background else '')+'产品图来自'+source+' · 以实际销售版本为准'
        dest=DATA/'assets'/f'poster-{work.id}-{work.version}-{int(time.time()*1000)}.png';dest.parent.mkdir(exist_ok=True)
        design=render_poster(content,(product or {}).get('name') or content.get('product_name','产品体验'),
                             knowledge.image_path(image_id),private_asset(background.path) if background else None,
                             SIZES[ratio],style,label,dest)
        # ima snapshots keep media URLs private; use the authenticated cached image route.
        product_image_url=image.get('url') or '/api/knowledge/images/'+image_id
        metadata={'work_id':work.id,'work_version':work.version,'background_id':background_id,'product_image_id':image_id,'product_source':image['source'],'product_image_url':product_image_url,'ratio':ratio,'label':label,**design,'verification':json.loads(work.report).get('status')}
        asset=Asset(actor_id=actor,kind='composite',path=str(dest),metadata_json=json.dumps(metadata,ensure_ascii=False));s.add(asset);s.commit()
        return {'id':asset.id,'metadata':metadata}
