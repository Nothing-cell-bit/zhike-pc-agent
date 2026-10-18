import asyncio
import hashlib
import html
import io
import json
import os
import secrets
import sqlite3
import time
import zipfile
from collections import defaultdict,deque
from contextlib import asynccontextmanager
from datetime import datetime,timedelta,timezone
from pathlib import Path
from typing import Literal
from urllib.parse import urlparse
import bleach
import httpx
import markdown
from argon2 import PasswordHasher
from argon2.exceptions import VerificationError
from fastapi import FastAPI,Depends,HTTPException,Request,Response,WebSocket,WebSocketDisconnect
from fastapi.responses import FileResponse,StreamingResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,update,func
from sqlalchemy.exc import IntegrityError
from .config import ROOT,DATA,IMAGE_KEY,IMAGE_MODEL
from . import model_settings
from .db import *
from .knowledge import knowledge,import_zip,work_images
from .ima import connection_status
from .config import MARKETING_SOURCE
from .ai import spawn_job,delayed_analysis,job_update
from .requirements import build_requirements,SCHEMA_VERSION
from .marketing import place_images, unified_markdown, scenario_judgment, image_relative_url, has_source_conflict, has_inline_images
from .images import run_image,compose,private_asset
from .cli import backup,restore_drill

ph=PasswordHasher()
STAFF={'staff','admin'}
STAGES=['新咨询','需求确认','产品比较','考虑中','已成交','暂不购买']
connections=defaultdict(set)
rate=defaultdict(deque)

def audit(s,actor,action,target=''):s.add(Audit(actor_id=actor,action=action,target=target))
def js(value):return json.dumps(value,ensure_ascii=False)
def record(obj,exclude=()):
    d={col.name:getattr(obj,col.name) for col in obj.__table__.columns if col.name not in exclude}
    for k in ['analysis','locked','payload','result','brief','content','report','card','metadata_json']:
        if k in d and isinstance(d[k],str):
            try:d[k]=json.loads(d[k])
            except ValueError:pass
    return d

def clean_error(e):return str(e)[:500] if isinstance(e,ValueError) else '操作失败，请检查配置或稍后重试'

async def daily_backup():
    while True:
        await asyncio.sleep(3600)
        target=DATA/'backups'
        files=list(target.glob('*.db')) if target.exists() else []
        if not files or time.time()-max(p.stat().st_mtime for p in files)>86400:await asyncio.to_thread(backup)

@asynccontextmanager
async def lifespan(app):
    init_db()
    with Session() as s:
        for j in s.scalars(select(Job).where(Job.status.in_(['running','queued']))):
            j.status='waiting_remote' if j.remote_id else 'failed';j.step='服务重启，保留已有结果';j.error='可主动重试；远端图片任务将续查原编号'
        s.commit()
    task=asyncio.create_task(daily_backup())
    yield
    task.cancel()

app=FastAPI(title='知客 · 门店增长工作台',lifespan=lifespan)

@app.middleware('http')
async def secure(request,call_next):
    if request.url.path.startswith('/api/') and request.method not in {'GET','HEAD','OPTIONS'}:
        origin=request.headers.get('origin')
        if origin and urlparse(origin).netloc!=request.headers.get('host'):
            return JSONResponse({'detail':'跨站请求被拒绝'},403)
        if request.headers.get('x-store-request')!='1':return JSONResponse({'detail':'缺少请求校验头'},403)
        if int(request.headers.get('content-length','0') or '0')>250000:return JSONResponse({'detail':'请求过大'},413)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='same-origin'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Content-Security-Policy']="default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; script-src 'self'; connect-src 'self' ws: wss:; font-src 'self' data:; frame-ancestors 'none'; base-uri 'self'"
    if request.url.path.startswith('/api/'):response.headers['Cache-Control']='no-store'
    return response

def identify(cookie):
    if not cookie:return None
    with Session() as s:
        sess=s.get(LoginSession,hashlib.sha256(cookie.encode()).hexdigest())
        if not sess or sess.expires<now():return None
        user=s.get(User,sess.user_id)
        return user if user and user.active else None

def current(request:Request):
    u=identify(request.cookies.get('store_session'))
    if not u:raise HTTPException(401,'请登录或开始访客咨询')
    return u

def staff(u:User=Depends(current)):
    if u.role not in STAFF:raise HTTPException(403,'需要客服权限')
    return u

def admin(u:User=Depends(staff)):
    if u.role!='admin':raise HTTPException(403,'需要管理员权限')
    return u

def allowed_conv(s,cid,u,write=False):
    c=s.get(Conversation,cid)
    if not c:raise HTTPException(404,'会话不存在')
    if u.role not in STAFF and c.customer_id!=u.id:raise HTTPException(403,'无法访问该会话')
    if write and u.role in STAFF and c.owner_id!=u.id:raise HTTPException(409,'请先认领或接管此会话')
    return c

def set_session(s,u,response,request):
    old=request.cookies.get('store_session')
    if old:
        oldsess=s.get(LoginSession,hashlib.sha256(old.encode()).hexdigest())
        if oldsess:s.delete(oldsess)
    token=secrets.token_urlsafe(40)
    s.add(LoginSession(id=hashlib.sha256(token.encode()).hexdigest(),user_id=u.id,expires=(datetime.now(timezone.utc)+timedelta(days=14)).isoformat()))
    response.set_cookie('store_session',token,max_age=14*86400,httponly=True,secure=os.getenv('COOKIE_SECURE','false').lower()=='true',samesite='lax',path='/')

