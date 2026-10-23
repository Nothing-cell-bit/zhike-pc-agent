"""Replay the reported refresh against an isolated DB snapshot; never send messages."""
import argparse,asyncio,copy,json,os,sqlite3,sys,time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


async def replay(cid):
    folder=ROOT/'tmp'/('dialogue-live-refresh-'+time.strftime('%Y%m%d-%H%M%S'))
    folder.mkdir()
    with sqlite3.connect(ROOT/'data'/'store.db') as src,sqlite3.connect(folder/'store.db') as dest:src.backup(dest)
    os.environ['STORE_DATA_DIR']=str(folder)
    from backend import ai,knowledge,dialogue_catalog
    from backend.db import Session,DialogueState,DialogueRun
    from sqlalchemy import select
    knowledge.INDEX=ROOT/'data'/'knowledge'/'index.db'
    dialogue_catalog.CACHE_ROOT=ROOT/'data'/'ima'
    report={'conversation_id':cid,'folder':str(folder),'operations':[],'passed':False}
    print('ARTIFACT',folder,flush=True)
    try:
        for operation in ('refresh_original','analysis','refresh_analyzed','refresh_again'):
            with Session() as s:before=json.loads(s.get(DialogueState,cid).state)
            start=time.perf_counter()
            result=await ai.analysis(cid) if operation=='analysis' else await ai.suggestions(cid,{})
            state=result['dialogue']
            keys=['needs','tasks','questions','selection','quotes','mission']
            unchanged=all(state.get(k)==before.get(k) for k in keys)
            candidates=state['action']['candidates']
            assert len(candidates)==3
            if operation!='analysis':
                assert unchanged
                assert [c['reply'] for c in candidates]!=[c['reply'] for c in before['action']['candidates']]
            record={'operation':operation,'seconds':round(time.perf_counter()-start,2),'business_state_unchanged':unchanged,
                    'candidates':candidates,'needs':state['needs'],'tasks':state['tasks'],'continuation':state['continuation']}
            report['operations'].append(record)
            with Session() as s:
                run=s.scalar(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at.desc()).limit(1))
                (folder/(operation+'-trace.json')).write_text(run.trace,encoding='utf8')
            print(operation,record['seconds'],flush=True)
        report['passed']=True
    except Exception as e:report['error']=str(e);print(type(e).__name__,str(e),flush=True)
    finally:(folder/'refresh-report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf8')
    print('RESULT',report['passed'],flush=True)
    return report['passed']


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('conversation_id');parser.add_argument('--live',action='store_true')
    args=parser.parse_args()
    if not args.live:parser.error('--live is required')
    sys.stdout.reconfigure(encoding='utf8')
    sys.exit(0 if asyncio.run(replay(args.conversation_id)) else 1)
