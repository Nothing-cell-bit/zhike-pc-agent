"""Replay the reported acknowledgement/ambiguous-answer failures in an isolated DB."""
import argparse
import asyncio
import copy
import json
import sqlite3
import sys
from datetime import datetime
from evaluate_natural_dialogue import ROOT,ai,Session,Conversation,Message
from backend.db import DialogueState,DialogueRun
from sqlalchemy import select


async def replay(cid,cutoff):
    source=sqlite3.connect('file:'+(ROOT/'data'/'store.db').as_posix()+'?mode=ro',uri=True)
    source.row_factory=sqlite3.Row
    original=source.execute('select * from conversations where id=?',(cid,)).fetchone()
    records=source.execute('select * from messages where conversation_id=? and seq<=? order by seq',(cid,cutoff)).fetchall()
    stored=source.execute('select state from dialogue_states where conversation_id=?',(cid,)).fetchone()
    source.close()
    if not original or not records or not stored:raise ValueError('回放源记录不完整')
    state=json.loads(stored['state']);ids={m['id'] for m in records}
    state['questions']=[q for q in state['questions'] if q.get('seq',0)<cutoff]
    for question in state['questions']:
        if (question.get('answer') or {}).get('message_id') not in {m['id'] for m in records if m['seq']<cutoff}:
            question.update(status='asked');question.pop('answer',None)
    state['tasks']=[t for t in state.get('tasks',[]) if t.get('created_seq',0)<cutoff]
    for task in state['tasks']:
        if task['kind']=='discover' and any(q.get('topic_key')==task.get('topic_key') and q['status']=='asked' for q in state['questions']):task['status']='waiting_customer'
    for need in state['needs'].values():
        if not isinstance(need,dict):continue
        need['quotes']=[q for q in need.get('quotes',[]) if q['message_id'] in {m['id'] for m in records if m['seq']<cutoff}]
        need.pop('details',None)
        if need.get('quotes'):need['value']='；'.join(q['quote'] for q in need['quotes'])
    state.update(revision=1,message_seq=cutoff-1,pending_service_events=[])
    with Session() as session:
        conv=Conversation(id=cid,customer_id='synthetic-customer',customer_name='原会话故障回放（隔离）',owner_id='synthetic-staff',
                          seq=cutoff,analysis_seq=cutoff-1,locked=original['locked'],stage=original['stage'])
        session.add(conv)
        for m in records:session.add(Message(id=m['id'],conversation_id=cid,sender_id='synthetic-'+m['role'],role=m['role'],content=m['content'],seq=m['seq'],client_id=m['client_id']))
        session.add(DialogueState(conversation_id=cid,revision=1,message_seq=cutoff-1,state=json.dumps(state,ensure_ascii=False)))
        session.commit()
    result=await ai.analysis(cid)
    with Session() as session:
        trace=json.loads(session.scalar(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at.desc()).limit(1)).trace)
    folder=ROOT/'tmp'/'reception-live'/datetime.now().strftime('%Y%m%d-%H%M%S-%f');folder.mkdir(parents=True)
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),encoding='utf-8')
    (folder/'trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
    state=result['dialogue']
    print(json.dumps({'artifact':str(folder),'cutoff':cutoff,'action':state['action'],'next_owner':state['next_owner'],
                      'question_statuses':[(q['text'],q['status']) for q in state['questions']],
                      'needs':state['needs'].get('tasks'),'retrieval':state.get('knowledge_retrieval')},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('conversation');parser.add_argument('--cutoff',type=int,required=True)
    parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live is required for real text model calls')
    sys.stdout.reconfigure(encoding='utf-8')
    asyncio.run(replay(args.conversation,args.cutoff))
