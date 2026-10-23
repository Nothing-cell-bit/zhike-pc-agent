"""Configured model, isolated DB, actual adopted replies and per-call timing."""
import argparse,asyncio,hashlib,json,sys,time,uuid
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from scripts.evaluate_natural_dialogue import ROOT,ai,append,Session,Conversation
from backend.db import DialogueRun
from sqlalchemy import select


async def evaluate(only_case=None):
    folder=ROOT/'tmp'/'service-workflow'/(time.strftime('%Y%m%d-%H%M%S')+'-'+uuid.uuid4().hex[:6]);folder.mkdir(parents=True)
    print('ARTIFACT '+str(folder),flush=True)
    original_completion=ai.completion
    async def measured_completion(settings,payload,*args,**kwargs):
        start=time.perf_counter()
        print('HTTP '+json.dumps({'max_tokens':payload['max_tokens'],'input_chars':sum(len(m['content']) for m in payload['messages']),
                                'disable_thinking':settings.disable_thinking}),flush=True)
        response=await original_completion(settings,payload,*args,**kwargs)
        print('HTTP_RETURN '+str(response.status_code)+' '+str(round(time.perf_counter()-start,2)),flush=True)
        return response
    ai.completion=measured_completion
    report={'scope':only_case or 'all','cases':[],'calls':[],'passed':False};original=ai.model_json
    report['source_hashes']={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest() for name in
        ['backend/service_workflow.py','backend/service_tasks.py','backend/dialogue.py','backend/ai.py','backend/main.py']}
    from backend import llm_trace
    original_record=llm_trace.record
    def record_raw(content,model,schema,usage):
        original_record(content,model,schema,usage)
        name=getattr(schema,'__name__','json')
        (folder/('raw-'+str(time.time_ns())+'-'+name+'.json')).write_text(content,'utf8')
        print('RAW '+name+' '+json.dumps(usage),flush=True)
    llm_trace.record=record_raw
    async def measured(*args,**kwargs):
        start=time.perf_counter();name=kwargs['schema'].__name__;print('CALL '+name,flush=True)
        try:
            output,usage=await original(*args,**kwargs)
            record={'schema':name,'seconds':round(time.perf_counter()-start,2),'usage':usage,'output':output}
            report['calls'].append(record);(folder/'calls.json').write_text(json.dumps(report['calls'],ensure_ascii=False,indent=2),'utf8')
            print('RETURN '+name+' '+str(record['seconds']),flush=True)
            return output,usage
        except Exception as e:print('ERROR '+name+' '+str(e),flush=True);raise
    ai.model_json=measured
    def create(name):
        with Session() as s:
            c=Conversation(customer_id='synthetic',customer_name='服务主线验收 '+name,owner_id='synthetic');s.add(c);s.commit();cid=c.id
        case={'name':name,'cid':cid,'turns':[]};report['cases'].append(case);return case
    async def turn(case,text,allowed=(),question=False,send=True,advance=False,regenerate=False):
        append(case['cid'],'customer',text);start=time.perf_counter();call_start=len(report['calls'])
        result=await ai.analysis(case['cid']);state=result['dialogue'];choices=state['action'].get('candidates',[])
        known={k:v['value'] for k,v in state['needs'].items() if isinstance(v,dict) and v.get('status')!='unknown'}
        checks={'three_choices':len(choices)==3,'no_field_pollution':set(known)<=set(allowed),
                'plain_choice':state['action']['kind']=='ask' or any(not c.get('question') for c in choices),
                'no_duplicate_question':all(not c.get('question') or c['reply'].count(c['question']['text'])==1 for c in choices),
                'tasks_present':bool(state.get('tasks'))}
        new_manual_work=any(t['kind']=='verify' and t['status']=='waiting_staff' and t.get('product_ids') and t.get('created_seq')==state['message_seq'] for t in state.get('tasks',[]))
        if advance:checks['advances_without_ok']=any(c.get('question') for c in choices) or state['action']['kind'] in {'recommend','compare','quote'} or new_manual_work
        from backend.dialogue import question_key,messages_for
        with Session() as s:current_messages=messages_for(s,case['cid'])
        checks['answered_fields_synchronized']=not any(q.get('status')=='asked' and q.get('scope','field')=='field'
            and any(m['message_id'] in {x['id'] for x in current_messages if x['seq']>q.get('seq',0)}
                    for m in state['needs'].get(question_key(q),{}).get('quotes',[])) for q in state['questions'])
        record={'customer':text,'seconds':round(time.perf_counter()-start,2),'calls':len(report['calls'])-call_start,
                'mission':state.get('mission'),'topic':state.get('topic'),'continuation':state.get('continuation'),
                'needs':known,'tasks':state.get('tasks'),'candidates':choices,'checks':checks,'new_manual_work':new_manual_work}
        case['turns'].append(record)
        with Session() as s:
            trace=s.scalar(select(DialogueRun).where(DialogueRun.conversation_id==case['cid']).order_by(DialogueRun.created_at.desc()).limit(1))
            (folder/f'{case["name"]}-{len(case["turns"])}.json').write_text(trace.trace,'utf8')
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        print(json.dumps({'case':case['name'],**record},ensure_ascii=False),flush=True)
        if not all(checks.values()):raise AssertionError(checks)
        if regenerate:
            import copy
            before={k:copy.deepcopy(state.get(k)) for k in ['needs','tasks','questions','mission','selection','quotes']}
            regenerated=await ai.suggestions(case['cid'],{})
            state=regenerated['dialogue'];choices=state['action']['candidates']
            assert len(choices)==3 and all(state.get(k)==v for k,v in before.items())
            assert {c['reply'] for c in choices}!={c['reply'] for c in record['candidates']}
            record['regenerated_candidates']=choices
        if send:
            chosen=next((c for c in choices if question and c.get('question')),choices[0]);append(case['cid'],'staff',chosen['reply'],chosen['id']);record['sent']=chosen['reply']
        return state
    try:
        if only_case in (None,'intro_progression'):
            for name in ['MateBook D 16 2024','MateBook 14 酷睿 Ultra']:
                case=create('intro_progression_'+name)
                await turn(case,'我想了解 HUAWEI '+name+'，能介绍一下吗？')
                await turn(case,'ok',question=True,advance=True,regenerate=True)
                state=await turn(case,'主要处理文档、看网课，预算6000元以内。',('tasks','budget'),question=True,advance=True)
                assert state['needs']['tasks']['status'] in {'known','partial'}
                assert '6000' in state['needs']['budget']['value']
                assert not any(c.get('question') and c['question']['scope']=='field' and c['question']['target'] in {'usage_tasks','purchase_budget'} for c in state['action']['candidates'])
        if only_case in (None,'continuous_service'):
            case=create('continuous_service')
            await turn(case,'想给自己换台电脑。我是计算机专业的学生，主要写程序。',('progress','user','tasks'),question=True,advance=True,regenerate=True)
            state=await turn(case,'预算一万以内，平常用Codex，同时开十个左右的任务窗口，不跑虚拟机。',('progress','user','tasks','software','budget'),question=True,advance=True)
            assert state['needs']['user']['status']=='known','明确的学生身份丢失'
            assert '十个' in state['needs']['tasks']['value'] and '不跑虚拟机' in state['needs']['tasks']['value'],'并行数量或负载限制丢失'
            state=await turn(case,'经常背去学校，轻一点就行，配置你帮我选。',('progress','user','tasks','software','budget','concerns'),advance=True,regenerate=True)
            selected=next((o for o in state['options'] if o['id'] in state['action']['option_ids']),None)
            assert selected,'委托配置后没有实际候选'
            await turn(case,'先看'+selected['name']+'，它有几个USB接口？',('progress','user','tasks','software','budget','concerns'))
            await turn(case,'就这台，帮我核对一下实际价格。',('progress','user','tasks','software','budget','concerns'),advance=True)
        if only_case in (None,'focused_information'):
            case=create('focused_information')
            state=await turn(case,'只想查MateBook D 16 2024有几个USB接口，先不用了解我的用途和预算。')
            assert not any(c.get('question') for c in state['action']['candidates'])
            await turn(case,'换成MateBook D 14 2024呢？',regenerate=True)
            state=await turn(case,'资料够了，今天先不聊了。')
            assert not any(c.get('question') for c in state['action']['candidates'])
        if only_case in (None,'memory_to_needs'):
            case=create('memory_to_needs')
            await turn(case,'先只说MateBook GT 14的内存，能比32GB更大吗？')
            state=await turn(case,'明白了',question=True)
            assert state['continuation']['mode']!='close'
            assert any(c.get('question') for c in state['action']['candidates']), '确认收到后没有有价值的下一步'
            await turn(case,'我做设计，主要剪辑视频，必用单位的栖云工具，预算8000元。',('user','tasks','software','budget'))
            await turn(case,'这个软件只有Windows版，先帮我核实能不能用，别重复问预算。',('user','tasks','software','budget','concerns'))
        if only_case in (None,'ports_and_switch'):
            case=create('ports_and_switch')
            await turn(case,'我想了解MateBook D 16 2024，USB-C有几个？')
            await turn(case,'这个口能给电脑充电吗？')
            await turn(case,'那MateBook D 14 2024呢？也是问充电接口')
        if only_case in (None,'selection_and_quote'):
            case=create('selection_and_quote')
            await turn(case,'我要给自己换台电脑，预算不超过9000元，主要写代码和做文档。',('progress','budget','tasks'))
            await turn(case,'需要用单位自研的蓝桥桌面，只有Windows安装包。配置你按用途选。',('progress','budget','tasks','software'))
            await turn(case,'就按你推荐的配置，帮我核对价格。',('progress','budget','tasks','software'))
        report['passed']=True
    except Exception as e:report['error']=type(e).__name__+': '+str(e);print(report['error'],flush=True)
    finally:
        report['db_folder']=str(__import__('backend.config',fromlist=['DATA']).DATA)
        report['actual_model_responses']=len(list(folder.glob('raw-*.json')))
        (folder/'report.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),'utf8')
        print('RESULT '+str(report['passed']),flush=True)
    return report['passed']


if __name__=='__main__':
    p=argparse.ArgumentParser();p.add_argument('--live',action='store_true');p.add_argument('--case',choices=['memory_to_needs','ports_and_switch','selection_and_quote','continuous_service','focused_information','intro_progression']);args=p.parse_args()
    if not args.live:p.error('Use --live to use the configured text model in an isolated database')
    sys.stdout.reconfigure(encoding='utf8');sys.exit(0 if asyncio.run(evaluate(args.case)) else 1)
