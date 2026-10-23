"""Real-model, isolated natural conversations; retain every turn for human review."""
import argparse,asyncio,json,os,sys,tempfile,time,uuid
from datetime import datetime
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
os.environ['STORE_DATA_DIR']=tempfile.mkdtemp(prefix='dialogue-natural-')
from backend import ai,dialogue_catalog,knowledge as kb
from backend.db import init_db,Session,Conversation,Message,DialogueRun
from backend.dialogue import observe_sent
from backend.model_settings import ModelConfig
from sqlalchemy import select
kb.INDEX=ROOT/'data'/'knowledge'/'index.db';dialogue_catalog.CACHE_ROOT=ROOT/'data'/'ima'
# Use the site's configured model without copying credentials into test artifacts.
override=ROOT/'data'/'private'/'text-model.json'
if override.exists():
    private=json.loads(override.read_text('utf-8'))
    configured=ModelConfig(private['base_url'],private['model'],private['api_key'],'custom',private.get('disable_thinking',False))
    ai.get_config=lambda:configured
init_db()

CASES={
 'gt_topic':[
  ('我想了解 HUAWEI MateBook GT 14，能介绍一下吗？',[]),
  ('内存',[]),('就内存啊',[]),('这个能自己加吗？',[]),('好，知道了，谢谢',[])],
 'ports_switch':[
  ('MateBook D 16 2024有几个USB接口？',[]),('我问的是C口',[]),
  ('这个口能给电脑充电吗？',[]),('那MateBook D 14 2024呢？同样问这个接口',[])],
 'screen_context':[
  ('MateBook X Pro 酷睿 Ultra 微绒典藏版，屏幕多大？',[]),
  ('刷新率呢？',[]),('默认就是最高刷新率吗？',[]),('不用推荐配置，我只了解屏幕',[])],
 'personal_vs_query':[
  ('MateBook 14鸿蒙版能运行Windows的exe软件吗？',[]),
  ('我需要用单位自研的曜石终端，只有exe安装包。', ['software']),
  ('那换成MateBook 14酷睿Ultra呢？',['software']),
  ('预算最多8000元，暂时不报价，先确认兼容性。',['software','budget'])]
}

def append(cid,role,text,action_id=''):
    with Session() as s:
        conv=s.get(Conversation,cid);conv.seq+=1
        message=Message(conversation_id=cid,sender_id='synthetic-'+role,role=role,content=text,seq=conv.seq,client_id=cid+'-'+str(conv.seq))
        s.add(message);s.flush()
        if role=='staff':observe_sent(s,conv,message,action_id)
        s.commit()

async def run(case_name):
    folder=ROOT/'tmp'/'dialogue-natural'/(datetime.now().strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:8]);folder.mkdir(parents=True)
    report={'isolated_database':os.environ['STORE_DATA_DIR'],'cases':[],'passed':False}
    print('ARTIFACT '+str(folder),flush=True)
    for name in CASES if case_name=='all' else [case_name]:
        with Session() as s:
            conv=Conversation(customer_id='synthetic-customer',customer_name='自然对话验收（隔离）',owner_id='synthetic-staff');s.add(conv);s.commit();cid=conv.id
        case={'name':name,'conversation_id':cid,'turns':[]};report['cases'].append(case)
        for number,(text,allowed_fields) in enumerate(CASES[name],1):
            append(cid,'customer',text);start=time.monotonic()
            try:
                result=await ai.analysis(cid);state=result['dialogue'];action=state['action']
                with Session() as s:
                    last=s.scalar(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at.desc()).limit(1));trace=json.loads(last.trace)
                needs={key:value['value'] for key,value in state['needs'].items() if isinstance(value,dict) and value.get('status')!='unknown'}
                checks={'no_review_dead_end':action['kind']!='review' and bool(action['reply']),
                        'no_unrequested_question':not action.get('question'),
                        'no_profile_pollution':set(needs)<=set(allowed_fields),
                        'no_pricing_tools':'quote_checks' not in trace.get('tools',{}),
                        'no_quote_artifact':not state['quotes']}
                if 'software' in allowed_fields:checks['software_retained']='曜石终端' in needs.get('software','')
                if 'budget' in allowed_fields:checks['budget_recorded']='8000' in needs.get('budget','')
                record={'customer':text,'reply':action['reply'],'kind':action['kind'],'question':action.get('question'),
                        'topic':state.get('topic'),'needs':needs,'checks':checks,'seconds':round(time.monotonic()-start,2),
                        'calls':len(trace.get('model_responses',[])),'reviews':trace.get('reviews'),'errors':trace.get('response_validation_errors')}
                case['turns'].append(record)
                (folder/f'{name}-{number}-trace.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),'utf-8')
                print(json.dumps({'case':name,'turn':number,**record},ensure_ascii=False),flush=True)
                if action['reply']:append(cid,'staff',action['reply'],action['id'])
            except Exception as error:
                case['turns'].append({'customer':text,'error':type(error).__name__+': '+str(error)});print('ERROR '+name+' '+type(error).__name__,flush=True)
            (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
        case['passed']=all('checks' in t and all(t['checks'].values()) for t in case['turns'])
    report['passed']=all(c['passed'] for c in report['cases'])
    (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf-8')
    print('RESULT '+str(report['passed']),flush=True)
    return report['passed']

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--case',choices=['all',*CASES],default='all');args=parser.parse_args()
    if not args.live:parser.error('Use --live to authorize real text-model calls in an isolated database')
    sys.stdout.reconfigure(encoding='utf-8');sys.exit(0 if asyncio.run(run(args.case)) else 1)
