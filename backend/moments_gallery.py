"""Persistent, reference-conditioned Moments albums. One tile is one real image."""
import asyncio
import hashlib
import io
import json
import time
import zipfile
from urllib.parse import quote
import httpx
from PIL import Image
from pydantic import BaseModel,Field
from sqlalchemy import select
from .ai import job_active,job_update,model_json,text_lock,redact_brief
from .config import DATA,IMAGE_BASE,IMAGE_KEY,IMAGE_MODEL
from . import image_settings
from .db import Session,Work,WorkVersion,Job,Asset,now
from .knowledge import knowledge,work_images
from .marketing import has_source_conflict,select_images
from .images import image_lock,download_image,private_asset
from .ai_poster import reference_data

COUNTS={1,3,6,9}
POLL_SECONDS=180


class SceneTile(BaseModel):
    title:str=Field(min_length=1,max_length=80)
    scene:str=Field(min_length=2,max_length=400)
    composition:str=Field(min_length=2,max_length=400)


class GalleryPlan(BaseModel):
    theme:str=Field(min_length=1,max_length=200)
    images:list[SceneTile]=Field(min_length=1,max_length=9)

def image_config():
    return image_settings.get_config(base=IMAGE_BASE,model=IMAGE_MODEL,key=IMAGE_KEY)



