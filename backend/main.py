import asyncio
import hashlib
import html
import io
import json
import os
import re
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
from argon2.exceptions import VerificationError,InvalidHashError
from fastapi import FastAPI,Depends,HTTPException,Request,Response,WebSocket,WebSocketDisconnect,Query
from fastapi.responses import FileResponse,StreamingResponse,JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,update,func
from sqlalchemy.exc import IntegrityError
from .config import ROOT,DATA,IMAGE_KEY,IMAGE_MODEL
from . import model_settings,image_settings
from .db import *
from .knowledge import knowledge,import_zip,work_images
from .ima import connection_status
from .config import MARKETING_SOURCE
from .ai import spawn_job,delayed_analysis,job_update
from .requirements import build_requirements,SCHEMA_VERSION
from .marketing import place_images, unified_markdown, article_with_images, scenario_judgment, image_relative_url, has_source_conflict, has_inline_images
from .images import run_image,compose,private_asset
from .ai_poster import prepare_poster,run_poster
from .cli import backup,restore_drill
from .rich_text import validate_rich_text,check_sources,render_document
from .moments_gallery import prepare_gallery,run_moments_gallery,can_resume,latest_gallery,public_gallery,gallery_zip,gallery_paths
from .moments_gallery import publication_gallery as retained_publication_gallery
from .work_media import MAX_UPLOAD_BYTES,editable_images,uploaded_images,save_upload,image_path as work_image_path,image_url as work_image_url
from .chat_materials import chat_sources,chat_messages,material_snapshot,UnboundChat
from .marketing_brief import prepare_chat_brief
from .admin_assignment import AssignmentInput,overview as assignment_overview,assign as assign_conversations

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
        upload=request.method=='POST' and re.fullmatch(r'/api/works/[^/]+/images',request.url.path)
        limit=MAX_UPLOAD_BYTES if upload else 250000
        try:length=int(request.headers.get('content-length','0') or '0')
        except ValueError:return JSONResponse({'detail':'无效的请求长度'},400)
        if length>limit:return JSONResponse({'detail':'图片不能超过10MB' if upload else '请求过大'},413)
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

def login_for_portal(body:Credentials,request:Request,response:Response,portal=None):
    auth_rate(request);old=identify(request.cookies.get('store_session'))
    with Session() as s:
        u=s.scalar(select(User).where(User.username==body.username,User.active==True))
        try:valid=u and u.role in STAFF|{'customer'} and ph.verify(u.password,body.password)
        except (VerificationError,InvalidHashError):valid=False
        if not valid:raise HTTPException(401,'账号或密码不正确')
        if portal=='staff' and u.role not in STAFF:raise HTTPException(403,'该账号为客户账号，请使用客户登录入口')
        if portal=='customer' and u.role!='customer':raise HTTPException(403,'该账号为员工账号，请使用员工登录入口')
        if old and old.role=='guest' and u.role=='customer':s.execute(update(Conversation).where(Conversation.customer_id==old.id).values(customer_id=u.id,customer_name=u.display_name))
        set_session(s,u,response,request);audit(s,u.id,'login');s.commit();return public_user(u)

@app.post('/api/auth/login')
def login(body:Credentials,request:Request,response:Response):
    return login_for_portal(body,request,response)

@app.post('/api/auth/customer/login')
def customer_login(body:Credentials,request:Request,response:Response):
    return login_for_portal(body,request,response,'customer')

@app.post('/api/auth/staff/login')
def staff_login(body:Credentials,request:Request,response:Response):
    return login_for_portal(body,request,response,'staff')

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
        else:query=query.where(Conversation.id.not_in(select(ConversationDismissal.conversation_id).where(ConversationDismissal.user_id==u.id)))
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
            from .dialogue import view,profile_projection,VERSION
            from .service_workflow import WORKFLOW_VERSION
            state=view(cid)
            raw=d['analysis'];latest_customer=max((m['seq'] for m in d['messages'] if m['role']=='customer'),default=0)
            pricing=s.scalar(select(Job).where(Job.kind=='pricing',Job.target_id==cid,Job.status=='completed').order_by(Job.created_at.desc()).limit(1))
            d['pricing_plan']=json.loads(pricing.result).get('pricing_plan') if pricing else None
            d['dialogue']=state
            d['requires_analysis']=bool(latest_customer and (not state or state.get('version',0)<VERSION or not state.get('continuation') or state.get('workflow_version',0)<WORKFLOW_VERSION))
            d['requirements_current']=not d['requires_analysis'] and c.analysis_seq>=latest_customer
            latest_job=s.scalar(select(Job).where(Job.target_id==cid,Job.kind.in_(['analysis','suggest'])).order_by(Job.created_at.desc()).limit(1))
            latest_customer_at=max((m['created_at'] for m in d['messages'] if m['role']=='customer'),default='')
            relevant_job=latest_job and latest_job.created_at>=latest_customer_at
            d['analysis_status']=latest_job.status if relevant_job else 'current' if d['requirements_current'] else 'pending'
            d['analysis_error']=latest_job.error if relevant_job and latest_job.status=='failed' else ''
            d['analysis']=profile_projection(state) if state else build_requirements(raw,d['messages'],d['locked'],'已结束' if c.status=='closed' else c.stage)
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
        s.execute(update(Followup).where(Followup.conversation_id==cid,Followup.status=='pending').values(owner_id=u.id))
        dismissal=s.get(ConversationDismissal,(u.id,cid))
        if dismissal:s.delete(dismissal)
        audit(s,u.id,'claim',cid);s.commit()
    await broadcast(cid);return {'ok':True}

