import asyncio
import io
import ipaddress
import json
import socket
import time
from pathlib import Path
from urllib.parse import urlparse
import httpx
from PIL import Image,ImageDraw,ImageFont,ImageOps
from .config import DATA,IMAGE_BASE,IMAGE_KEY,IMAGE_MODEL
from .db import Session,Job,Asset,Work,now
from .ai import job_update,job_active,model_json,text_lock,redact_brief
from .knowledge import knowledge,work_images
from .marketing import has_source_conflict

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

def font(size):
    paths=[Path('C:/Windows/Fonts/msyh.ttc'),Path('/usr/share/fonts/truetype/noto/NotoSansCJK-Regular.ttc'),Path('/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc')]
    for p in paths:
        if p.exists():return ImageFont.truetype(str(p),size)
    return ImageFont.load_default()

def lines(draw,text,f,maxwidth,maxlines):
    result=[];line=''
    truncated=False
    for index,char in enumerate(text):
        if char=='\n' or draw.textlength(line+char,font=f)>maxwidth:
            result.append(line);line='' if char=='\n' else char
            if len(result)>=maxlines:
                truncated=True;break
        else:line+=char
    if line and len(result)<maxlines:result.append(line)
    if truncated and result:
        while result[-1] and draw.textlength(result[-1]+'…',font=f)>maxwidth:result[-1]=result[-1][:-1]
        result[-1]+='…'
    return result

def compose(work_id,actor,image_id,background_id='',ratio='3:4'):
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
        w,h=SIZES[ratio];margin=int(w*.065)
        canvas=Image.new('RGB',(w,h),'#f2efea')
        if background:
            with Image.open(private_asset(background.path)) as bg:canvas=ImageOps.fit(bg.convert('RGB'),(w,h))
            overlay=Image.new('RGBA',(w,h),(255,255,255,80));canvas=Image.alpha_composite(canvas.convert('RGBA'),overlay).convert('RGB')
        d=ImageDraw.Draw(canvas);d.rounded_rectangle((margin,margin,w-margin,h-margin),radius=24,fill='#fffdf9')
        d.text((margin*1.5,margin*1.4),'知客  /  到店体验',font=font(max(14,int(w*.018))),fill='#a72930')
        landscape=w>h
        text_x=int(margin*1.5);text_width=int(w*.43) if landscape else w-margin*3
        title_y=int(h*.24) if landscape else int(margin*2.15)
        title_size=int(w*.032) if landscape else int(w*.043)
        title_step=int(title_size*1.4);title_count=3 if landscape else 2
        y=title_y;f=font(title_size)
        for l in lines(d,content.get('title','产品体验'),f,text_width,title_count):d.text((text_x,y),l,font=f,fill='#232323');y+=title_step
        top=int(h*.24) if landscape else int(h*.29)
        box=(int(w*.32),int(h*.50)) if landscape else (int(w*.76),int(h*.40))
        product_x=int(w*.58) if landscape else (w-box[0])//2
        with Image.open(knowledge.image_path(image_id)) as src:
            product_im=src.convert('RGBA');product_im.thumbnail(box)
            px=product_x+(box[0]-product_im.width)//2;py=top+(box[1]-product_im.height)//2
            canvas.paste(product_im,(px,py),product_im)
        d=ImageDraw.Draw(canvas);summary_y=int(h*.54) if landscape else int(h*.75);y=summary_y
        summary_size=int(w*.02) if landscape else int(w*.024);summary_step=int(summary_size*1.5)
        f=font(summary_size)
        # Posters use the short CTA; the complete article remains in text exports.
        for l in lines(d,content.get('cta') or content.get('intro','欢迎到店体验'),f,text_width,3 if landscape else 2):d.text((text_x,y),l,font=f,fill='#444444');y+=summary_step
        label='AI场景合成 · 产品图来自知识库' if background else '产品图来自本地知识库 · 以实际销售版本为准'
        if json.loads(work.report).get('status') not in {'passed','manual_passed'}:label='待确认草稿 · '+label
        source_y=int(h-margin*1.9)
        d.text((text_x,source_y),label,font=font(max(12,int(w*.015))),fill='#79736b')
        dest=DATA/'assets'/f'poster-{work.id}-{work.version}-{int(time.time()*1000)}.png';dest.parent.mkdir(exist_ok=True);canvas.save(dest)
        layout={'title':[text_x,title_y,text_x+text_width,title_y+title_step*title_count],'product':[px,py,px+product_im.width,py+product_im.height],'summary':[text_x,summary_y,text_x+text_width,y],'source':[text_x,source_y,w-margin,source_y+max(12,int(w*.02))]}
        metadata={'work_id':work.id,'work_version':work.version,'background_id':background_id,'product_image_id':image_id,'product_source':image['source'],'product_image_url':image['url'],'ratio':ratio,'label':label,'layout':layout,'verification':json.loads(work.report).get('status')}
        asset=Asset(actor_id=actor,kind='composite',path=str(dest),metadata_json=json.dumps(metadata,ensure_ascii=False));s.add(asset);s.commit()
        return {'id':asset.id,'metadata':metadata}
