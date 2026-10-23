"""A fresh isolated browser run, using the site's real text model; no production messages."""
import json
import os
import secrets
from datetime import datetime,timedelta,timezone
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
folder=Path(os.environ['E2E_DATA_DIR']).resolve()
if not folder.is_relative_to(ROOT/'tmp') or (folder/'store.db').exists():
    raise RuntimeError('Use a fresh directory under project tmp for acceptance')
folder.mkdir(parents=True,exist_ok=True)
os.environ['STORE_DATA_DIR']=str(folder)
from backend import ai,dialogue,knowledge,model_settings,dialogue_catalog
from backend.main import app,ph
from backend.db import init_db,Session,User,Conversation,Message,DialogueState
from backend.service_tasks import sync_tasks
from backend.service_workflow import WORKFLOW_VERSION

# Load approved settings in memory without duplicating a key in the test data.
private=ROOT/'data/private/text-model.json'
if private.exists():
    settings=json.loads(private.read_text(encoding='utf-8'))
    model=model_settings.ModelConfig(settings['base_url'],settings['model'],settings['api_key'],'custom',settings.get('disable_thinking',False))
else:
    model=model_settings.get_config()
ai.get_config=lambda:model
knowledge.INDEX=ROOT/'data/knowledge/index.db'
# Isolate any new retrieval cache writes as well as business data.
import shutil
if (ROOT/'data/ima').exists():shutil.copytree(ROOT/'data/ima',folder/'ima',dirs_exist_ok=True)
dialogue_catalog.CACHE_ROOT=folder/'ima'
init_db()
password=secrets.token_urlsafe(24)
with Session() as s:
    staff=User(username='verification_staff',display_name='核实流程验收客服',password=ph.hash(password),role='staff')
    customer=User(username='verification_customer',display_name='核实流程演示客户',password=ph.hash(password),role='customer')
    s.add_all([staff,customer]);s.flush()
    conv=Conversation(customer_id=customer.id,customer_name=customer.display_name,owner_id=staff.id,status='active',seq=3,analysis_seq=3)
    s.add(conv);s.flush()
    texts=[('customer','我考虑 MateBook D 16 2024，想用 Windows 11 跑 Blender 4.2，做中等场景建模，暂时不做复杂渲染。先帮我确认这个场景能不能用，确认后继续帮我选配置。'),
           ('staff','您的软件、系统和建模场景已记录，具体适配表现需要门店核实。'),('customer','好的，核实后告诉我，再继续选。')]
    for seq,(role,text) in enumerate(texts,1):s.add(Message(conversation_id=conv.id,sender_id=staff.id if role=='staff' else customer.id,role=role,content=text,seq=seq,client_id=secrets.token_hex(16)))
    s.flush();messages=dialogue.messages_for(s,conv.id);state=dialogue.initial_state(conv,messages)
    product=next(p for p in dialogue.catalog_index() if 'MateBook D 16 2024' in p['name'])
    sync_tasks(state,[{'key':'verify:blender-fit','kind':'verify','title':'核实 MateBook D 16 2024 的 Blender 4.2 中等建模场景','product_ids':[product['id']],
                       'evidence':{'message_id':messages[0]['id'],'quote':messages[0]['text']}}],messages,1)
    state['tasks'][0]['due_at']=(datetime.now(timezone.utc)-timedelta(minutes=10)).isoformat()
    state.update(workflow_version=WORKFLOW_VERSION,revision=1,message_seq=3,goal='information',continuation={'mode':'answer','reason':'等待核实结果'},
                 response_required=False,next_owner='staff',waiting_reason='已记录适配疑问，等待门店核实',
                 action={'id':'acceptance-wait','kind':'wait','reply':'','candidates':[],'message_seq':3,'revision':1})
    s.add(DialogueState(conversation_id=conv.id,revision=1,message_seq=3,state=json.dumps(state,ensure_ascii=False)))
    s.commit()
    (folder/'login.json').write_text(json.dumps({'staff':staff.username,'customer':customer.username,'password':password,'cid':conv.id,'task_id':state['tasks'][0]['id'],'model':model.model}),encoding='utf-8')