def public_user(u):return {'id':u.id,'username':u.username,'display_name':u.display_name,'role':u.role}

class Credentials(BaseModel):
    username:str=Field(min_length=3,max_length=40,pattern=r'^[A-Za-z0-9_\-]+$')
    password:str=Field(min_length=10,max_length=128)
    display_name:str=Field(default='',max_length=40)

class GuestInput(BaseModel):name:str=Field(default='访客',min_length=1,max_length=30)

@app.get('/api/me')
def me(request:Request):
    u=identify(request.cookies.get('store_session'))
    with Session() as s:initialized=s.scalar(select(func.count()).select_from(User).where(User.role=='admin'))>0
    return {'user':public_user(u) if u else None,'initialized':initialized}

@app.post('/api/auth/guest')
def guest(body:GuestInput,request:Request,response:Response):
    existing=identify(request.cookies.get('store_session'))
    if existing:return public_user(existing)
    with Session() as s:
        u=User(username='guest_'+uid(),display_name=body.name,password='!',role='guest');s.add(u);s.flush();set_session(s,u,response,request);s.commit();return public_user(u)

def auth_rate(request):
    key=request.client.host;dq=rate[key];t=time.monotonic()
    while dq and dq[0]<t-60:dq.popleft()
    if len(dq)>=12:raise HTTPException(429,'登录尝试过多，请一分钟后重试')
    dq.append(t)

@app.post('/api/auth/register')
def register(body:Credentials,request:Request,response:Response):
    auth_rate(request)
    old=identify(request.cookies.get('store_session'))
    with Session() as s:
        if s.scalar(select(User).where(User.username==body.username)):raise HTTPException(409,'用户名已使用')
        u=User(username=body.username,display_name=body.display_name or body.username,password=ph.hash(body.password),role='customer');s.add(u);s.flush()
        if old and old.role=='guest':s.execute(update(Conversation).where(Conversation.customer_id==old.id).values(customer_id=u.id,customer_name=u.display_name))
        set_session(s,u,response,request);audit(s,u.id,'register');s.commit();return public_user(u)

@app.post('/api/auth/login')
def login(body:Credentials,request:Request,response:Response):
    auth_rate(request);old=identify(request.cookies.get('store_session'))
    with Session() as s:
        u=s.scalar(select(User).where(User.username==body.username,User.active==True))
        try:valid=u and ph.verify(u.password,body.password)
        except VerificationError:valid=False
        if not valid:raise HTTPException(401,'账号或密码不正确')
        if old and old.role=='guest' and u.role=='customer':s.execute(update(Conversation).where(Conversation.customer_id==old.id).values(customer_id=u.id,customer_name=u.display_name))
        set_session(s,u,response,request);audit(s,u.id,'login');s.commit();return public_user(u)

@app.post('/api/auth/logout')
def logout(request:Request,response:Response):
    with Session() as s:
        token=request.cookies.get('store_session','');obj=s.get(LoginSession,hashlib.sha256(token.encode()).hexdigest())
        if obj:s.delete(obj);s.commit()
    response.delete_cookie('store_session');return {'ok':True}

class PasswordInput(BaseModel):
    old_password:str=Field(max_length=128)
    new_password:str=Field(min_length=10,max_length=128)

@app.post('/api/auth/password')
def change_password(body:PasswordInput,u=Depends(current)):
    with Session() as s:
        user=s.get(User,u.id)
        try:ph.verify(user.password,body.old_password)
        except VerificationError:raise HTTPException(400,'原密码不正确')
        user.password=ph.hash(body.new_password)
        for sess in s.scalars(select(LoginSession).where(LoginSession.user_id==u.id)):s.delete(sess)
        s.commit()
    return {'ok':True,'message':'密码已更新，请重新登录'}

@app.get('/api/products')
def products():
    if not knowledge.status().get('ready'):return []
    return [{k:v for k,v in p.items() if k not in {'summary','path'}} for p in knowledge.products()]

@app.get('/api/products/{pid}')
def product(pid:str,u=Depends(current)):
    p=knowledge.product(pid)
    if not p:raise HTTPException(404,'产品不存在')
    return p

@app.get('/api/knowledge/images/{iid}')
def product_image(iid:str,request:Request):
    if iid.startswith('ima-'):staff(current(request))
    path=knowledge.image_path(iid)
    if not path or not path.is_file():raise HTTPException(404,'图片不存在')
    return FileResponse(path)

@app.get('/api/knowledge/search')
def search(q:str='',product_id:str='',category:str='',u=Depends(staff)):
    if len(q)>300:raise HTTPException(400,'检索词太长')
    return knowledge.search(q,product_id,category)

@app.get('/api/knowledge/documents/{did}')
def document(did:str,u=Depends(staff)):
    doc=knowledge.document(did)
    if not doc:raise HTTPException(404,'资料不存在')
    return doc