class Takeover(BaseModel):expected_owner:str|None=None

class AbandonInput(BaseModel):
    expected_owner:str|None=Field(max_length=64)

@app.post('/api/conversations/{cid}/abandon')
async def abandon_conversation(cid:str,body:AbandonInput,u=Depends(staff)):
    with Session() as s:
        c=allowed_conv(s,cid,u)
        if c.owner_id is not None or c.status!='waiting':
            raise HTTPException(409,'已接待的会话不能放弃，请使用结束接待')
        # Keep the waiting/owner check atomic with dismissal so stale pages cannot hide a claimed conversation.
        result=s.execute(update(Conversation).where(Conversation.id==cid,Conversation.owner_id.is_(None),Conversation.status=='waiting',Conversation.owner_id==body.expected_owner).values(owner_id=None))
        if not result.rowcount:raise HTTPException(409,'会话状态或负责人已变化，请刷新后再操作')
        if not s.get(ConversationDismissal,(u.id,cid)):
            s.add(ConversationDismissal(user_id=u.id,conversation_id=cid))
        audit(s,u.id,'abandon',cid);s.commit()
    await broadcast(cid);return {'ok':True}

@app.post('/api/conversations/{cid}/takeover')
async def takeover(cid:str,body:Takeover,u=Depends(staff)):
    with Session() as s:
        allowed_conv(s,cid,u)
        result=s.execute(update(Conversation).where(Conversation.id==cid,Conversation.owner_id==body.expected_owner).values(owner_id=u.id,status='active',updated_at=now()))
        if not result.rowcount:raise HTTPException(409,'负责人已变化，请刷新后再接管')
        s.execute(update(Followup).where(Followup.conversation_id==cid,Followup.status=='pending').values(owner_id=u.id))
        dismissal=s.get(ConversationDismissal,(u.id,cid))
        if dismissal:s.delete(dismissal)
        audit(s,u.id,'takeover',cid);s.commit()
    await broadcast(cid);return {'ok':True}

class MessageInput(BaseModel):
    content:str=Field(default='',max_length=6000)
    client_id:str=Field(min_length=10,max_length=100)
    product_id:str=''
    action_id:str=Field(default='',max_length=64)

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
        if u.role in STAFF and body.action_id and not body.product_id:
            from .dialogue import check_send_action
            try:card=check_send_action(s,c,body.action_id,body.content)
            except ValueError as error:raise HTTPException(409,str(error)) from None
        if body.product_id:
            if u.role not in STAFF:raise HTTPException(403,'产品卡片由客服发送')
            p=knowledge.product(body.product_id)
            if not p:raise HTTPException(404,'产品不存在')
            card={'product_id':p['id'],'name':p['name'],'image_id':p['images'][0]['id'] if p['images'] else '', 'source':p['facts']['urls'][0] if p['facts']['urls'] else ''}
        # Atomic increment serializes message sequence across concurrent senders.
        s.execute(update(Conversation).where(Conversation.id==cid).values(seq=Conversation.seq+1,updated_at=now()));s.refresh(c)
        m=Message(conversation_id=cid,sender_id=u.id,role='staff' if u.role in STAFF else 'customer',content=body.content.strip(),card=js(card),client_id=body.client_id,seq=c.seq);s.add(m)
        try:
            s.flush()
            if u.role in STAFF:
                from .dialogue import observe_sent
                observe_sent(s,c,m,body.action_id if not body.product_id else '')
            s.commit()
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
        from .dialogue import status_change
        status_change(s,c)
        if body.stage in {'暂不购买','已成交'}:
            for f in s.scalars(select(Followup).where(Followup.conversation_id==cid,Followup.status=='pending')):
                f.status='cancelled';f.feedback='客户'+body.stage+'，停止营销跟进'
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
        c.locked=js(locks);c.analysis=js(analysis)
        from .dialogue import manual_change
        manual_change(s,c)
        audit(s,u.id,'correct_requirement',cid);s.commit();return {'ok':True}

class TaskInput(BaseModel):product_id:str=''

class PriceRuleInput(BaseModel):
    product_id:str=Field(min_length=1,max_length=100)
    variant_id:str=Field(min_length=1,max_length=100)
    payload:dict

@app.get('/api/admin/price-rules')
def price_rules(u=Depends(admin)):
    with Session() as s:return [record(row) for row in s.scalars(select(PriceRule).order_by(PriceRule.created_at.desc()))]

@app.get('/api/admin/price-options')
async def price_options(u=Depends(admin)):
    from .dialogue_catalog import load_options
    options={o['id']:o for o in (await load_options())['options']}
    with Session() as s:
        for row in s.scalars(select(DialogueState)):
            for option in json.loads(row.state).get('options',[]):options[option['id']]=option
    return list(options.values())

@app.post('/api/admin/price-rules')
def add_price_rule(body:PriceRuleInput,u=Depends(admin)):
    from .quoting import calculate
    try:
        if body.payload.get('level','L1') not in {'L1','L2','L3','L4'}:raise ValueError('报价类型无效')
        # Validate the formula independently of a particular customer's eligibility.
        qualifications=set(body.payload.get('qualifications_required',[]))|{d['qualification'] for d in body.payload.get('discounts',[]) if d.get('qualification')}
        calculate(body.payload,1,qualifications)
    except (ValueError,KeyError,TypeError) as error:raise HTTPException(400,'规则不完整或计算口径无效：'+str(error)) from None
    with Session() as s:
        row=PriceRule(product_id=body.product_id,variant_id=body.variant_id,payload=js(body.payload),author_id=u.id)
        s.add(row);audit(s,u.id,'create_price_rule',body.variant_id);s.commit();return record(row)

