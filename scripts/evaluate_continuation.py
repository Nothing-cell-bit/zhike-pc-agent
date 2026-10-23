"""Live semantic checks for topic receipts, voluntary exploration and explicit endings."""
import argparse,asyncio,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_natural_dialogue import ROOT,ai,append,Session,Conversation
from backend.db import DialogueRun
from sqlalchemy import select


async def run():
    folder=ROOT/'tmp'/'continuation'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);folder.mkdir(parents=True)
    report={'cases':[],'passed':False};print('ARTIFACT '+str(folder),flush=True)
    async def analyze(case,customer,expected,allowed):
        append(case['cid'],'customer',customer);start=time.monotonic()
        result=await ai.analysis(case['cid']);state=result['dialogue'];candidates=state['action'].get('candidates',[])
        needs={k:v['value'] for k,v in state['needs'].items() if isinstance(v,dict) and v.get('status')!='unknown'}
        checks={'three_candidates':len(candidates)==3,'no_profile_pollution':set(needs)<=set(allowed)}
        if expected=='bridge':
            checks.update(planner_bridges=(state.get('continuation') or {}).get('mode')=='bridge',
                          offers_question=any(c.get('question') for c in candidates),
                          keeps_plain_answer=any(not c.get('question') for c in candidates))
        if expected in {'focused','close'}:checks['no_question']=all(not c.get('question') for c in candidates)
        if expected=='focused':checks['session_not_closed']=(state.get('continuation') or {}).get('mode')!='close'
        if expected=='close':checks['explicit_end']=(state.get('continuation') or {}).get('mode')=='close'
        if 'tasks' in allowed:checks['usage_retained']='剪辑' in needs.get('tasks','')
        if 'software' in allowed:checks['software_retained']='栖云工具' in needs.get('software','')
        if 'budget' in allowed:checks['budget_retained']='8000' in needs.get('budget','')
        record={'customer':customer,'continuation':state.get('continuation'),'scope':state.get('conversation_scope'),
                'customer_act':state.get('customer_act'),'needs':needs,'candidates':candidates,'checks':checks,'seconds':round(time.monotonic()-start,2)}
        case['turns'].append(record)
        with Session() as s:
            run=s.scalar(select(DialogueRun).where(DialogueRun.conversation_id==case['cid']).order_by(DialogueRun.created_at.desc()).limit(1))
            (folder/f'{case["name"]}-{len(case["turns"])}-trace.json').write_text(run.trace,'utf-8')
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        print(json.dumps({'case':case['name'],**record},ensure_ascii=False),flush=True)
        if not all(checks.values()):raise ValueError('Behavior checks failed: '+str(checks))
        return state
    def create(name):
        with Session() as s:
            c=Conversation(customer_id='synthetic',customer_name='接续验收 '+name,owner_id='synthetic');s.add(c);s.commit();cid=c.id
        case={'name':name,'cid':cid,'turns':[]};report['cases'].append(case);return case
    def send(case,state,probe=False):
        choices=state['action']['candidates'];choice=next((c for c in choices if probe and c.get('question')),choices[0])
        append(case['cid'],'staff',choice['reply'],choice['id']);case['turns'][-1]['adopted']=choice
    try:
        case=create('local_receipt')
        state=await analyze(case,'先只说MateBook GT 14的内存，能比32GB更大吗？','focused',[])
        append(case['cid'],'staff','资料列的内存是32GB，是否有更大版本还需要核实。')
        state=await analyze(case,'明白了','bridge',[]);send(case,state,True)
        state=await analyze(case,'我做设计，主要剪辑视频，必用单位的栖云工具，预算8000元。','respond',['user','tasks','software','budget']);send(case,state)
        state=await analyze(case,'先别问其他的，只说这款屏幕多大。','focused',['user','tasks','software','budget']);send(case,state)
        await analyze(case,'今天就到这里，不需要再问了。','close',['user','tasks','software','budget'])
        case=create('global_boundary')
        append(case['cid'],'customer','这次只问MateBook D 16 2024的接口情况，整个咨询都不要问我的个人需求。')
        append(case['cid'],'staff','资料列了一个USB-C接口，是否支持给电脑充电还需要核实。')
        await analyze(case,'嗯，知道了','focused',[])
        case=create('quote_receipt')
        append(case['cid'],'customer','我想选一台电脑，还没确定型号。')
        append(case['cid'],'staff','价格需要等具体配置确认后再核对。')
        await analyze(case,'行','bridge',['progress'])
        report['passed']=True
    except Exception as error:report['error']=type(error).__name__+': '+str(error);print(report['error'],flush=True)
    for case in report['cases']:case['passed']=all(all(t['checks'].values()) for t in case['turns'])
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');print('RESULT '+str(report['passed']),flush=True)
    return report['passed']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');args=p.parse_args()
    if not args.live:p.error('Use --live for configured text-model calls in an isolated database')
    sys.stdout.reconfigure(encoding='utf-8');sys.exit(0 if asyncio.run(run()) else 1)