async def broadcast(cid):
    for ws in list(connections[cid]):
        try:await ws.send_json({'event':'updated','conversation_id':cid})
        except Exception:connections[cid].discard(ws)

@app.get('/api/conversations')
def conversations(u=Depends(current)):
    with Session() as s:
        query=select(Conversation).order_by(Conversation.updated_at.desc())
        if u.role not in STAFF:query=query.where(Conversation.customer_id==u.id)
        users={x.id:x.display_name for x in s.scalars(select(User).where(User.role.in_(STAFF)))}
        result=[]
        for c in s.scalars(query):
            last=s.scalar(select(Message).where(Message.conversation_id==c.id).order_by(Message.seq.desc()).limit(1))
            rp=s.get(ReadPosition,c.id+':'+u.id)
            d=record(c,('analysis','locked'));d.update({'owner_name':users.get(c.owner_id,''),'last_message':last.content if last else '等待开始咨询','unread':max(0,c.seq-(rp.seq if rp else 0))});result.append(d)
        return result

@app.post('/api/conversations')
def new_conversation(u=Depends(current)):
    if u.role in STAFF:raise HTTPException(400,'请使用客户入口创建咨询')
    with Session() as s:
        c=Conversation(customer_id=u.id,customer_name=u.display_name);s.add(c);s.commit();return record(c,('analysis','locked'))

@app.get('/api/conversations/{cid}')
def get_conversation(cid:str,u=Depends(current)):
    with Session() as s:
        c=allowed_conv(s,cid,u);d=record(c)
        d['messages']=[record(m) for m in s.scalars(select(Message).where(Message.conversation_id==cid).order_by(Message.seq))]
        if u.role not in STAFF:d.pop('analysis',None);d.pop('locked',None)
        else:
            raw=d['analysis'];latest_customer=max((m['seq'] for m in d['messages'] if m['role']=='customer'),default=0)
            d['requires_analysis']=bool(latest_customer and raw.get('schema_version',0)<SCHEMA_VERSION)
            d['requirements_current']=not d['requires_analysis'] and c.analysis_seq>=latest_customer
            d['analysis']=build_requirements(raw,d['messages'],d['locked'],'已结束' if c.status=='closed' else c.stage)
            if d['requires_analysis']:
                d['analysis']['next_question']={'state':'refresh_required','field':'','text':'点击右上角更新需求，获取新的追问建议。'}
                d['analysis']['questions']=[]
            elif not d['requirements_current']:
                d['analysis']['next_question']={'state':'updating','field':'','text':'正在根据新消息更新建议。'}
                d['analysis']['questions']=[]
        key=cid+':'+u.id;rp=s.get(ReadPosition,key)
        if rp:rp.seq=c.seq
        else:s.add(ReadPosition(id=key,seq=c.seq))
        s.commit();return d

@app.post('/api/conversations/{cid}/claim')
async def claim(cid:str,u=Depends(staff)):
    with Session() as s:
        allowed_conv(s,cid,u)
        result=s.execute(update(Conversation).where(Conversation.id==cid,Conversation.owner_id.is_(None)).values(owner_id=u.id,status='active',updated_at=now()))
        if not result.rowcount:raise HTTPException(409,'已被认领，请刷新或使用接管')
        audit(s,u.id,'claim',cid);s.commit()
    await broadcast(cid);return {'ok':True}

class Takeover(BaseModel):expected_owner:str|None=None

@app.post('/api/conversations/{cid}/takeover')
async def takeover(cid:str,body:Takeover,u=Depends(staff)):
    with Session() as s:
        allowed_conv(s,cid,u)
        result=s.execute(update(Conversation).where(Conversation.id==cid,Conversation.owner_id==body.expected_owner).values(owner_id=u.id,status='active',updated_at=now()))
        if not result.rowcount:raise HTTPException(409,'负责人已变化，请刷新后再接管')
        s.execute(update(Followup).where(Followup.conversation_id==cid,Followup.status=='pending').values(owner_id=u.id))
        audit(s,u.id,'takeover',cid);s.commit()
    await broadcast(cid);return {'ok':True}

class MessageInput(BaseModel):
    content:str=Field(default='',max_length=6000)
    client_id:str=Field(min_length=10,max_length=100)
    product_id:str=''

@app.post('/api/conversations/{cid}/messages')
async def send_message(cid:str,body:MessageInput,u=Depends(current)):
    if not body.content.strip() and not body.product_id:raise HTTPException(400,'消息不能为空')
    with Session() as s:
        c=allowed_conv(s,cid,u,True)
        duplicate=s.scalar(select(Message).where(Message.client_id==body.client_id))
        if duplicate:
            if duplicate.sender_id!=u.id or duplicate.conversation_id!=cid:raise HTTPException(409,'消息编号冲突')
            return record(duplicate)
        if c.status=='closed':raise HTTPException(409,'会话已结束，请重新打开')
        card={}
        if body.product_id:
            if u.role not in STAFF:raise HTTPException(403,'产品卡片由客服发送')
            p=knowledge.product(body.product_id)
            if not p:raise HTTPException(404,'产品不存在')
            card={'product_id':p['id'],'name':p['name'],'image_id':p['images'][0]['id'] if p['images'] else '', 'source':p['facts']['urls'][0] if p['facts']['urls'] else ''}
        # Atomic increment serializes message sequence across concurrent senders.
        s.execute(update(Conversation).where(Conversation.id==cid).values(seq=Conversation.seq+1,updated_at=now()));s.refresh(c)
        m=Message(conversation_id=cid,sender_id=u.id,role='staff' if u.role in STAFF else 'customer',content=body.content.strip(),card=js(card),client_id=body.client_id,seq=c.seq);s.add(m)
        try:s.commit()
        except IntegrityError:
            s.rollback();duplicate=s.scalar(select(Message).where(Message.client_id==body.client_id))
            if not duplicate or duplicate.sender_id!=u.id or duplicate.conversation_id!=cid:raise HTTPException(409,'消息编号冲突')
            return record(duplicate)
        result=record(m)
    await broadcast(cid)
    if u.role not in STAFF:await delayed_analysis(cid,u.id)
    return result