@app.post('/api/admin/price-rules/{rid}/approve')
def approve_price_rule(rid:str,u=Depends(admin)):
    from .quoting import calculate
    with Session() as s:
        row=s.get(PriceRule,rid)
        if not row:raise HTTPException(404,'规则不存在')
        if row.author_id==u.id:raise HTTPException(409,'请由另一位管理员复核该规则')
        try:
            payload=json.loads(row.payload)
            quals=set(payload.get('qualifications_required',[]))|{d['qualification'] for d in payload.get('discounts',[]) if d.get('qualification')}
            calculate(payload,1,quals)
        except (ValueError,TypeError,KeyError):raise HTTPException(400,'规则已失效或缺少计算依据') from None
        row.approved_by=u.id;row.status='approved';audit(s,u.id,'approve_price_rule',rid);s.commit();return record(row)

@app.post('/api/admin/price-rules/{rid}/revoke')
def revoke_price_rule(rid:str,u=Depends(admin)):
    with Session() as s:
        row=s.get(PriceRule,rid)
        if not row:raise HTTPException(404,'规则不存在')
        row.status='revoked';audit(s,u.id,'revoke_price_rule',rid);s.commit();return {'ok':True}

class QualificationInput(BaseModel):
    qualification:str=Field(min_length=1,max_length=100)
    evidence_ref:str=Field(min_length=1,max_length=500)
    valid_until:datetime

@app.post('/api/conversations/{cid}/qualifications')
def verify_qualification(cid:str,body:QualificationInput,u=Depends(admin)):
    if body.valid_until.tzinfo is None or body.valid_until<=datetime.now(timezone.utc):raise HTTPException(400,'请填写带时区且未过期的有效期')
    with Session() as s:
        c=allowed_conv(s,cid,u)
        q=QuoteQualification(customer_id=c.customer_id,qualification=body.qualification,evidence_ref=body.evidence_ref,valid_until=body.valid_until.isoformat(),reviewed_by=u.id)
        s.add(q);audit(s,u.id,'verify_quote_qualification',cid);s.commit();return {'id':q.id}

class VerificationRecord(BaseModel):
    kind:Literal['compatibility','price','other']
    conclusion:Literal['supported','unsupported','conditional','confirmed','unconfirmed']
    summary:str=Field(min_length=1,max_length=500)
    conditions:str=Field(default='',max_length=500)
    source:str=Field(default='',max_length=500)
    configuration:str=Field(default='',max_length=200)
    price_text:str=Field(default='',max_length=100)
    valid_until:datetime|None=None

    @field_validator('summary','conditions','source','configuration','price_text',mode='before')
    @classmethod
    def trim_text(cls,value):return value.strip() if isinstance(value,str) else value

class ServiceTaskInput(BaseModel):
    revision:int=Field(ge=0)
    status:Literal['completed','cancelled','in_progress','waiting_staff']
    result:str=Field(default='',max_length=1000)
    due_at:datetime|None=None
    verification:VerificationRecord|None=None

