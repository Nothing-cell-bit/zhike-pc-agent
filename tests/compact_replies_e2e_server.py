"""Isolated UI data for the one-reply preview and centered alternatives dialog."""
import json
from .reception_e2e_server import app,folder,ROOT,Session,DialogueState,Message
from sqlalchemy import select

login=json.loads((folder/'login.json').read_text(encoding='utf-8'))
samples=json.loads((ROOT/'output/model-recovery-20261022/实际回复.json').read_text(encoding='utf-8'))
with Session() as session:
    texts=['我想了解 MateBook D 16 2024，主要编程用。','您主要做哪类编程？会同时开大型 IDE 或虚拟机吗？','都要，会。']
    for message,text in zip(session.scalars(select(Message).where(Message.conversation_id==login['cid']).order_by(Message.seq)),texts):message.content=text
    row=session.get(DialogueState,login['cid']);state=json.loads(row.state)
    candidates=[{'id':'preview-'+str(i),'label':item['label'],'answer':item['reply'],'reply':item['reply'],'intro':item['reply'],'question':None,'citations':[]} for i,item in enumerate(samples[:3])]
    state.update(response_required=True,waiting_reason='',goal='information',reply_context={'sources':[],'suffix':''},
                 knowledge_retrieval=[{'status':'cached','retrieved_at':'2026-10-22T00:06:06+00:00'}],
                 action={'id':'preview-main','kind':'inform','reply':candidates[0]['reply'],'intro':candidates[0]['reply'],
                         'candidates':candidates,'option_ids':[],'message_seq':3,'revision':1,'status':'proposed'})
    row.state=json.dumps(state,ensure_ascii=False);session.commit()