class ConvPatch(BaseModel):
    status:Literal['waiting','active','closed']|None=None
    stage:Literal['新咨询','需求确认','产品比较','考虑中','已成交','暂不购买']|None=None

@app.patch('/api/conversations/{cid}')
async def patch_conv(cid:str,body:ConvPatch,u=Depends(current)):
    with Session() as s:
        c=allowed_conv(s,cid,u,u.role in STAFF)
        if u.role not in STAFF and (body.stage is not None or body.status!='active'):raise HTTPException(403,'客户仅可重新打开自己的会话')
        for k,v in body.model_dump(exclude_none=True).items():setattr(c,k,v)
        if body.stage=='暂不购买':
            for f in s.scalars(select(Followup).where(Followup.conversation_id==cid,Followup.status=='pending')):f.status='cancelled';f.feedback='客户暂不购买，停止跟进'
        c.updated_at=now();s.commit()
    await broadcast(cid);return {'ok':True}

class Correction(BaseModel):
    field:Literal['user','tasks','software','budget','progress','concerns','next_step']
    value:str=Field(max_length=2000)
    locked:bool=True

@app.patch('/api/conversations/{cid}/analysis')
def correct(cid:str,body:Correction,u=Depends(staff)):
    with Session() as s:
        c=allowed_conv(s,cid,u,True);locks=json.loads(c.locked);analysis=json.loads(c.analysis)
        if body.locked:
            item={'value':body.value,'evidence':analysis.get(body.field,{}).get('evidence',[]),'manual':True};locks[body.field]=item;analysis[body.field]=item
        else:locks.pop(body.field,None)
        c.locked=js(locks);c.analysis=js(analysis);audit(s,u.id,'correct_requirement',cid);s.commit();return {'ok':True}

class TaskInput(BaseModel):product_id:str=''

@app.post('/api/conversations/{cid}/ai/{kind}')
async def conversation_ai(cid:str,kind:Literal['analysis','suggest'],body:TaskInput,u=Depends(staff)):
    with Session() as s:allowed_conv(s,cid,u)
    return {'job_id':spawn_job(kind,u.id,cid,body.model_dump())}

@app.websocket('/api/ws/{cid}')
async def socket_chat(ws:WebSocket,cid:str):
    origin=ws.headers.get('origin')
    if not origin or urlparse(origin).netloc!=ws.headers.get('host'):await ws.close(code=1008);return
    u=identify(ws.cookies.get('store_session'))
    if not u:await ws.close(code=1008);return
    try:
        with Session() as s:allowed_conv(s,cid,u)
    except HTTPException:await ws.close(code=1008);return
    await ws.accept();connections[cid].add(ws)
    try:
        while True:
            await ws.receive_text()
            latest=identify(ws.cookies.get('store_session'))
            if not latest:await ws.close(code=1008);break
            await ws.send_json({'event':'pong'})
    except WebSocketDisconnect:pass
    finally:connections[cid].discard(ws)

class Brief(BaseModel):
    product_id:str=Field(default='',max_length=100)
    audience:str=Field(default='',max_length=500)
    scene:str=Field(default='',max_length=1000)
    goal:str=Field(default='',max_length=500)
    platform:Literal['公众号','小红书','朋友圈','海报']='小红书'
    tone:str=Field(default='',max_length=300)
    emphasis:str=Field(default='',max_length=1000)
    buying_stage:str=Field(default='',max_length=100)
    user_problem:str=Field(default='',max_length=1000)

@app.post('/api/marketing/tasks')
async def generate_article(body:Brief,u=Depends(staff)):return {'job_id':spawn_job('generate',u.id,payload=body.model_dump())}

@app.get('/api/jobs')
def jobs(u=Depends(staff)):
    with Session() as s:return [record(j) for j in s.scalars(select(Job).order_by(Job.created_at.desc()).limit(60))]

@app.get('/api/jobs/{jid}')
def job(jid:str,u=Depends(staff)):
    with Session() as s:
        j=s.get(Job,jid)
        if not j:raise HTTPException(404,'任务不存在')
        return record(j)

