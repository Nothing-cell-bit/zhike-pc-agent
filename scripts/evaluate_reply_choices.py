"""Real-model conversations for reply choices, consent to probing, and draft isolation."""
import argparse,asyncio,copy,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_natural_dialogue import append,Session,Conversation,ai,ROOT
from backend.db import DialogueState,DialogueRun
from sqlalchemy import select

CASES={
 'memory_correction':[
  ('MateBook GT 14内存多大？我只问内存。',[],False),
  ('有没有更大内存的？',[],False),
  ('不是问容量了，我想知道自己能不能加内存。',[],False),
  ('不用了解我的用途，只看这个参数就行。',[],False)],
 'ports_switch':[
  ('MateBook D 16 2024有几个USB-C接口？',[],True),
  ('这个口能给电脑充电吗？',[],False),
  ('那换成MateBook D 14 2024呢，同样问C口。',[],False)],
 'buying_context':[
  ('我准备换电脑，平时办公。看中MateBook 14酷睿Ultra，但不确定适不适合我。',['progress','tasks','concerns'],True),
  ('主要用Excel和PowerPoint，预算最多8000，别的用途没有了。',['progress','tasks','concerns','software','budget'],True),
  ('预算改成7000以内。先别问其他的，帮我看看这款的屏幕多大。',['progress','tasks','concerns','software','budget'],False),
  ('换成MateBook X Pro酷睿Ultra微绒典藏版，只说屏幕尺寸。',['progress','tasks','concerns','software','budget'],False)]}

async def run(names):
    folder=ROOT/'tmp'/'reply-choices'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);folder.mkdir(parents=True)
    report={'cases':[],'passed':False};print('ARTIFACT '+str(folder),flush=True)
    for name in names:
        with Session() as s:
            c=Conversation(customer_id='synthetic',customer_name='三候选验收 '+name,owner_id='synthetic');s.add(c);s.commit();cid=c.id
        case={'name':name,'cid':cid,'turns':[]};report['cases'].append(case)
        for i,(customer,allowed,probing) in enumerate(CASES[name]):
            append(cid,'customer',customer);start=time.monotonic();record={'customer':customer}
            try:
                result=await ai.analysis(cid);state=result['dialogue'];choices=state['action'].get('candidates',[])
                record['candidates']=copy.deepcopy(choices)
                record['needs']={k:v['value'] for k,v in state['needs'].items() if isinstance(v,dict) and v.get('status')!='unknown'}
                checks={'three_choices':len(choices)==3,'no_pollution':set(record['needs'])<=set(allowed),
                        'no_unwanted_probe':probing or all(not c['question'] for c in choices),
                        'one_direct_answer':any(not c['question'] for c in choices) or state['action']['kind']=='ask'}
                if name=='buying_context' and i>=1:checks['usage_retained']='办公' in record['needs'].get('tasks','')
                if name=='buying_context' and i>=2:checks['corrected_budget']='7000' in record['needs'].get('budget','') and '8000' not in record['needs'].get('budget','')
                if i==0 and name!='buying_context':
                    phases=[];original=ai.model_json
                    async def tracked(*args,**kwargs):
                        phases.append(args[1].get('phase'));return await original(*args,**kwargs)
                    ai.model_json=tracked
                    try:renewed=await ai.suggestions(cid,{})
                    finally:ai.model_json=original
                    checks['regenerate_only_wording']=set(phases)<={'reply_choices','review_choices'}
                    checks['regenerate_keeps_needs']=renewed['dialogue']['needs']==state['needs']
                    checks['regenerate_keeps_topic']=renewed['dialogue']['topic']==state['topic']
                    fresh=renewed['dialogue']['action']['candidates']
                    checks['new_choices']=len({c['reply'] for c in fresh}-{c['reply'] for c in choices})>=1
                    record['regenerated']=fresh;state=renewed['dialogue'];choices=fresh
                chosen=next((c for c in choices if probing and c['question']),choices[0])
                record['adopted']=chosen;record['checks']=checks
                append(cid,'staff',chosen['reply'],chosen['id'])
                with Session() as s:
                    sent=json.loads(s.get(DialogueState,cid).state)
                    checks['only_sent_question_recorded']=not chosen['question'] or any(q['text']==chosen['question']['text'] for q in sent['questions'])
                record['seconds']=round(time.monotonic()-start,2)
            except Exception as error:record['error']=type(error).__name__+': '+str(error)
            with Session() as s:
                traces=[json.loads(r.trace) for r in s.scalars(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at))]
            (folder/f'{name}-traces.json').write_text(json.dumps(traces,ensure_ascii=False,indent=2),'utf-8')
            case['turns'].append(record);print(json.dumps({'case':name,'turn':i+1,**record},ensure_ascii=False),flush=True)
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        case['passed']=all('checks' in r and all(r['checks'].values()) for r in case['turns'])
        if name=='buying_context':
            case['proactive_question_used']=any(r.get('adopted',{}).get('question') for r in case['turns'])
            case['passed']=case['passed'] and case['proactive_question_used']
    report['passed']=all(c['passed'] for c in report['cases'])
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8');print('RESULT '+str(report['passed']),flush=True)
    return report['passed']

if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--live',action='store_true');parser.add_argument('--case',choices=['all',*CASES],default='all');args=parser.parse_args()
    if not args.live:parser.error('Use --live for configured text-model calls; isolated database only')
    sys.stdout.reconfigure(encoding='utf-8');sys.exit(0 if asyncio.run(run(CASES if args.case=='all' else [args.case])) else 1)
