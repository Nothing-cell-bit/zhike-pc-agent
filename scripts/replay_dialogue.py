"""Replay an existing conversation in an isolated DB; never write to its source."""
import argparse,asyncio,json,sqlite3,sys,time
from datetime import datetime
from pathlib import Path
from evaluate_natural_dialogue import ROOT,ai,Session,Conversation,Message
from backend.db import DialogueState


async def replay(cid,diagnose_network=False):
    source=sqlite3.connect('file:'+str(ROOT/'data'/'store.db')+'?mode=ro',uri=True);source.row_factory=sqlite3.Row
    original=source.execute('select * from conversations where id=?',(cid,)).fetchone()
    if not original:raise ValueError('Conversation not found')
    messages=source.execute('select * from messages where conversation_id=? order by seq',(cid,)).fetchall()
    previous=source.execute('select * from dialogue_states where conversation_id=?',(cid,)).fetchone()
    with Session() as session:
        session.add(Conversation(id=cid,customer_id='replay-customer',customer_name='历史故障回放（隔离）',owner_id='replay-staff',
            seq=original['seq'],analysis=original['analysis'],analysis_seq=original['analysis_seq'],locked=original['locked'],stage=original['stage']))
        for message in messages:session.add(Message(id=message['id'],conversation_id=cid,sender_id='replay-'+message['role'],role=message['role'],
            content=message['content'],card=message['card'],seq=message['seq'],client_id=message['client_id']))
        if previous:session.add(DialogueState(conversation_id=cid,revision=previous['revision'],message_seq=previous['message_seq'],state=previous['state']))
        session.commit()
    folder=ROOT/'tmp'/'dialogue-natural'/('replay-'+datetime.now().strftime('%Y%m%d-%H%M%S-%f'));folder.mkdir(parents=True)
    source.close();start=time.monotonic();attempts=[]
    if diagnose_network:
        original_completion=ai.completion
        async def measured(settings,payload,timeout=100):
            begin=time.monotonic();event={'schema':payload.get('response_format',{}).get('json_schema',{}).get('name','json'),'timeout_seconds':timeout}
            try:
                response=await original_completion(settings,payload,timeout=timeout)
                event['http_status']=response.status_code;return response
            except Exception as error:
                event['error_type']=type(error).__name__
                event['causes']=[];cause=error.__cause__
                while cause is not None:
                    event['causes'].append(type(cause).__name__);cause=cause.__cause__
                raise
            finally:
                event['seconds']=round(time.monotonic()-begin,2);attempts.append(event)
                (folder/'network-attempts.json').write_text(json.dumps(attempts,ensure_ascii=False,indent=2),encoding='utf-8')
                print(json.dumps(event),flush=True)
        ai.completion=measured
    print('ARTIFACT '+str(folder),flush=True)
    try:result=await ai.analysis(cid)
    except Exception as error:
        (folder/'failure.json').write_text(json.dumps({'error_type':type(error).__name__,'message':str(error),'seconds':round(time.monotonic()-start,2),'network_attempts':attempts},ensure_ascii=False,indent=2),encoding='utf-8')
        raise
    result['seconds']=round(time.monotonic()-start,2);result['isolated']=True
    (folder/'result.json').write_text(json.dumps(result,ensure_ascii=False,indent=2),'utf-8')
    state=result['dialogue']
    print(json.dumps({'artifact':str(folder),'seconds':result['seconds'],'topic':state.get('topic'),'action':state['action'],
        'needs':{k:v['value'] for k,v in state['needs'].items() if isinstance(v,dict) and v.get('status')!='unknown'}},ensure_ascii=False))


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('conversation');parser.add_argument('--live',action='store_true');parser.add_argument('--diagnose-network',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('Explicit --live is required for the text-model replay')
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(replay(args.conversation,args.diagnose_network))