@app.get('/api/jobs/{jid}/events')
async def events(jid:str,u=Depends(staff)):
    async def stream():
        previous=''
        while True:
            with Session() as s:
                obj=s.get(Job,jid)
                if not obj:yield 'event: error\ndata: {}\n\n';return
                data=record(obj)
            encoded=js(data)
            if encoded!=previous:yield 'data: '+encoded+'\n\n';previous=encoded
            else:yield ': keepalive\n\n'
            if data['status'] not in {'queued','running'}:return
            await asyncio.sleep(1)
    return StreamingResponse(stream(),media_type='text/event-stream',headers={'X-Accel-Buffering':'no'})

@app.post('/api/jobs/{jid}/retry')
async def retry(jid:str,u=Depends(staff)):
    with Session() as s:
        old=s.get(Job,jid)
        if not old:raise HTTPException(404,'任务不存在')
        if old.status in {'running','queued','completed'}:raise HTTPException(409,'任务不需要重试')
        if old.kind=='image':
            if old.remote_id:
                old.status='queued';old.error='';s.commit();asyncio.create_task(run_image(jid));return {'job_id':jid}
            raise HTTPException(409,'没有远端编号；请在创作页面明确重新生成背景')
        return {'job_id':spawn_job(old.kind,u.id,old.target_id,json.loads(old.payload))}

@app.post('/api/jobs/{jid}/cancel')
def cancel(jid:str,u=Depends(staff)):
    with Session() as s:
        j=s.get(Job,jid)
        if not j:raise HTTPException(404,'任务不存在')
        if j.status in {'running','queued','waiting_remote'}:
            j.status='cancelled';j.step='已停止等待；如远端已提交仍可能完成';s.commit()
        return {'ok':True}

@app.get('/api/works')
def works(u=Depends(staff)):
    with Session() as s:return [record(w) for w in s.scalars(select(Work).order_by(Work.updated_at.desc()))]

