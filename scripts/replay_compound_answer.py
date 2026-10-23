"""Verify a real answered discovery question in an isolated database snapshot."""
import argparse,asyncio,json,os,sqlite3,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

async def replay(cid):
    folder=ROOT/'tmp'/('dialogue-live-compound-'+time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir()
    with sqlite3.connect(ROOT/'data'/'store.db') as src,sqlite3.connect(folder/'store.db') as dest:src.backup(dest)
    os.environ['STORE_DATA_DIR']=str(folder)
    from backend import ai,knowledge,dialogue_catalog
    from backend.db import Session,Conversation,DialogueState,DialogueRun,Message
    from backend.dialogue import observe_sent
    from sqlalchemy import select
    knowledge.INDEX=ROOT/'data'/'knowledge'/'index.db';dialogue_catalog.CACHE_ROOT=ROOT/'data'/'ima'
    report={'conversation_id':cid,'folder':str(folder),'operations':[],'passed':False}
    print('ARTIFACT',folder,flush=True)
    def append(role,text,action_id=''):
        with Session() as s:
            conv=s.get(Conversation,cid);conv.seq+=1
            msg=Message(conversation_id=cid,sender_id='isolated-'+role,role=role,content=text,seq=conv.seq,client_id='isolated-'+str(conv.seq))
            s.add(msg);s.flush()
            if role=='staff':observe_sent(s,conv,msg,action_id)
            s.commit()
    async def step(name,refresh=False):
        with Session() as s:before=json.loads(s.get(DialogueState,cid).state)
        start=time.perf_counter()
        try:
            result=await ai.suggestions(cid,{}) if refresh else await ai.analysis(cid)
            state=result['dialogue'];action=state['action']
            assert len(action['candidates'])==3
            assert state['needs']['user']['status']=='unknown','身份不能从软件或课程练习推断'
            assert state['needs']['progress']['status']=='unknown','服务推进不能改写购机意向'
            if refresh:
                assert all(state.get(k)==before.get(k) for k in ['needs','tasks','questions','selection','quotes','mission'])
                assert [c['reply'] for c in action['candidates']]!=[c['reply'] for c in before['action']['candidates']]
            report['operations'].append({'name':name,'seconds':round(time.perf_counter()-start,2),'state':state})
            print(name,report['operations'][-1]['seconds'],json.dumps(action['candidates'],ensure_ascii=False),flush=True)
            return state
        finally:
            with Session() as s:
                run=s.scalar(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at.desc()).limit(1))
                (folder/(name+'-trace.json')).write_text(run.trace,encoding='utf8')
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    try:
        state=await step('actual_answer')
        assert '3D建模' in state['needs']['tasks']['value']
        assert 'blender' in state['needs']['software']['value'].lower()
        assert any(q['status']=='answered' and '哪类' in q['text'] for q in state['questions'])
        assert any(t['status']=='completed' and 'design_detail' in t['key'] for t in state['tasks'])
        state=await step('refresh',True)
        candidate=next((c for c in state['action']['candidates'] if c.get('question')),state['action']['candidates'][0])
        append('staff',candidate['reply'],candidate['id'])
        append('customer','主要是课程练习，做简单产品模型，不做复杂渲染，预算7000以内。')
        state=await step('project_and_budget')
        assert 'blender' in state['needs']['software']['value'].lower()
        assert '7000' in state['needs']['budget']['value']
        report['passed']=True
    except Exception as e:report['error']=type(e).__name__+': '+str(e);print(report['error'],flush=True)
    finally:(folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('RESULT',report['passed'],flush=True)
    return report['passed']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('conversation_id');parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live is required')
    sys.stdout.reconfigure(encoding='utf8')
    sys.exit(0 if asyncio.run(replay(args.conversation_id)) else 1)