@app.post('/api/conversations/{cid}/service-tasks/{tid}')
async def resolve_service_task(cid:str,tid:str,body:ServiceTaskInput,u=Depends(staff)):
    from .db import DialogueState
    from .service_tasks import refresh_tasks
    with Session() as s:
        c=allowed_conv(s,cid,u)
        if c.owner_id!=u.id:raise HTTPException(403,'请由当前接待客服处理')
        if c.status=='closed':raise HTTPException(409,'接待已结束')
        row=s.get(DialogueState,cid)
        if not row or row.revision!=body.revision:raise HTTPException(409,'任务已变化，请刷新后处理')
        state=json.loads(row.state);task=next((t for t in state.get('tasks',[]) if t['id']==tid),None)
        if not task:raise HTTPException(404,'任务不存在')
        if task['status'] in {'completed','cancelled'}:raise HTTPException(409,'该事项已处理')
        if body.status!='cancelled' and (task['kind']!='verify' or task['status']=='blocked'):raise HTTPException(400,'此任务由对话或报价流程完成')
        result_text=body.result.strip()
        if body.verification:
            v=body.verification
            if v.conclusion=='unconfirmed':
                if body.status!='waiting_staff' or not body.due_at:raise HTTPException(400,'暂未确认请保留待核实，并设置下次处理时间')
            elif body.status!='completed':raise HTTPException(400,'明确核实结论请登记为完成')
            elif not v.source or v.conclusion=='conditional' and not v.conditions:
                raise HTTPException(400,'请填写核实依据，以及有条件适用的限制')
            if v.kind=='price' and v.conclusion!='unconfirmed' and (not v.configuration or not v.price_text or not v.valid_until):
                raise HTTPException(400,'价格核实请填写具体配置、价格和有效期；正式报价仍须核价规则')
            if v.valid_until and (v.valid_until.tzinfo is None or v.valid_until<=datetime.now(timezone.utc)):
                raise HTTPException(400,'价格有效期须带时区且晚于当前时间')
            verdict={'supported':'可用','unsupported':'不适用','conditional':'有条件可用','confirmed':'已确认','unconfirmed':'暂未确认'}[v.conclusion]
            result_text='结论：'+verdict+'。'+v.summary
            for label,value in [('适用条件与限制',v.conditions),('核实依据',v.source),('具体配置',v.configuration),('核实价格（非正式报价）',v.price_text),('价格有效期',v.valid_until.isoformat() if v.valid_until else '')]:
                if value:result_text+='\n'+label+'：'+value
        if body.status in {'completed','cancelled'} and not result_text:raise HTTPException(400,'请填写处理结果')
        if body.due_at:
            if body.due_at.tzinfo is None or body.due_at<=datetime.now(timezone.utc):raise HTTPException(400,'截止时间须带时区且晚于当前时间')
            task['due_at']=body.due_at.astimezone(timezone.utc).isoformat()
        task.update(status=body.status,owner='staff',assigned_to=u.id)
        if body.status=='in_progress':task.update(started_by=u.id,started_at=task.get('started_at') or now())
        if body.verification:
            record=body.verification.model_dump(mode='json',exclude_unset=True)
            if body.status=='completed':task['verification']=record
            else:
                task['last_attempt']=record
                task['attempts']=[*task.get('attempts',[]),{**record,'actor_id':u.id,'recorded_at':now()}][-10:]
        if body.status in {'completed','cancelled'}:task.update(result=result_text,completed_by=u.id,completed_at=now())
        if body.status=='completed':task['feedback_status']='pending'
        refresh_tasks(state)
        if body.status in {'completed','cancelled'}:
            state.setdefault('pending_service_events',[]).append({'id':secrets.token_hex(16),
                'kind':'verification_completed' if body.status=='completed' else 'task_cancelled',
                'task_id':tid,'actor_id':u.id,'created_at':now()})
        state['next_owner']='staff'
        state['revision']=row.revision+1
        if body.status in {'completed','cancelled'}:
            state['action']={'kind':'review','reply':'','status':'needs_review'}
        elif state.get('action'):
            state['action']['revision']=row.revision+1
        updated=s.execute(update(DialogueState).where(DialogueState.conversation_id==cid,DialogueState.revision==body.revision)
            .values(revision=body.revision+1,state=json.dumps(state,ensure_ascii=False),updated_at=now()))
        if not updated.rowcount:raise HTTPException(409,'任务已变化，请刷新后处理')
        audit(s,u.id,'resolve_service_task',cid);s.commit()
    await broadcast(cid)
    job_id=spawn_job('analysis',u.id,cid) if body.status in {'completed','cancelled'} else None
    return {'ok':True,'job_id':job_id}

@app.post('/api/conversations/{cid}/ai/{kind}')
async def conversation_ai(cid:str,kind:Literal['analysis','suggest','pricing'],body:TaskInput,u=Depends(staff)):
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
    workflow:Literal['platform-v1','legacy']='platform-v1'
    product_id:str=Field(default='',max_length=100)
    audience:str=Field(default='',max_length=500)
    scene:str=Field(default='',max_length=1000)
    goal:str=Field(default='',max_length=500)
    platform:Literal['公众号','小红书','朋友圈','海报']='小红书'
    tone:str=Field(default='',max_length=300)
    emphasis:str=Field(default='',max_length=1000)
    buying_stage:str=Field(default='',max_length=100)
    user_problem:str=Field(default='',max_length=1000)
    moments_image_count:Literal[0,1,3,6,9]=0
    moments_image_mode:Literal['original','mixed','ai']='mixed'
    chat_message_ids:list[str]=Field(default_factory=list,max_length=20)

    @field_validator('chat_message_ids')
    @classmethod
    def valid_message_ids(cls,value):
        if len(set(value))!=len(value) or any(not item or len(item)>100 for item in value):
            raise ValueError('请选择不同且有效的聊天消息')
        return value

@app.get('/api/marketing/chat-sources')
def marketing_chat_sources(u=Depends(staff)):
    with Session() as session:return chat_sources(session,u.id)

@app.get('/api/marketing/chat-sources/{cid}')
def marketing_chat_messages(cid:str,before:int|None=Query(default=None,ge=1),limit:int=Query(default=100,ge=1,le=100),u=Depends(staff)):
    with Session() as session:
        try:return chat_messages(session,u.id,cid,before,limit)
        except UnboundChat as error:raise HTTPException(403,str(error)) from None

@app.post('/api/marketing/tasks')
async def generate_article(body:Brief,u=Depends(staff)):
    payload=body.model_dump()
    if body.chat_message_ids:
        with Session() as session:
            try:payload['chat_materials']=material_snapshot(session,u.id,body.chat_message_ids)
            except UnboundChat as error:raise HTTPException(403,str(error)) from None
    return {'job_id':spawn_job('generate',u.id,payload=payload)}

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
        if old.kind=='moments_gallery':
            try:can_resume(json.loads(old.payload))
            except ValueError as error:raise HTTPException(409,str(error)) from None
            old.status='queued';old.error='';s.commit();asyncio.create_task(run_moments_gallery(jid));return {'job_id':jid}
        if old.kind in {'image','poster'}:
            if old.remote_id:
                old.status='queued';old.error='';s.commit();asyncio.create_task(run_poster(jid) if old.kind=='poster' else run_image(jid));return {'job_id':jid}
            raise HTTPException(409,'没有远端编号；请先核查图片服务任务记录，再在创作页面明确重新生成')
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
    with Session() as s:
        result=[]
        for w in s.scalars(select(Work).order_by(Work.updated_at.desc())):
            item=record(w);cover=None
            if item['brief'].get('platform')=='朋友圈':
                try:
                    album=retained_publication_gallery(s,w)
                    if album and album['items'] and gallery_paths(s,w,album):
                        first=album['items'][0];cover={'url':first['url'],'caption':first.get('title','朋友圈配图')}
                except ValueError:pass
            if not cover:
                for image in item['content'].get('images',[]):
                    try:path=work_image_path(image['id'],w.id)
                    except ValueError:continue
                    if path and path.is_file():
                        cover={'url':work_image_url(image),'caption':image.get('caption') or image.get('description','作品配图')};break
            item['cover_image']=cover;result.append(item)
        return result