@app.get('/api/works/{wid}')
def work(wid:str,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        d=record(w);d['versions']=[record(v) for v in s.scalars(select(WorkVersion).where(WorkVersion.work_id==wid).order_by(WorkVersion.version.desc()))]
        try:d['available_images']=work_images(d['content'],d['brief'])
        except ValueError:d['available_images']=[]
        return d

class WorkEdit(BaseModel):
    expected_version:int
    title:str=Field(min_length=1,max_length=200)
    intro:str=Field(default='',max_length=1000)
    body:str=Field(min_length=1,max_length=16000)
    cta:str=Field(default='',max_length=1000)
    image_ids:list[str]=Field(default_factory=list,max_length=6)
    pending:list[str]|None=Field(default=None,max_length=30)
    tags:list[str]|None=Field(default=None,max_length=10)

@app.patch('/api/works/{wid}')
def edit_work(wid:str,body:WorkEdit,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        content=json.loads(w.content);brief=json.loads(w.brief)
        try:allowed={i['id']:i for i in work_images(content,brief)}
        except ValueError as e:raise HTTPException(409,str(e)) from None
        if any(i not in allowed for i in body.image_ids):raise HTTPException(400,'图片与产品不匹配')
        if len(set(body.image_ids))!=len(body.image_ids):raise HTTPException(400,'请勿重复选择同一图片')
        content.update(body.model_dump(exclude={'expected_version','image_ids'},exclude_none=True))
        content['images']=place_images([allowed[i] for i in body.image_ids],content['body'])
        content['strategy_current']=False
        # The previous model summary may refer to deleted text; keep only explicit input.
        content['scenario']=scenario_judgment(brief)
        old_report=json.loads(w.report)
        unresolved=[i for i in old_report.get('issues',[]) if i.get('type')=='资料冲突']
        values={'version':body.expected_version+1,'content':js(content),'report':js({'status':'unchecked','blocked':has_source_conflict(old_report),'issues':unresolved,'pending':['作品已修改，请重新核验']}),'updated_at':now()}
        result=s.execute(update(Work).where(Work.id==wid,Work.version==body.expected_version).values(**values))
        if not result.rowcount:raise HTTPException(409,'作品已更新，请刷新后再保存')
        s.add(WorkVersion(work_id=wid,version=values['version'],content=values['content'],report=values['report']));audit(s,u.id,'edit_work',wid);s.commit();return {'ok':True}

@app.post('/api/works/{wid}/verify')
async def verify_work(wid:str,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        version=w.version
    return {'job_id':spawn_job('verify',u.id,wid,{'expected_version':version})}


class WorkRevision(BaseModel):
    expected_version:int=Field(ge=1)


class WorkApproval(WorkRevision):
    note:str=Field(min_length=1,max_length=1000)

    @field_validator('note')
    @classmethod
    def meaningful_note(cls,value):
        if not value.strip():raise ValueError('请填写确认说明')
        return value.strip()


@app.post('/api/works/{wid}/repair')
async def repair_work(wid:str,body:WorkRevision,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        if w.version!=body.expected_version:raise HTTPException(409,'作品已更新，请刷新后再自动调整')
    return {'job_id':spawn_job('repair',u.id,wid,body.model_dump())}


@app.post('/api/works/{wid}/approve')
def approve_work(wid:str,body:WorkApproval,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        if w.version!=body.expected_version:raise HTTPException(409,'作品已更新，请刷新后重新确认')
        report=json.loads(w.report);content=json.loads(w.content)
        if report.get('status') not in {'needs_review','unchecked'}:raise HTTPException(409,'当前版本已通过，无需重复确认')
        if has_source_conflict(report):raise HTTPException(409,'资料存在冲突，请核对并重新检查后再确认通过')
        if has_inline_images(content):raise HTTPException(409,'请先删除正文中的图片代码，通过同型号配图列表选择图片')
        try:allowed={i['id'] for i in work_images(content,json.loads(w.brief))}
        except ValueError as e:raise HTTPException(409,str(e)) from None
        if any(i.get('id') not in allowed for i in content.get('images',[])):
            raise HTTPException(409,'配图不属于当前产品，请先更换同型号图片')
        report['approval']={'actor_id':u.id,'display_name':u.display_name,'note':body.note,
                            'approved_at':now(),'reviewed_version':w.version,'previous_status':report.get('status')}
        report['status']='manual_passed'
        values={'version':w.version+1,'report':js(report),'updated_at':now()}
        changed=s.execute(update(Work).where(Work.id==wid,Work.version==body.expected_version,Work.report==w.report).values(**values))
        if not changed.rowcount:raise HTTPException(409,'作品或检查结果已更新，请刷新后重新确认')
        s.add(WorkVersion(work_id=wid,version=values['version'],content=w.content,report=values['report']))
        audit(s,u.id,'approve_work',wid);s.commit()
        return {'ok':True,'version':values['version']}

def work_markdown(w,draft):
    c=json.loads(w.content);report=json.loads(w.report)
    return unified_markdown(c,json.loads(w.brief),report,draft)

@app.get('/api/works/{wid}/export')
def export(wid:str,format:Literal['txt','md','html','zip']='md',draft:bool=False,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        report=json.loads(w.report)
        if has_source_conflict(report):
            raise HTTPException(409,'资料存在冲突，请人工核对并重新检查，暂不能导出草稿或正式稿')
        if not draft and report.get('status') not in {'passed','manual_passed'}:raise HTTPException(409,'请先通过核验或人工确认，或选择待确认草稿导出')
        text=work_markdown(w,draft);c=json.loads(w.content)
        if has_inline_images(c):raise HTTPException(409,'正文含未受管理的图片代码，请删除并通过同型号配图列表选择图片')
    allowed_images={image_relative_url(im) for im in c.get('images',[])}
    def image_attribute(tag,name,value):return name=='alt' or (name=='src' and value in allowed_images)
    safe=bleach.clean(markdown.markdown(text),tags={'h1','h2','h3','p','ul','ol','li','strong','em','blockquote','a','img','br','hr','code','pre'},attributes={'a':['href'],'img':image_attribute},protocols=['https','http'])
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(c['title'])+'</title><style>body{max-width:860px;margin:40px auto;padding:0 20px;font-family:system-ui;line-height:1.8;overflow-wrap:anywhere}img{max-width:100%;height:auto}</style><body>'+safe+'</body></html>'
    if format=='zip':
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('article.md',text);z.writestr('article.html',page);z.writestr('sources.json',js(c.get('sources',[])));z.writestr('verification.json',w.report)
            z.writestr('scenario.json',js(scenario_judgment(json.loads(w.brief),c.get('scenario'))))
            for im in c.get('images',[]):
                fp=knowledge.image_path(im['id'])
                if fp:z.write(fp,'images/'+im['name'])
        blob=data.getvalue();media='application/zip'
    elif format=='html':
        # Standalone HTML embeds local source pictures, with no remote tracking.
        import base64,mimetypes
        for im in c.get('images',[]):
            fp=knowledge.image_path(im['id'])
            if fp:page=page.replace(image_relative_url(im),'data:'+(mimetypes.guess_type(fp)[0] or 'image/png')+';base64,'+base64.b64encode(fp.read_bytes()).decode())
        blob=page.encode();media='text/html'
    else:blob=text.encode();media='text/plain'
    return Response(blob,media_type=media,headers={'Content-Disposition':f'attachment; filename="work-{wid[:8]}-v{w.version}.{format}"'})

class ImageInput(BaseModel):
    scene:str=Field(min_length=2,max_length=800)
    ratio:Literal['1:1','3:4','16:9']='3:4'
    request_id:str=Field(min_length=10,max_length=100)

@app.post('/api/images/tasks')
async def image_task(body:ImageInput,u=Depends(staff)):
    with Session() as s:
        existing=s.scalar(select(Job).where(Job.id==body.request_id))
        if existing:
            if existing.actor_id!=u.id or existing.kind!='image':raise HTTPException(409,'任务编号冲突')
            return {'job_id':existing.id}
        j=Job(id=body.request_id,kind='image',actor_id=u.id,payload=js(body.model_dump()));s.add(j)
        try:s.commit()
        except IntegrityError:s.rollback();raise HTTPException(409,'图片请求已存在，请刷新任务列表')
    asyncio.create_task(run_image(j.id));return {'job_id':j.id}

@app.get('/api/assets')
def assets(u=Depends(staff)):
    with Session() as s:return [record(a,('path',)) for a in s.scalars(select(Asset).order_by(Asset.created_at.desc()).limit(80))]

@app.get('/api/assets/{aid}')
def asset_file(aid:str,u=Depends(staff)):
    with Session() as s:
        a=s.get(Asset,aid)
        if not a:raise HTTPException(404,'图片不存在')
        return FileResponse(private_asset(a.path))

class CompositeInput(BaseModel):
    image_id:str
    background_id:str=''
    ratio:Literal['1:1','3:4','16:9']='3:4'

@app.post('/api/works/{wid}/compose')
def composition(wid:str,body:CompositeInput,u=Depends(staff)):
    try:return compose(wid,u.id,body.image_id,body.background_id,body.ratio)
    except ValueError as e:raise HTTPException(400,str(e))

class FollowupInput(BaseModel):
    conversation_id:str
    days:list[int]=Field(default_factory=lambda:[1,3,7],max_length=3)

@app.post('/api/followups/plan')
def followup_plan(body:FollowupInput,u=Depends(staff)):
    if any(d not in {1,3,7} for d in body.days):raise HTTPException(400,'支持1/3/7天计划')
    with Session() as s:
        c=allowed_conv(s,body.conversation_id,u,True)
        if c.stage in {'暂不购买','已成交'}:raise HTTPException(409,'当前阶段不再新增营销跟进')
        existing=list(s.scalars(select(Followup).where(Followup.conversation_id==c.id,Followup.status=='pending')))
        if existing:raise HTTPException(409,'已有待办跟进，请先处理或调整')
        goals={1:'补齐需求与顾虑',3:'比较候选与体验反馈',7:'确认决策与后续安排'}
        scripts={1:'您好，上次聊到的使用需求还有哪些需要补充？我可以继续帮您核对。',3:'您好，前几天的候选方案看过了吗？如果有具体软件或使用问题，我们可以逐项核对。',7:'您好，想了解一下您的购机安排是否有变化。如暂时不需要，我会停止后续跟进。'}
        for d in dict.fromkeys(body.days):s.add(Followup(conversation_id=c.id,owner_id=u.id,due_at=(datetime.now(timezone.utc)+timedelta(days=d)).isoformat(),purpose=goals[d],script=scripts[d]))
        audit(s,u.id,'followup_plan',c.id);s.commit();return {'ok':True}

@app.get('/api/followups')
def followups(u=Depends(staff)):
    with Session() as s:
        names={c.id:c.customer_name for c in s.scalars(select(Conversation))}
        return [{**record(f),'customer_name':names.get(f.conversation_id,'客户')} for f in s.scalars(select(Followup).order_by(Followup.due_at))]

class FollowupEdit(BaseModel):
    due_at:datetime|None=None
    purpose:str|None=Field(default=None,max_length=300)
    script:str|None=Field(default=None,max_length=3000)
    status:Literal['pending','completed','cancelled']|None=None
    feedback:str|None=Field(default=None,max_length=3000)

@app.patch('/api/followups/{fid}')
def edit_followup(fid:str,body:FollowupEdit,u=Depends(staff)):
    with Session() as s:
        f=s.get(Followup,fid)
        if not f:raise HTTPException(404,'事项不存在')
        if f.owner_id!=u.id and u.role!='admin':raise HTTPException(403,'只能修改本人负责的跟进')
        c=s.get(Conversation,f.conversation_id)
        if body.status=='pending' and c and c.stage in {'暂不购买','已成交'}:raise HTTPException(409,'当前客户阶段不能恢复营销跟进')
        for k,v in body.model_dump(exclude_none=True).items():
            if k=='due_at':
                if v.tzinfo is None:raise HTTPException(400,'跟进时间必须带时区')
                v=v.astimezone(timezone.utc).isoformat()
            setattr(f,k,v)
        s.commit();return {'ok':True}

@app.get('/api/dashboard')
def dashboard(u=Depends(staff)):
    with Session() as s:
        alljobs=list(s.scalars(select(Job)));finished=[j for j in alljobs if j.status=='completed']
        return {'waiting':s.scalar(select(func.count()).select_from(Conversation).where(Conversation.status=='waiting')),'conversations':s.scalar(select(func.count()).select_from(Conversation)),'works':s.scalar(select(func.count()).select_from(Work)),'pending_followups':s.scalar(select(func.count()).select_from(Followup).where(Followup.status=='pending')),'completed_jobs':len(finished),'failed_jobs':sum(j.status=='failed' for j in alljobs),'token_usage':sum(json.loads(j.result).get('usage',{}).get('total_tokens',0) for j in finished),'knowledge':knowledge.status()}

class StaffInput(Credentials):role:Literal['staff','admin']='staff'

@app.get('/api/admin/users')
def users(u=Depends(admin)):
    with Session() as s:return [{**public_user(x),'active':x.active} for x in s.scalars(select(User).where(User.role.in_(STAFF)))]

@app.post('/api/admin/users')
def add_staff(body:StaffInput,u=Depends(admin)):
    with Session() as s:
        if s.scalar(select(User).where(User.username==body.username)):raise HTTPException(409,'账号已存在')
        user=User(username=body.username,display_name=body.display_name or body.username,password=ph.hash(body.password),role=body.role);s.add(user);audit(s,u.id,'create_staff');s.commit();return public_user(user)

class UserEdit(BaseModel):active:bool;role:Literal['staff','admin']

@app.patch('/api/admin/users/{user_id}')
def edit_staff(user_id:str,body:UserEdit,u=Depends(admin)):
    if user_id==u.id:raise HTTPException(400,'不能停用或降级当前管理员')
    with Session() as s:
        user=s.get(User,user_id)
        if not user or user.role not in STAFF:raise HTTPException(404,'员工不存在')
        user.active=body.active;user.role=body.role;audit(s,u.id,'edit_staff',user_id);s.commit();return {'ok':True}

class StoreSettings(BaseModel):
    name:str=Field(min_length=1,max_length=60)
    hours:str=Field(default='09:00—21:00',max_length=60)
    welcome:str=Field(default='你好，欢迎咨询华为PC选购。',max_length=300)

@app.get('/api/store')
def store():
    with Session() as s:
        row=s.get(Setting,'store');return json.loads(row.value) if row else {'name':'知客 · 华为PC体验门店','hours':'09:00—21:00','welcome':'把需求告诉我们，让每一次选择都有依据。'}

@app.put('/api/admin/store')
def update_store(body:StoreSettings,u=Depends(admin)):
    with Session() as s:
        row=s.get(Setting,'store')
        if row:row.value=js(body.model_dump())
        else:s.add(Setting(key='store',value=js(body.model_dump())))
        audit(s,u.id,'update_store');s.commit();return {'ok':True}

@app.get('/api/admin/status')
def status(u=Depends(admin)):
    with Session() as s:
        image_job=s.scalar(select(Job).where(Job.kind=='image').order_by(Job.created_at.desc()).limit(1))
        image_error=image_job.error if image_job else ''
    return {'text':model_settings.get_config().public(),'image':{'configured':bool(IMAGE_KEY),'model':IMAGE_MODEL,'account':'NothingK','account_verified':False,'last_error':image_error},'knowledge':knowledge.status(),'marketing_knowledge':{'provider':MARKETING_SOURCE,**connection_status()},'backups':[p.name for p in sorted((DATA/'backups').glob('*.db'))]}

@app.get('/api/admin/text-model')
def text_model(u=Depends(admin)):
    return JSONResponse(model_settings.get_config().public(),headers={'Cache-Control':'no-store'})

@app.put('/api/admin/text-model')
async def save_text_model(request:Request,u=Depends(admin)):
    try:
        if len(await request.body())>16000:raise ValueError('模型配置内容过长')
        body=await request.json()
        result=await asyncio.to_thread(model_settings.save_config,body)
    except ValueError as e:
        # Never return a validation body, provider response or credential.
        detail=str(e) if not isinstance(e,json.JSONDecodeError) else '模型配置格式无效'
        raise HTTPException(400,detail) from None
    except OSError:
        raise HTTPException(500,'私有配置保存失败，请检查持久目录权限') from None
    with Session() as s:audit(s,u.id,'update_text_model');s.commit()
    return JSONResponse(result,headers={'Cache-Control':'no-store'})

@app.delete('/api/admin/text-model')
@app.post('/api/admin/text-model/reset')
def reset_text_model(u=Depends(admin)):
    result=model_settings.reset_config()
    with Session() as s:audit(s,u.id,'reset_text_model');s.commit()
    return JSONResponse(result,headers={'Cache-Control':'no-store'})

@app.post('/api/admin/check-model')
async def check_model(u=Depends(admin)):
    return await model_settings.check_config()

@app.post('/api/admin/backup')
def do_backup(u=Depends(admin)):
    name=Path(backup()).name
    with Session() as s:audit(s,u.id,'backup',name);s.commit()
    return {'filename':name}

@app.post('/api/admin/backup/drill')
def backup_drill(u=Depends(admin)):
    result=restore_drill(Path(backup()))
    with Session() as s:audit(s,u.id,'restore_drill',result['backup']);s.commit()
    return result

@app.get('/api/admin/audit')
def audits(u=Depends(admin)):
    with Session() as s:return [record(a) for a in s.scalars(select(Audit).order_by(Audit.created_at.desc()).limit(100))]

@app.post('/api/admin/knowledge/reindex')
async def reindex(u=Depends(admin)):
    archives=list((DATA/'knowledge'/'archive').glob('*.zip'))
    if not archives:raise HTTPException(400,'请先用导入命令保存知识包')
    with Session() as s:
        if s.scalar(select(Job).where(Job.kind=='import',Job.status.in_(['running','queued']))):raise HTTPException(409,'导入任务正在执行')
        j=Job(kind='import',actor_id=u.id);s.add(j);s.commit();jid=j.id
    async def run():
        job_update(jid,status='running',step='正在校验并重建索引')
        try:
            result=await asyncio.to_thread(import_zip,archives[-1]);job_update(jid,status='completed',step='知识库已更新',result=js(result))
        except Exception as e:job_update(jid,status='failed',step='导入失败，保留原版本',error=clean_error(e))
    asyncio.create_task(run());return {'job_id':jid}

dist=ROOT/'frontend'/'dist'
if dist.exists():
    app.mount('/assets',StaticFiles(directory=dist/'assets'),name='static')
    @app.get('/{path:path}')
    def frontend(path:str):
        if path.startswith('api/'):raise HTTPException(404,'接口不存在')
        return FileResponse(dist/'index.html')
