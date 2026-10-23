"""Isolated, labelled reception fixtures for browser acceptance; no external calls."""
import json
import os
import secrets
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
folder=Path(os.environ['E2E_DATA_DIR']).resolve()
if not folder.is_relative_to(ROOT/'tmp'):raise ValueError('验收目录必须位于项目 tmp 内')
folder.mkdir(parents=True,exist_ok=True)
os.environ.update(STORE_DATA_DIR=str(folder),TEXT_API_KEY='',MODELSCOPE_IMAGE_API_KEY='',IMA_OPENAPI_CLIENTID='',IMA_OPENAPI_APIKEY='',MARKETING_KNOWLEDGE_SOURCE='local_zip')
from backend import ai,dialogue,knowledge as kb
from backend.main import app,ph
from backend.db import init_db,Session,User,Conversation,Message,DialogueState
from backend.service_tasks import sync_tasks
from backend.service_workflow import WORKFLOW_VERSION
kb.INDEX=ROOT/'data'/'knowledge'/'index.db'
init_db()
password=secrets.token_urlsafe(24)
with Session() as s:
    staff=User(username='reception_staff',display_name='隔离验收客服',password=ph.hash(password),role='staff')
    admin=User(username='reception_admin',display_name='隔离验收管理员',password=ph.hash(password),role='admin')
    s.add_all([staff,admin]);s.flush()
    conv=Conversation(customer_id='synthetic-customer',customer_name='多轮验收夹具',owner_id=staff.id,status='active',seq=3,analysis_seq=3)
    s.add(conv);s.flush()
    texts=[('customer','我用 Blender 做中等场景建模，想了解这台电脑。'),('staff','具体适配表现需要门店核实。'),('customer','ok')]
    for seq,(role,text) in enumerate(texts,1):s.add(Message(conversation_id=conv.id,sender_id='synthetic-'+role,role=role,content=text,seq=seq,client_id=secrets.token_hex(12)))
    s.flush();messages=dialogue.messages_for(s,conv.id)
    state=dialogue.initial_state(conv,messages)
    sync_tasks(state,[{'key':'verify:software-fit','kind':'verify','title':'核实 Blender 适配性（验收夹具）','evidence':{'message_id':messages[0]['id'],'quote':messages[0]['text']}}],messages,1)
    state['tasks'][0]['due_at']=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
    state.update(workflow_version=WORKFLOW_VERSION,revision=1,message_seq=3,goal='information',continuation={'mode':'answer','reason':'等待门店处理'},
                 response_required=False,next_owner='staff',waiting_reason='门店核实尚未完成，客户已确认收到，无需重复回复',
                 action={'id':'fixture','kind':'wait','reply':'','candidates':[],'message_seq':3,'revision':1})
    s.add(DialogueState(conversation_id=conv.id,revision=1,message_seq=3,state=json.dumps(state,ensure_ascii=False)))
    s.commit()
    (folder/'login.json').write_text(json.dumps({'staff':'reception_staff','admin':'reception_admin','password':password,'cid':conv.id}),encoding='utf-8')


async def fixture(instruction,data,*args,**kwargs):
    name=kwargs['schema'].__name__
    if name=='ProgressReview':return {'next_question':None,'reason':'隔离夹具没有其他客户决策请求','paths':[
        {'area':area,'status':'not_relevant','reason':'此隔离夹具明确只等待固定结果','question':None}
        for area in ['verification_scope','decision_criteria','decision_path']]},{}
    if name=='ServiceCustomerUpdate':return {'changes':[],'resolutions':[]},{}
    if name=='ServicePlanning':
        message=data['current_turn']
        staff_message=next(m for m in reversed(data['messages']) if m['role']=='staff')
        return {'next_question':None,'plan':{'customer_act':'acknowledge','customer_evidence':{'message_id':message['id'],'quote':message['text']},
            'goal':'information','action':'inform','continuation':{'mode':'answer','reason':'核实结果到达后给出新答复'},
            'topic':None,'acknowledged_message_id':staff_message['id'],'conversation_scope':None},'tasks':[]},{}
    if name=='ServiceDraft':
        source=next(s for s in data['tools']['sources'] if s.get('source_type')=='staff_verified')
        return {'candidates':[{'label':'结果'+str(i+1),'answer':text,'question':None,'citations':[{'source_id':source['id']}]} for i,text in enumerate([
            '验收夹具：核实记录已确认指定环境。','验收夹具：指定环境的核实结果已经登记。','验收夹具：本次适配核实已完成，可查看登记结果。'])],'option_ids':[]},{}
    if name=='ServiceAudit':return {'errors':[],'invalid_need_fields':[],'invalid_candidates':[],
        'reviews':[{'index':i,'grounded':True,'responsive':True,'reason':'隔离验收固定结果'} for i in range(len(data['candidates']))]},{}
    raise ValueError('验收夹具未定义此模型阶段：'+name)

ai.model_json=fixture