@app.get('/api/works/{wid}')
def work(wid:str,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        d=record(w);d['versions']=[record(v) for v in s.scalars(select(WorkVersion).where(WorkVersion.work_id==wid).order_by(WorkVersion.version.desc()))]
        try:d['available_images']=editable_images(s,w)
        except ValueError:d['available_images']=uploaded_images(s,wid)
        return d

@app.get('/api/conversations/{cid}/marketing-brief')
def conversation_marketing_brief(cid:str,product_id:str=Query(default='',max_length=100),u=Depends(staff)):
    with Session() as session:
        try:return prepare_chat_brief(session,cid,u.id,product_id)
        except UnboundChat as error:raise HTTPException(403,str(error)) from None
        except ValueError as error:raise HTTPException(400,str(error)) from None

@app.post('/api/works/{wid}/images')
async def upload_work_image(wid:str,request:Request,filename:str='本地配图',u=Depends(staff)):
    with Session() as s:
        if not s.get(Work,wid):raise HTTPException(404,'作品不存在')
    chunks=[];size=0
    async for chunk in request.stream():
        size+=len(chunk)
        if size>MAX_UPLOAD_BYTES:raise HTTPException(413,'图片不能超过10MB')
        chunks.append(chunk)
    if not size:raise HTTPException(400,'请选择图片文件')
    def store():
        with Session() as s:
            w=s.get(Work,wid)
            if not w:raise HTTPException(404,'作品不存在')
            try:return save_upload(s,w,u.id,b''.join(chunks),filename)
            except ValueError as error:raise HTTPException(400,str(error)) from None
    return await asyncio.to_thread(store)

class WorkEdit(BaseModel):
    expected_version:int
    title:str=Field(min_length=1,max_length=200)
    intro:str=Field(default='',max_length=1000)
    body:str=Field(min_length=1,max_length=16000)
    cta:str=Field(default='',max_length=1000)
    image_ids:list[str]=Field(default_factory=list,max_length=6)
    image_positions:dict[str,int]|None=Field(default=None,max_length=6)
    rich_text:dict|None=None
    pending:list[str]|None=Field(default=None,max_length=30)
    tags:list[str]|None=Field(default=None,max_length=10)

    @field_validator('rich_text')
    @classmethod
    def valid_rich_text(cls,value):return validate_rich_text(value)

    @field_validator('image_positions')
    @classmethod
    def valid_image_positions(cls,value):
        if value is not None and any(position<0 for position in value.values()):raise ValueError('图片位置不能为负数')
        return value

@app.patch('/api/works/{wid}')
def edit_work(wid:str,body:WorkEdit,u=Depends(staff)):
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        content=json.loads(w.content);brief=json.loads(w.brief)
        try:allowed={i['id']:i for i in editable_images(s,w)}
        except ValueError as e:raise HTTPException(409,str(e)) from None
        if any(i not in allowed for i in body.image_ids):raise HTTPException(400,'图片与产品不匹配')
        if len(set(body.image_ids))!=len(body.image_ids):raise HTTPException(400,'请勿重复选择同一图片')
        if body.image_positions is not None and set(body.image_positions)!=set(body.image_ids):raise HTTPException(400,'图片位置必须与所选图片一致')
        content.update(body.model_dump(exclude={'expected_version','image_ids','image_positions'},exclude_none=True))
        try:check_sources(body.rich_text,content,body.image_ids)
        except ValueError as error:raise HTTPException(422,str(error)) from None
        content['images']=place_images([allowed[i] for i in body.image_ids],content['body'])
        if body.image_positions is not None:
            block_count=len([part for part in content['body'].strip().split('\n\n') if part.strip()])
            for image in content['images']:
                image['after_block']=min(body.image_positions[image['id']],block_count)
                image['position']=f'正文第{image["after_block"]}块后' if image['after_block'] else '导语后'
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
        try:allowed={i['id'] for i in editable_images(s,w)}
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
def export(wid:str,format:Literal['txt','md','html','zip']='md',draft:bool=False,scope:Literal['record','publication']='record',u=Depends(staff)):
    publication_gallery=None;publication_gallery_files=[]
    with Session() as s:
        w=s.get(Work,wid)
        if not w:raise HTTPException(404,'作品不存在')
        report=json.loads(w.report)
        if has_source_conflict(report):
            raise HTTPException(409,'资料存在冲突，请人工核对并重新检查，暂不能导出草稿或正式稿')
        if not draft and report.get('status') not in {'passed','manual_passed'}:raise HTTPException(409,'请先通过核验或人工确认，或选择待确认草稿导出')
        text=work_markdown(w,draft);c=json.loads(w.content)
        if has_inline_images(c):raise HTTPException(409,'正文含未受管理的图片代码，请删除并通过同型号配图列表选择图片')
        if scope=='publication' and json.loads(w.brief).get('platform')=='朋友圈':
            publication_gallery=retained_publication_gallery(s,w)
            if publication_gallery:
                try:paths=gallery_paths(s,w,publication_gallery)
                except ValueError as error:raise HTTPException(409,str(error)) from None
                publication_gallery_files=[(f'images/moments-{index:02d}'+path.suffix.lower(),path) for index,path in enumerate(paths,1)]
                publication_gallery={**publication_gallery,'items':[{**item,'url':name} for item,(name,path) in zip(publication_gallery['items'],publication_gallery_files)]}
    if scope=='publication':
        from .platform_content import publication_text
        from .publication import render_publication
        text=publication_text(c,json.loads(w.brief)['platform'])
    allowed_images={image_relative_url(im) for im in c.get('images',[])}
    def image_attribute(tag,name,value):return name=='alt' or (name=='src' and value in allowed_images)
    styled={};display=dict(c);rich_body=False
    for field,item in c.get('rich_text',{}).items():
        if item.get('source')!=c.get(field):continue
        try:
            validate_rich_text({field:item});check_sources({field:item},c,[image['id'] for image in c.get('images',[])])
        except (ValueError,TypeError,KeyError):continue
        marker='EDITORRICH'+secrets.token_hex(12)
        image_map={image['id']:{'url':image_relative_url(image),'caption':image.get('caption') or image.get('description','')} for image in c.get('images',[])}
        styled[marker]=render_document(item['doc'],image_map,inline=field!='body');display[field]=marker
        if field=='body':rich_body=True
    article=article_with_images({**display,'images':[]}) if rich_body else None
    html_text=unified_markdown(display,json.loads(w.brief),report,draft,article=article) if styled else text
    safe=bleach.clean(markdown.markdown(html_text),tags={'h1','h2','h3','p','ul','ol','li','strong','em','blockquote','a','img','br','hr','code','pre'},attributes={'a':['href'],'img':image_attribute},protocols=['https','http'])
    for marker,fragment in styled.items():safe=safe.replace('<p>'+marker+'</p>',fragment).replace(marker,fragment)
    if scope=='publication':safe=render_publication(c,json.loads(w.brief)['platform'],image_relative_url,gallery=publication_gallery)
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(c['title'])+'</title><style>body{max-width:860px;margin:40px auto;padding:0 20px;font-family:system-ui;font-synthesis:weight style;line-height:1.8;overflow-wrap:anywhere}img{max-width:100%;height:auto}</style><body>'+safe+'</body></html>'
    if format=='zip':
        data=io.BytesIO()
        with zipfile.ZipFile(data,'w',zipfile.ZIP_DEFLATED) as z:
            z.writestr('article.md',text);z.writestr('article.html',page);z.writestr('sources.json',js(c.get('sources',[])));z.writestr('verification.json',w.report)
            z.writestr('scenario.json',js(scenario_judgment(json.loads(w.brief),c.get('scenario'))))
            for im in c.get('images',[]):
                fp=work_image_path(im['id'],wid)
                if fp:z.write(fp,'images/'+im['name'])
            for name,path in publication_gallery_files:z.write(path,name)
            if publication_gallery:z.writestr('gallery.json',js(publication_gallery))
        blob=data.getvalue();media='application/zip'
    elif format=='html':
        # Standalone HTML embeds local source pictures, with no remote tracking.
        import base64,mimetypes
        for im in c.get('images',[]):
            fp=work_image_path(im['id'],wid)
            if fp:page=page.replace(image_relative_url(im),'data:'+(mimetypes.guess_type(fp)[0] or 'image/png')+';base64,'+base64.b64encode(fp.read_bytes()).decode())
        for name,path in publication_gallery_files:page=page.replace(name,'data:'+(mimetypes.guess_type(path)[0] or 'image/png')+';base64,'+base64.b64encode(path.read_bytes()).decode())
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
    style:Literal['studio','ember']='studio'

class PosterInput(BaseModel):
    image_id:str=Field(min_length=1,max_length=150)
    expected_version:int=Field(ge=1)
    scene:str=Field(min_length=2,max_length=800)
    ratio:Literal['1:1','3:4','16:9']='3:4'
    request_id:str=Field(pattern=r'^[A-Za-z0-9_-]{10,100}$')

    @field_validator('scene')
    @classmethod
    def meaningful_scene(cls,value):
        if len(value.strip())<2:raise ValueError('请填写具体使用场景')
        return value.strip()

@app.post('/api/works/{wid}/poster-tasks')
async def poster_task(wid:str,body:PosterInput,u=Depends(staff)):
    with Session() as session:
        existing=session.get(Job,body.request_id)
        if existing:
            if existing.actor_id!=u.id or existing.kind!='poster' or existing.target_id!=wid:
                raise HTTPException(409,'任务编号冲突')
            return {'job_id':existing.id}
        work=session.get(Work,wid)
        if not work:raise HTTPException(404,'作品不存在')
        try:payload=prepare_poster(work,body.image_id,body.scene,body.ratio,body.expected_version)
        except ValueError as error:raise HTTPException(409,str(error))
        job=Job(id=body.request_id,kind='poster',actor_id=u.id,target_id=wid,payload=js(payload))
        session.add(job)
        try:session.commit()
        except IntegrityError:session.rollback();raise HTTPException(409,'请求已存在，请刷新任务列表')
    asyncio.create_task(run_poster(job.id));return {'job_id':job.id}

@app.post('/api/works/{wid}/compose')
def composition(wid:str,body:CompositeInput,u=Depends(staff)):
    try:return compose(wid,u.id,body.image_id,body.background_id,body.ratio,body.style)
    except ValueError as e:raise HTTPException(400,str(e))


class MomentsGalleryInput(BaseModel):
    expected_version:int=Field(ge=1)
    count:Literal[1,3,6,9]=3
    mode:Literal['original','mixed','ai']='mixed'
    scene:str=Field(min_length=2,max_length=800)
    request_id:str=Field(pattern=r'^[A-Za-z0-9_-]{10,100}$')

    @field_validator('scene')
    @classmethod
    def meaningful_scene(cls,value):
        if len(value.strip())<2:raise ValueError('请填写具体配图场景')
        return value.strip()


@app.post('/api/works/{wid}/moments-gallery-tasks')
async def moments_gallery_task(wid:str,body:MomentsGalleryInput,u=Depends(staff)):
    with Session() as session:
        existing=session.get(Job,body.request_id)
        if existing:
            previous=json.loads(existing.payload)
            if existing.actor_id!=u.id or existing.kind!='moments_gallery' or existing.target_id!=wid or any(previous.get(key)!=value for key,value in {'work_version':body.expected_version,'count':body.count,'mode':body.mode,'scene':body.scene}.items()):raise HTTPException(409,'配图请求编号已用于另一组设置，请重新确认')
            return {'job_id':existing.id,'ai_count':previous['ai_count'],'original_count':previous['original_count']}
        work=session.get(Work,wid)
        if not work:raise HTTPException(404,'作品不存在')
        if work.version!=body.expected_version:raise HTTPException(409,'作品版本已变化，请刷新后准备配图')
        try:payload=prepare_gallery(work,body.count,body.mode,body.scene)
        except ValueError as error:raise HTTPException(409,str(error)) from None
        row=Job(id=body.request_id,kind='moments_gallery',actor_id=u.id,target_id=wid,payload=js(payload));session.add(row)
        try:session.commit()
        except IntegrityError:session.rollback();raise HTTPException(409,'请求已存在，请刷新配图任务')
    asyncio.create_task(run_moments_gallery(row.id))
    return {'job_id':row.id,'ai_count':payload['ai_count'],'original_count':payload['original_count']}


@app.get('/api/works/{wid}/moments-gallery')
def get_moments_gallery(wid:str,u=Depends(staff)):
    with Session() as session:
        work=session.get(Work,wid)
        if not work:raise HTTPException(404,'作品不存在')
        return {'gallery':latest_gallery(session,work),'previous_gallery':latest_gallery(session,work,previous=True)}


class MomentsGalleryOrder(BaseModel):
    expected_version:int=Field(ge=1)
    expected_revision:int=Field(ge=1)
    order:list[int]=Field(min_length=1,max_length=9)


@app.patch('/api/works/{wid}/moments-gallery/{gid}')
def reorder_moments_gallery(wid:str,gid:str,body:MomentsGalleryOrder,u=Depends(staff)):
    with Session() as session:
        work=session.get(Work,wid);album=session.get(Asset,gid)
        if not work or not album or album.kind!='moments_gallery':raise HTTPException(404,'配图不存在')
        previous=album.metadata_json;metadata=json.loads(previous)
        if metadata.get('work_id')!=wid:raise HTTPException(404,'配图不属于当前作品')
        if work.version!=body.expected_version or metadata['work_version']!=work.version or metadata['revision']!=body.expected_revision:raise HTTPException(409,'文案或配图顺序已变化，请刷新后调整')
        if sorted(body.order)!=list(range(len(metadata['items']))):raise HTTPException(422,'必须保留每张图片且不能重复')
        metadata['items']=[metadata['items'][index] for index in body.order];metadata['revision']+=1
        changed=session.execute(update(Asset).where(Asset.id==gid,Asset.metadata_json==previous).values(metadata_json=js(metadata)))
        if not changed.rowcount:raise HTTPException(409,'配图顺序已更新，请刷新')
        private_asset(album.path).write_text(js(metadata),encoding='utf-8');audit(session,u.id,'reorder_moments_gallery',wid);session.commit()
        return {'ok':True,'revision':metadata['revision']}


@app.get('/api/works/{wid}/moments-gallery/{gid}/download')
def download_moments_gallery(wid:str,gid:str,u=Depends(staff)):
    with Session() as session:
        work=session.get(Work,wid);album=session.get(Asset,gid)
        if not work or not album or album.kind!='moments_gallery':raise HTTPException(404,'配图不存在')
        result=public_gallery(album)
        if result.get('work_id')!=wid:raise HTTPException(404,'配图不属于当前作品')
        try:blob=gallery_zip(session,work,result)
        except ValueError as error:raise HTTPException(409,str(error)) from None
        return Response(blob,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="moments-gallery.zip"'})

class FollowupInput(BaseModel):
    conversation_id:str
    days:list[int]=Field(default_factory=lambda:[1,3,5],min_length=1,max_length=3)

@app.post('/api/followups/plan')
def followup_plan(body:FollowupInput,u=Depends(staff)):
    if any(d not in {1,3,5} for d in body.days):raise HTTPException(400,'支持1/3/5天计划')
    with Session() as s:
        c=allowed_conv(s,body.conversation_id,u,True)
        if c.stage in {'暂不购买','已成交'}:raise HTTPException(409,'当前阶段不再新增营销跟进')
        existing=list(s.scalars(select(Followup).where(Followup.conversation_id==c.id,Followup.status=='pending')))
        if existing:raise HTTPException(409,'已有待办跟进，请先处理或调整')
        from .reception import followup_content
        goals={1:'补齐关键需求与遗留疑问',3:'方案反馈与购买顾虑',5:'购买、到店与后续安排'}
        scripts={1:'您好，上次咨询还有哪些问题需要补充？',3:'您好，上次讨论的方案看过了吗？还有哪些顾虑需要我们一起核对？',5:'您好，想了解一下您的购机或到店安排。如暂时不需要，我会停止后续跟进。'}
        goals,scripts=followup_content(s,c,goals,scripts)
        for d in dict.fromkeys(body.days):s.add(Followup(conversation_id=c.id,owner_id=u.id,due_at=(datetime.now(timezone.utc)+timedelta(days=d)).isoformat(),purpose=goals[d],script=scripts[d],generated=True,offset_days=d))
        audit(s,u.id,'followup_plan',c.id);s.commit();return {'ok':True}

@app.get('/api/followups')
def followups(u=Depends(staff)):
    with Session() as s:
        query=select(Followup,Conversation.customer_name).join(Conversation,Conversation.id==Followup.conversation_id).where(
            Followup.owner_id==u.id,
            Conversation.id.not_in(select(ConversationDismissal.conversation_id).where(ConversationDismissal.user_id==u.id)),
            (Followup.status!='pending') | (Conversation.owner_id==u.id),
        ).order_by(Followup.due_at)
        from .reception import followup_draft
        return [{**record(f),**followup_draft(s,f),'customer_name':name} for f,name in s.execute(query)]

@app.get('/api/notifications')
def followup_notifications(u=Depends(staff)):
    # Read pending deadlines directly: reconnects/restarts retain reminders, without
    # creating duplicate notifications or ever inserting a customer chat message.
    with Session() as s:
        query=select(Followup,Conversation.customer_name).join(Conversation,Conversation.id==Followup.conversation_id).where(
            Followup.status=='pending',Followup.owner_id==u.id,Conversation.owner_id==u.id,
            Conversation.stage.not_in(['暂不购买','已成交']),
            Conversation.id.not_in(select(ConversationDismissal.conversation_id).where(ConversationDismissal.user_id==u.id)),
            func.julianday(Followup.due_at)<=func.julianday(now()),
        ).order_by(func.julianday(Followup.due_at),Followup.id)
        from .reception import followup_draft
        result=[{**record(f),**followup_draft(s,f),'customer_name':name,'kind':'followup'} for f,name in s.execute(query)]
        from .reception import verification_notifications
        return result+verification_notifications(s,u.id)

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
        if c and (c.owner_id!=u.id or s.get(ConversationDismissal,(u.id,c.id))) and u.role!='admin':raise HTTPException(409,'请先认领或接管此会话')
        if body.status=='pending' and c and c.stage in {'暂不购买','已成交'}:raise HTTPException(409,'当前客户阶段不能恢复营销跟进')
        if body.purpose is not None or body.script is not None:f.generated=False
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

@app.get('/api/admin/conversations')
def admin_conversation_overview(u=Depends(admin)):
    with Session() as session:return assignment_overview(session)

@app.post('/api/admin/conversations/assign')
async def admin_assign_conversations(body:AssignmentInput,u=Depends(admin)):
    with Session() as session:result=assign_conversations(session,u.id,body)
    for row in body.conversations:await broadcast(row.id)
    return result

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
    return {'text':model_settings.get_config().public(),'image':{**image_settings.get_config().public(),'last_error':image_error},'knowledge':knowledge.status(),'marketing_knowledge':{'provider':MARKETING_SOURCE,**connection_status()},'backups':[p.name for p in sorted((DATA/'backups').glob('*.db'))]}

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

@app.get('/api/admin/image-model')
def image_model(u=Depends(admin)):
    return JSONResponse(image_settings.get_config().public(),headers={'Cache-Control':'no-store'})

@app.put('/api/admin/image-model')
async def save_image_model(request:Request,u=Depends(admin)):
    try:
        if len(await request.body())>16000:raise ValueError('图片配置内容过长')
        body=await request.json()
        result=await asyncio.to_thread(image_settings.save_config,body)
    except ValueError as error:
        detail='图片配置格式无效' if isinstance(error,json.JSONDecodeError) else str(error)
        raise HTTPException(400,detail) from None
    except OSError:
        raise HTTPException(500,'图片配置保存失败，请检查私有目录权限') from None
    with Session() as session:audit(session,u.id,'update_image_model');session.commit()
    return JSONResponse(result,headers={'Cache-Control':'no-store'})

@app.post('/api/admin/image-model/reset')
def reset_image_model(u=Depends(admin)):
    result=image_settings.reset_config()
    with Session() as session:audit(session,u.id,'reset_image_model');session.commit()
    return JSONResponse(result,headers={'Cache-Control':'no-store'})

@app.post('/api/admin/check-image-model')
async def check_image_model(u=Depends(admin)):
    return await image_settings.check_config()

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