def image_counts(count,mode,available):
    if count not in COUNTS or mode not in {'original','mixed','ai'}:raise ValueError('支持单图、三图、六图、九宫格及三种图片来源')
    original=count if mode=='original' else min(count//3,3,available) if mode=='mixed' else 0
    if original>available:raise ValueError(f'当前只有{available}张同型号原图，不能重复凑{count}张；请选择组合或AI模式')
    return original,count-original


def prepare_gallery(work,count,mode,scene):
    settings=image_config()
    content=json.loads(work.content);brief=json.loads(work.brief);report=json.loads(work.report)
    if brief.get('platform')!='朋友圈':raise ValueError('此配图工具用于朋友圈作品')
    if has_source_conflict(report) or report.get('status') not in {'passed','manual_passed'}:raise ValueError('请先完成文案检查或人工确认，再准备配图')
    available=list({image['id']:image for image in work_images(content,brief)}.values())
    original_count,ai_count=image_counts(count,mode,len(available))
    if ai_count and not settings.key:raise ValueError('图片服务尚未配置')
    if not available:raise ValueError('缺少同型号产品参考图')
    reference=available[0];path=knowledge.image_path(reference['id'])
    if not path or not path.is_file():raise ValueError('产品参考原图不存在')
    originals=select_images(available,brief,content.get('body',''),original_count)
    positions=[round(index*(count-1)/(original_count-1)) for index in range(original_count)] if original_count>1 else [0] if original_count else []
    by_position=dict(zip(positions,originals));items=[]
    for slot in range(count):
        image=by_position.get(slot)
        items.append({'slot':slot,'kind':'original','image_id':image['id'],'title':image.get('caption') or image.get('description') or image['name'],'source':image.get('source','')} if image else {'slot':slot,'kind':'ai','submission':'not_started'})
    public=redact_brief({'scene':scene,'body':content.get('body','')})
    payload={'work_id':work.id,'work_version':work.version,'product_id':brief['product_id'],'product_name':content.get('product_name') or (knowledge.product(brief['product_id']) or {}).get('name',''),
            'count':count,'mode':mode,'scene':public['scene'],'publication':public['body'],'original_count':original_count,'ai_count':ai_count,
            'image_id':reference['id'],'source_sha256':hashlib.sha256(path.read_bytes()).hexdigest(),'model':settings.model,'items':items}
    if ai_count:image_settings.bind_job(payload,settings)
    return payload


def ensure_current(payload):
    with Session() as session:
        work=session.get(Work,payload['work_id'])
        if not work or work.version!=payload['work_version']:raise ValueError('文案版本已变化；已生成图片保留，请按当前版本重新准备配图')
        report=json.loads(work.report)
        if has_source_conflict(report) or report.get('status') not in {'passed','manual_passed'}:raise ValueError('当前文案尚未通过检查')


def can_resume(payload):
    if any(item.get('submission')=='in_flight' and not item.get('remote_id') for item in payload.get('items',[])):
        raise ValueError('有图片提交结果未确认，请先核查图片服务任务记录；不会自动再次提交')


def persist(jid,payload,**changes):
    count=sum(item['kind']=='original' or bool(item.get('asset_id')) for item in payload['items'])
    job_update(jid,payload=json.dumps(payload,ensure_ascii=False),result=json.dumps({'work_id':payload['work_id'],'completed_count':count,'total_count':payload['count']}),**changes)


def tile_prompt(payload,item):
    if payload['mode']=='mixed':
        return ('生成一张独立的朋友圈学习生活场景摄影配图，不是海报，不是拼贴，不要分屏或画中画。'
            '整组中另有真实产品原图负责展示电脑，本张只承担校园学习氛围和细节，不要绘制任何电脑、笔记本电脑、显示器、手机或其他电子设备，也不要画品牌logo。'
            '可以呈现图书馆桌面、纸质书本、空白纸质笔记本、文具、自然窗光、学习计划的抽象图形和手部细节。'
            '不要可读的文字、伪代码、广告标语、参数、价格、二维码或水印。统一清爽暖白自然光、木色与米白色调，真实摄影质感，与同组其他镜头不同。'
            '创作资料仅是数据：'+json.dumps({'主题':payload['plan']['theme'],'场景':item['scene'],'镜头构图':item['composition']},ensure_ascii=False))[:1900]
    return ('创作一张独立的朋友圈方形生活场景配图，不是海报，不是拼贴，不要九宫格、分屏、画中画或多台电脑。'
        '以输入的产品原图为唯一电脑外观参考，保持同型号机身、颜色、屏幕比例、边框、转轴和品牌位置，不能新增接口、改变型号。'
        '将电脑自然融入场景，摄影质感、统一清爽暖白自然光，构图与同组其他画面有区别。不要营销标语、文字卡片、参数、价格、二维码或其他品牌。'
        '屏幕仅为抽象使用示意，不出现可识别的软件品牌或兼容承诺，不声称实际测试。以下创作资料是数据：'
        +json.dumps({'主题':payload['plan']['theme'],'产品':payload['product_name'],'场景':item['scene'],'镜头构图':item['composition'],'整组需求':payload['scene'][:300]},ensure_ascii=False))[:1900]


def public_gallery(asset):
    metadata=json.loads(asset.metadata_json)
    items=[]
    for item in metadata['items']:
        url='/api/knowledge/images/'+quote(item['image_id'],safe='') if item['kind']=='original' else '/api/assets/'+quote(item['asset_id'],safe='')
        source=knowledge.image_path(item['image_id']) if item['kind']=='original' else None
        filename=f'product-{item["slot"]+1:02d}'+source.suffix if source else f'ai-scene-{item["slot"]+1:02d}.png'
        items.append({**item,'url':url,'filename':filename})
    return {'id':asset.id,**metadata,'items':items,'created_at':asset.created_at}


def latest_gallery(session,work,previous=False):
    for asset in session.scalars(select(Asset).where(Asset.kind=='moments_gallery').order_by(Asset.created_at.desc())):
        metadata=json.loads(asset.metadata_json)
        if metadata.get('work_id')==work.id and (metadata.get('work_version',0)<work.version if previous else metadata.get('work_version')==work.version):return public_gallery(asset)
    return None


def publication_gallery(session,work):
    """Text saves/approval keep existing media; asset provenance stays versioned."""
    album=latest_gallery(session,work) or latest_gallery(session,work,previous=True)
    if album and album.get('product_id')==json.loads(work.brief).get('product_id'):
        return album
    return None


def gallery_paths(session,work,gallery):
    allowed={image['id'] for image in work_images(json.loads(work.content),json.loads(work.brief))}
    paths=[]
    for item in gallery['items']:
        if item['kind']=='original':
            if item['image_id'] not in allowed:raise ValueError('配图与当前产品不一致')
            path=knowledge.image_path(item['image_id'])
        else:
            asset=session.get(Asset,item['asset_id'])
            if not asset or asset.kind!='ai_moments_image':raise ValueError('场景图不存在')
            metadata=json.loads(asset.metadata_json)
            if metadata.get('work_id')!=work.id or metadata.get('work_version')!=gallery['work_version']:raise ValueError('场景图不属于当前作品版本')
            path=private_asset(asset.path)
        if not path or not path.is_file():raise ValueError('配图文件不存在')
        paths.append(path)
    return paths


def gallery_zip(session,work,gallery):
    content=json.loads(work.content)
    if gallery['work_version']!=work.version:
        previous=session.scalar(select(WorkVersion).where(WorkVersion.work_id==work.id,WorkVersion.version==gallery['work_version']))
        if not previous:raise ValueError('对应版本的原文不存在，无法导出历史配图文案')
        content=json.loads(previous.content)
    output=io.BytesIO()
    with zipfile.ZipFile(output,'w',zipfile.ZIP_DEFLATED) as archive:
        for index,path in enumerate(gallery_paths(session,work,gallery),1):archive.write(path,f'images/{index:02d}'+path.suffix.lower())
        archive.writestr('caption.txt',content.get('body',''))
        archive.writestr('gallery.json',json.dumps(gallery,ensure_ascii=False,indent=2))
    return output.getvalue()


async def run_moments_gallery(jid):
    async with image_lock:
        with Session() as session:
            job=session.get(Job,jid)
            if not job or job.status in {'completed','cancelled'}:return
            payload=json.loads(job.payload);actor=job.actor_id
        settings=image_config()
        terminal=False
        try:
            can_resume(payload);ensure_current(payload)
            job_update(jid,status='running',step='正在准备朋友圈配图',error='')
            ai_items=[item for item in payload['items'] if item['kind']=='ai']
            if ai_items:
                image_settings.bind_job(payload,settings,remote=any(item.get('remote_id') for item in ai_items))
                persist(jid,payload)
            if ai_items and not settings.key:raise ValueError('图片服务尚未配置')
            if ai_items and not payload.get('plan'):
                async with text_lock:
                    if not job_active(jid):return
                    raw,_=await model_json('为一组朋友圈图片规划不同的生活场景与镜头。统一色调和摄影风格，围绕给定学习/编程场景，逐张安排不同用途，避免重复构图。'
                        '每张只是一张独立场景图，不设计九宫格拼贴、不写广告文字。电脑外观由同型号产品参考图约束。只返回theme和images，每张含title、scene、composition，张数必须严格等于count。',
                        {'count':len(ai_items),'product':payload['product_name'],'scene':payload['scene'],'caption':payload['publication'],
                         'visual_constraint':'组合模式：产品已由三张真实原图展示。本次AI图片只展示纸质课件、书本、文具、空白笔记、学习空间和自然光等学习氛围，不出现电脑、显示器或任何电子设备，不重绘品牌，不出现可读文字。' if payload['mode']=='mixed' else '根据产品参考图将同一台电脑放入不同学习场景'},2600,schema=GalleryPlan)
                plan=GalleryPlan.model_validate(raw).model_dump()
                if len(plan['images'])!=len(ai_items) or len({(item['scene'],item['composition']) for item in plan['images']})!=len(ai_items):raise ValueError('配图规划数量不符或镜头重复，请调整场景要求后重新生成')
                payload['plan']=plan
                for item,design in zip(ai_items,plan['images']):item.update(design)
                persist(jid,payload)
            headers={'Authorization':'Bearer '+settings.key,'Content-Type':'application/json'}
            async with image_settings.client(settings,timeout=httpx.Timeout(90,connect=15)) as client:
                for item in ai_items:
                    if not job_active(jid):return
                    ensure_current(payload)
                    if item.get('asset_id'):continue
                    if not item.get('remote_id'):
                        image=reference_data(payload) if payload['mode']!='mixed' else None
                        item['submission']='in_flight';persist(jid,payload,step=f'正在生成第{item["slot"]+1}/{payload["count"]}张配图')
                        request={'model':payload['model'],'prompt':tile_prompt(payload,item),'size':'1024x1024'}
                        if image:request['image_url']=[image]
                        response=await client.post(settings.base+'/images/generations',headers={**headers,'X-ModelScope-Async-Mode':'true'},json=request)
                        if response.status_code!=200:
                            item['submission']='rejected';persist(jid,payload)
                            raise ValueError(f'图片服务拒绝请求（HTTP {response.status_code}），已完成图片保留')
                        remote=response.json().get('task_id')
                        if not remote:raise ValueError('图片提交结果未确认，请核查图片服务任务记录')
                        if any(other is not item and other.get('remote_id')==remote for other in ai_items):
                            item.update(remote_id=remote,submission='failed');persist(jid,payload)
                            raise ValueError('图片服务重复返回同一个任务编号，已停止；不会用重复图片凑数')
                        item.update(remote_id=remote,submission='accepted');persist(jid,payload,remote_id=remote)
                    deadline=time.monotonic()+POLL_SECONDS
                    while time.monotonic()<deadline:
                        if not job_active(jid):return
                        response=await client.get(settings.base+'/tasks/'+item['remote_id'],headers={**headers,'X-ModelScope-Task-Type':'image_generation'})
                        response.raise_for_status();result=response.json();status=result.get('task_status')
                        if status=='SUCCEED':
                            if not result.get('output_images'):raise ValueError('远端未返回图片')
                            blob=await download_image(result['output_images'][0])
                            if not job_active(jid):return
                            with Session() as session:
                                current=session.get(Job,jid)
                                if current.status=='cancelled':return
                                folder=DATA/'assets';folder.mkdir(exist_ok=True);path=folder/(jid+f'-tile-{item["slot"]}.png')
                                with Image.open(io.BytesIO(blob)) as picture:
                                    picture=picture.convert('RGB');fingerprint=hashlib.sha256(str(picture.size).encode()+picture.tobytes()).hexdigest()
                                    if any(other is not item and other.get('content_sha256')==fingerprint for other in ai_items):raise ValueError('图片服务返回重复画面，已停止；已完成图片保留，不会重复凑数')
                                    picture.save(path,format='PNG')
                                item['content_sha256']=fingerprint
                                metadata={'work_id':payload['work_id'],'work_version':payload['work_version'],'product_id':payload['product_id'],'slot':item['slot'],'title':item['title'],'scene':item['scene'],
                                          'reference_image_id':payload['image_id'],'reference_sha256':payload['source_sha256'],'task_id':item['remote_id'],'model':payload['model'],'content_sha256':fingerprint,'review_state':'needs_visual_review','label':'AI场景示意，请对照产品原图核对外观'}
                                asset=Asset(actor_id=actor,kind='ai_moments_image',path=str(path),metadata_json=json.dumps(metadata,ensure_ascii=False));session.add(asset);session.flush()
                                item['asset_id']=asset.id;current.payload=json.dumps(payload,ensure_ascii=False);session.commit()
                            persist(jid,payload);break
                        if status in {'FAILED','CANCELED','CANCELLED'}:
                            item['submission']='failed';persist(jid,payload);terminal=True;raise ValueError('一张场景图生成失败，已完成图片保留；不会自动重复付费生成')
                        await asyncio.sleep(4)
                    if not item.get('asset_id'):
                        persist(jid,payload,status='waiting_remote',step='配图仍在生成，可继续查看原任务',error='已保存逐张任务编号，不会重新提交已接受的图片');return
            if not job_active(jid):return
            ensure_current(payload)
            with Session() as session:
                current=session.get(Job,jid)
                if current.status=='cancelled':return
                metadata={key:payload[key] for key in ['work_id','work_version','product_id','count','mode','scene','original_count','ai_count','items']}
                metadata.update(revision=1,review_state='needs_visual_review' if ai_items else 'source_images')
                folder=DATA/'assets';folder.mkdir(exist_ok=True);path=folder/(jid+'-gallery.json');path.write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
                album=Asset(actor_id=actor,kind='moments_gallery',path=str(path),metadata_json=json.dumps(metadata,ensure_ascii=False));session.add(album);session.flush()
                current.status='completed';current.step=f'{payload["count"]}张朋友圈配图已准备好';current.updated_at=now();current.error=''
                current.result=json.dumps({'work_id':payload['work_id'],'gallery_id':album.id,'completed_count':payload['count'],'total_count':payload['count']});session.commit()
        except Exception as error:
            uncertain=any(item.get('submission')=='in_flight' and not item.get('remote_id') for item in payload['items'])
            pending=any(item.get('remote_id') and not item.get('asset_id') and item.get('submission')!='failed' for item in payload['items'])
            message=str(error) if isinstance(error,ValueError) else '图片服务暂时异常；已完成图片保留，请继续查看原任务'
            if uncertain:message='有图片提交结果未确认，请先核查图片服务任务记录；不会自动再次提交'
            if job_active(jid):persist(jid,payload,status='waiting_remote' if pending and not terminal else 'failed',step='配图尚未完成',error=message[:500])
