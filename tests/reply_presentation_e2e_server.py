"""Isolated UI replay of the reported message and the actual repaired LLM answer."""
import json,os,secrets
from pathlib import Path
from sqlalchemy import delete,select
from .reception_e2e_server import app,folder,Session,User,Conversation,Message,DialogueState,ph

payload=json.loads(Path(os.environ['REPLY_PRESENTATION_FIXTURE']).read_text(encoding='utf-8'))
login=json.loads((folder/'login.json').read_text(encoding='utf-8'))
with Session() as session:
    customer=User(username='presentation_customer',display_name='显示复核客户',password=ph.hash(login['password']),role='customer')
    session.add(customer);session.flush()
    conv=session.get(Conversation,login['cid']);conv.customer_id=customer.id
    session.execute(delete(Message).where(Message.conversation_id==conv.id))
    entries=[('customer',payload['customer']),('staff',payload['legacy']),('customer',payload['customer']),('staff',payload['repaired'])]
    for seq,(role,text) in enumerate(entries,1):session.add(Message(conversation_id=conv.id,sender_id=customer.id if role=='customer' else conv.owner_id,
        role=role,content=text,seq=seq,client_id=secrets.token_hex(16)))
    conv.seq=conv.analysis_seq=4
    row=session.get(DialogueState,conv.id);state=json.loads(row.state);state['message_seq']=4;state['action']['message_seq']=4;row.message_seq=4;row.state=json.dumps(state,ensure_ascii=False)
    session.commit()
login['customer']='presentation_customer'
(folder/'login.json').write_text(json.dumps(login),encoding='utf-8')
