import asyncio
import copy
import json
import pytest

from backend import dialogue
from backend.db import Session, Conversation, DialogueState
from .test_reply_choices import seed, q
from .test_dialogue_workflow import add
from .conftest import post
from .test_workflow import guest


def clean_audit():return {'errors':[],'invalid_need_fields':[]},{}


def progress_result(question=None,reason='该测试夹具明确没有额外独立信息请求'):
    return {'reason':reason,'next_question':question,'paths':[
        {'area':area,'status':'useful' if index==0 and question else 'not_relevant','reason':reason,
         'question':question if index==0 else None}
        for index,area in enumerate(['verification_scope','decision_criteria','decision_path'])]}


def turn(message):
    return {'plan':{'topic':None,'acknowledged_message_id':None,'conversation_scope':None,'customer_act':'request_information','customer_evidence':{'message_id':message['id'],'quote':message['text']},
        'goal':'information','action':'inform','continuation':{'mode':'answer','reason':'先处理当前问题'}},
        'needs':{'changes':[]},'unresolved':[{'key':'memory_check','title':'核实更大内存版本'}],'tasks':[],
        'candidates':[{'label':label,'answer':answer,'question':None,'citations':[]} for label,answer in
                      [('直接回答','更大内存版本还需要核实。'),('简要说明','我这边还需要确认是否有更大内存版本。'),('回应','更大容量的版本，目前还没有确认。')]]}


def service_protocol(model):
    """Use shared scenario data to answer the two explicit production roles."""
    async def wrapped(*args,**kwargs):
        if kwargs['schema'].__name__=='SaleOptionSelection':return {'option_ids':[o['id'] for o in args[1]['options'][:1]],'reason':'测试场景匹配配置'},{}
        if kwargs['schema'].__name__=='ProgressReview':return progress_result(),{}
        if kwargs['schema'].__name__=='FollowupAdmission':return {'agreed':False,'reason':'测试场景没有客户后续约定'},{}
        if kwargs['schema'].__name__=='ScopeAdmission':return {'explicit_restriction':True},{}
        result,usage=await model(*args,**kwargs)
        name=kwargs['schema'].__name__
        if name=='ServiceCustomerUpdate':
            return {**copy.deepcopy(result.get('needs',{})),'resolutions':copy.deepcopy(result.get('plan',{}).get('resolutions',[]))},usage
        if name=='ServiceAudit' and 'reviews' not in result:
            result['reviews']=[{'index':c['index'],'grounded':c['index'] not in result.get('invalid_candidates',[]),'responsive':True,'reason':'测试场景已校验'}
                               for c in args[1]['candidates']]
        if name=='ServicePlanning':
            from backend.service_workflow import ServicePlanning
            return {k:v for k,v in result.items() if k in ServicePlanning.model_fields},usage
        if name in {'ServiceDraft','RefillDraft'}:
            from backend.service_workflow import ServiceDraft
            extracted={k:v for k,v in result.items() if k in ServiceDraft.model_fields}

            if name=='ServiceDraft':extracted.setdefault('option_ids',result.get('plan',{}).get('option_ids',[]))
            else:extracted={k:v for k,v in extracted.items() if k in {'candidates','unresolved'}}
            extracted['candidates']=extracted['candidates'][:args[1].get('output_count',3)]
            for candidate in extracted.get('candidates',[]):candidate.setdefault('question',None)
            return extracted,usage
        return result,usage
    return wrapped


def test_single_decision_persists_real_task_without_guessing_fields(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);calls=[]
    async def model(instruction,data,*args,**kwargs):

        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        calls.append(data);return turn(data['current_turn']),{'prompt_tokens':100,'completion_tokens':60}
    result=asyncio.run(run(cid,service_protocol(model)));state=result['dialogue']
    assert len(calls)==3 and len(state['action']['candidates'])==3
    assert next(t for t in state['tasks'] if t['kind']=='verify')['status']=='waiting_staff'
    assert next(t for t in state['tasks'] if t['kind']=='verify')['completion']=='门店登记核实结果'
    assert state['needs']['user']['status']=='unknown' and state['needs']['software']['status']=='unknown'
    assert dialogue.view(cid)['tasks']==state['tasks']


def test_verified_result_is_audited_and_stale_draft_cannot_send(clients):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        return turn(data['current_turn']),{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue'];task=next(t for t in state['tasks'] if t['kind']=='verify')
    response=post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',
                  {'revision':state['revision'],'status':'completed','result':'已向门店确认：当前没有其他在售内存版本。'})
    assert response.status_code==200
    saved=dialogue.view(cid);done=next(t for t in saved['tasks'] if t['kind']=='verify')
    assert done['status']=='completed' and done['completed_by']
    assert saved['action']['kind']=='review'
    assert post(staff,f'/conversations/{cid}/messages',{'content':state['action']['candidates'][0]['reply'],
        'action_id':state['action']['candidates'][0]['id'],'client_id':'obsolete-choice'}).status_code==409
    assert post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',
        {'revision':state['revision'],'status':'completed','result':'覆盖'}).status_code==409


def test_task_wait_does_not_prevent_other_next_step_and_drafts_do_not_complete_tasks(clients):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn'])
        result['plan']['continuation']={'mode':'bridge','reason':'核实由门店处理，仍可了解实际用途','next_information':'实际用途'}
        result['tasks'].append({'key':'usage_tasks','kind':'discover','title':'了解使用场景','target':'usage_tasks','evidence':result['plan']['customer_evidence']});result['active_task_keys']=['usage_tasks']
        result['candidates'][1]['question']=q()
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert {t['status'] for t in state['tasks']}=={'waiting_staff','ready'}
    assert not state['questions']
    choice=state['action']['candidates'][1]
    assert post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'usage-choice'}).status_code==200
    saved=dialogue.view(cid)
    assert len(saved['questions'])==1 and next(t for t in saved['tasks'] if t['kind']=='discover')['status']=='waiting_customer'
    assert next(t for t in saved['tasks'] if t['kind']=='verify')['status']=='waiting_staff'


def test_stale_inference_cannot_overwrite_task_result(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        add(cid,'customer','再看看屏幕')
        return turn(data['current_turn']),{}
    result=asyncio.run(run(cid,service_protocol(model)))
    assert result['stale'] and not dialogue.view(cid).get('tasks')


def test_regenerate_preserves_mission_tasks_and_uses_one_call(clients):
    from backend.service_workflow import run, regenerate
    cid,_,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        return turn(data['current_turn']),{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue'];calls=[]
    async def wording(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        calls.append(data)
        return {'candidates':[{**c,'answer':'收到，'+c['answer']} for c in turn(data['current_turn'])['candidates']]},{}
    changed=asyncio.run(regenerate(cid,service_protocol(wording)))['dialogue']
    assert len(calls)==1
    for key in ('needs','tasks','mission','topic','quotes','questions'):assert changed.get(key)==state.get(key)


def test_task_completion_requires_real_sent_answer_not_model_assertion(clients):
    from backend.service_tasks import sync_tasks, observe_delivery
    cid,_,state=seed(clients)
    with Session() as s:messages=dialogue.messages_for(s,cid)
    evidence={'message_id':messages[-1]['id'],'quote':messages[-1]['text']}
    proposal={'key':'answer_memory','kind':'answer','title':'回答内存问题','evidence':evidence}
    sync_tasks(state,[proposal],messages,1)
    task=state['tasks'][0]
    assert task['status']=='ready'
    observe_delivery(state,{'task_ids':[task['id']]},'真实答复','sent-message',2)
    assert task['status']=='completed' and task['sent_message_id']=='sent-message'


def test_dependencies_invalid_ids_and_explicit_cancellation(clients):
    from backend.service_tasks import sync_tasks
    cid,_,state=seed(clients)
    with Session() as s:messages=dialogue.messages_for(s,cid)
    ev={'message_id':messages[-1]['id'],'quote':messages[-1]['text']}
    sync_tasks(state,[{'key':'a','kind':'verify','title':'核实配置','evidence':ev},
        {'key':'b','kind':'quote','title':'核价','depends_on':['a'],'evidence':ev}],messages,1)
    assert next(t for t in state['tasks'] if t['key']=='b')['status']=='blocked'
    original=copy.deepcopy(state)
    sync_tasks(state,[{'key':'fake','kind':'verify','title':'无效','evidence':{'message_id':'draft','quote':'虚构'}}],messages,2)
    assert state['tasks']==original['tasks']


def test_source_presence_does_not_prove_generated_conclusion(clients,monkeypatch):
    from backend.service_workflow import run
    from backend import service_workflow as workflow
    cid,_,_=seed(clients);calls=[]
    async def info(_,query='' ):return {'sources':[{'id':'source','title':'产品事实','excerpt':'内存 32 GB'}]}
    monkeypatch.setattr(dialogue,'load_information',info)
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state);state['topic']={'product_ids':[dialogue.catalog_index()[0]['id']]};row.state=json.dumps(state);s.commit()
    async def model(_,data,*args,**kwargs):
        calls.append(kwargs['schema'].__name__)
        if kwargs['schema'].__name__=='ServiceAudit':
            bad=any('不存在' in c['answer'] for c in data['candidates'])
            return {'errors':['原文只列32 GB，不能断定不存在其他版本'] if bad else [],'invalid_need_fields':[]},{}
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn'])
        if sum(n in {'ServiceDraft','RefillDraft'} for n in calls)==1:
            for index,c in enumerate(result['candidates']):c.update(answer=['更大版本不存在。','目前更大版本不存在。','这款更大版本不存在。'][index],citations=[{'source_id':'source','excerpt':'内存 32 GB'}])
        return result,{}
    result=asyncio.run(run(cid,service_protocol(model)))
    assert 'ServiceAudit' in calls
    assert all('不存在' not in c['answer'] for c in result['dialogue']['action']['candidates'])


def test_production_entry_and_profile_audit_keep_budget_drop_query(clients,monkeypatch):
    from backend import ai
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','预算6000元，屏幕多大？');calls=[]
    async def model(_,data,*args,**kwargs):
        calls.append(kwargs['schema'].__name__)
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':['usage_tasks']},{}
        result=turn(data['current_turn'])
        result['needs']['changes']=[{'field':'purchase_budget','operation':'replace','fact':fact(mid,'预算6000元')},
            {'field':'usage_tasks','operation':'replace','fact':fact(mid,'屏幕多大？')}]
        return result,{}
    monkeypatch.setattr(ai,'model_json',service_protocol(model))
    state=asyncio.run(ai.analysis(cid))['dialogue']
    assert calls==['ServiceCustomerUpdate','ServicePlanning','ServiceDraft','ServiceAudit']
    assert '6000' in state['needs']['budget']['value'] and state['needs']['tasks']['status']=='unknown'


def test_manual_locks_and_mission_survive_topic_interruption(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','预算改为9000，先看看屏幕')
    with Session() as s:
        conv=s.get(Conversation,cid);conv.locked=json.dumps({'budget':{'value':'7000元以内','status':'known'}})
        row=s.get(DialogueState,cid);base=json.loads(row.state);base['mission']={'text':'挑选学习电脑','evidence':{'message_id':mid,'quote':'先看看屏幕'}};row.state=json.dumps(base);s.commit()
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['needs']['changes']=[{'field':'purchase_budget','operation':'replace','fact':fact(mid,'预算改为9000')}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['mission']['text']=='挑选学习电脑' and state['needs']['budget']['value']=='7000元以内'
    assert state['conflicts']


def test_full_production_recommend_confirm_quote_send_and_revoke(clients,monkeypatch):
    from backend import ai
    from backend.db import PriceRule
    from .test_quote_engine import rule
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim')
    pid=dialogue.catalog_index()[0]['id'];option={'id':'sale','product_id':pid,'name':'测试设备','variant':'已核实配置','sku_verified':True,'price':None}
    async def load(_):return {'options':[option],'sources':[],'warnings':[]}
    monkeypatch.setattr(dialogue,'load_options',load)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        if kwargs['schema'].__name__=='ServiceCustomerUpdate':return turn(data['current_turn']),{}
        result=turn(data['current_turn']);quote=bool(data['state'].get('presentations'))
        result['tasks']=[{'key':'quote' if quote else 'recommend','kind':'quote' if quote else 'recommend','title':'核对价格' if quote else '推荐方案','evidence':result['plan']['customer_evidence']}]
        result['active_task_keys']=[result['tasks'][0]['key']]
        result['plan'].update(goal='quote' if quote else 'recommend',action='quote' if quote else 'recommend',option_ids=['sale'] if data.get('tools',{}).get('options') else [])
        if quote:result['plan'].update(customer_act='confirm_option',selection={'option_id':'sale','evidence':result['plan']['customer_evidence']})
        for index,c in enumerate(result['candidates']):c.update(answer=['请看这套配置。','这套方案供您确认。','给您整理好了。'][index])
        return result,{}
    monkeypatch.setattr(ai,'model_json',service_protocol(model));add(cid,'customer','帮我推荐配置')
    first=asyncio.run(ai.analysis(cid))['dialogue'];choice=first['action']['candidates'][0]
    assert post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'recommend-delivery'}).status_code==200
    assert dialogue.view(cid)['tasks'][0]['status']=='completed'
    with Session() as s:s.add(PriceRule(id='approved',product_id=pid,variant_id='sale',author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule())));s.commit()
    add(cid,'customer','就这套，报价吧');quoted=asyncio.run(ai.analysis(cid))['dialogue']
    assert quoted['selection']['status']=='confirmed' and quoted['quotes'][0]['total_minor']==800900
    choice=quoted['action']['candidates'][0]
    assert post(staff,f'/conversations/{cid}/messages',{'content':choice['intro'],'action_id':choice['id'],'client_id':'quote-delivery'}).status_code==200
    assert next(t for t in dialogue.view(cid)['tasks'] if t['kind']=='quote')['status']=='completed'
    assert customer.get('/api/conversations/'+cid).json()['messages'][-1]['card']['quotes'][0]['total_minor']==800900
    add(cid,'customer','再报一次');quoted=asyncio.run(ai.analysis(cid))['dialogue'];choice=quoted['action']['candidates'][0]
    with Session() as s:s.get(PriceRule,'approved').status='revoked';s.commit()
    assert post(staff,f'/conversations/{cid}/messages',{'content':choice['intro'],'action_id':choice['id'],'client_id':'revoked-quote-send'}).status_code==409


def test_retrieval_is_bounded_and_cannot_accept_fake_product_ids(clients):
    from backend.service_workflow import run
    import pytest
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        calls.append(data['phase']);result=turn(data['current_turn']);result['retrieve_product_ids']=['not-in-catalog'];return result,{}
    with pytest.raises(ValueError):asyncio.run(run(cid,service_protocol(model)))
    assert calls==['customer_update','service_turn','service_turn','service_turn'] and dialogue.view(cid).get('workflow_version') is None


def test_task_permission_blank_result_and_closed_conversation(clients):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        return turn(data['current_turn']),{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue'];task=next(t for t in state['tasks'] if t['kind']=='verify')
    body={'revision':state['revision'],'status':'completed','result':' '}
    assert post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',body).status_code==400
    body['result']='已核实'
    assert post(clients[2],f'/conversations/{cid}/service-tasks/{task["id"]}',body).status_code==403
    with Session() as s:s.get(Conversation,cid).status='closed';s.commit()
    assert post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',body).status_code==409


def test_task_dependencies_cannot_cycle_or_reuse_another_product(clients):
    from backend.service_tasks import proposal_errors
    _,_,state=seed(clients)
    ev={'message_id':'m','quote':'q'}
    proposals=[{'key':'a','kind':'verify','title':'A','evidence':ev,'depends_on':['b']},
               {'key':'b','kind':'quote','title':'B','evidence':ev,'depends_on':['a']}]
    assert proposal_errors(state,proposals)
    proposals[0]['depends_on']=[];proposals[1]['depends_on']=['missing']
    assert proposal_errors(state,proposals)
    proposals[1]['depends_on']=['a']
    assert not proposal_errors(state,proposals)


def test_prompt_schema_compaction_preserves_types_and_required_fields():
    from backend.ai import prompt_schema
    from backend.service_workflow import ServicePlanning
    schema=prompt_schema(ServicePlanning,compact=True)
    assert schema['required']==ServicePlanning.model_json_schema()['required']
    assert schema['properties']['plan']['$ref']
    assert 'title' not in schema and 'description' not in json.dumps(schema)


def test_retrieval_ranks_arbitrary_topic_without_dropping_source_conditions():
    from backend.service_workflow import focus_sources
    sources=[{'id':str(i),'excerpt':f'## 条目{i}\n普通信息','product_id':'p'} for i in range(30)]
    sources.append({'id':'wanted','excerpt':'## 外设\n专用星轨连接器，只在指定版本支持。','product_id':'p'})
    chosen=focus_sources({'sources':sources},'我问专用星轨连接器')
    assert len(chosen['sources'])<=10
    assert next(s for s in chosen['sources'] if s['id']=='wanted')['excerpt']==sources[-1]['excerpt']


def test_new_hard_budget_filters_recommendation_in_same_turn(clients,monkeypatch):
    import pytest
    from backend.service_workflow import run
    from backend.db import PriceRule
    from .test_quote_engine import rule
    from .test_dialogue_workflow import fact
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim');mid=add(cid,'customer','预算最多6000元，帮我选配置')
    pid=dialogue.catalog_index()[0]['id'];option={'id':'expensive','product_id':pid,'name':'测试设备','variant':'销售款','price':None}
    with Session() as s:s.add(PriceRule(product_id=pid,variant_id='expensive',author_id='a',approved_by='b',status='approved',payload=json.dumps(rule())));s.commit()
    async def load(_):return {'options':[option],'sources':[],'warnings':[]}
    monkeypatch.setattr(dialogue,'load_options',load)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan'].update(goal='recommend',action='recommend',option_ids=['expensive'] if data.get('tools',{}).get('options') else [])
        result['needs']['changes']=[{'field':'purchase_budget','operation':'replace','fact':fact(mid,'预算最多6000元')}]
        return result,{}
    with pytest.raises(ValueError):asyncio.run(run(cid,service_protocol(model)))


def test_staff_verification_resumes_answer_without_new_customer_message(clients):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    async def initial(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        return turn(data['current_turn']),{}
    state=asyncio.run(run(cid,service_protocol(initial)))['dialogue'];choice=state['action']['candidates'][0]
    post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'pending-verification'})
    state=dialogue.view(cid);task=next(t for t in state['tasks'] if t['kind']=='verify')
    assert post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',{'revision':state['revision'],'status':'completed','result':'已核实在售版内存为32GB'}).status_code==200
    async def resumed(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        assert data.get('trigger')=='staff_result'
        customer=next(m for m in data['messages'] if m['role']=='customer');result=turn(customer);result['unresolved']=[]
        if kwargs['schema'].__name__=='ServicePlanning':return result,{}
        source=next(s for s in data['tools']['sources'] if s.get('source_type')=='staff_verified')
        for i,c in enumerate(result['candidates']):c.update(answer=['已核实，是32GB内存。','核实结果回来了，在售版为32GB。','目前在售版确认是32GB。'][i],citations=[{'source_id':source['id'],'excerpt':source['excerpt']}])
        return result,{}
    final=asyncio.run(run(cid,service_protocol(resumed)))['dialogue']
    assert final['action']['kind']=='inform' and len(final['action']['candidates'])==3
    assert not final.get('pending_service_event')


def test_task_planner_has_no_product_prose_and_writer_cannot_change_strategy(clients):
    from backend.service_workflow import run,ServicePlanning,ServiceDraft
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        schema=kwargs['schema'];calls.append(schema.__name__)
        if schema is ServicePlanning:
            assert 'tools' not in data and 'sources' not in data
            result=turn(data['current_turn']);result['plan']['continuation']={'mode':'bridge','reason':'当前问题已交代，了解实际使用以判断是否合适','next_information':'实际使用任务'}
            result['tasks']=[{'key':'usage','kind':'discover','title':'了解实际用途','target':'usage_tasks','evidence':result['plan']['customer_evidence']}];result['active_task_keys']=['usage']
            return {k:v for k,v in result.items() if k in ServicePlanning.model_fields},{}
        if schema is ServiceDraft:
            assert data['state']['continuation']['mode']=='bridge'
            result=turn(data['current_turn']);result['candidates'][1]['question']=q()
            return {k:v for k,v in result.items() if k in ServiceDraft.model_fields},{}
        return clean_audit()
    result=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert calls==['ServiceCustomerUpdate','ServicePlanning','ServiceDraft','ServiceAudit']
    assert result['continuation']['mode']=='bridge' and any(c.get('question') for c in result['action']['candidates'])


def test_empty_audit_is_never_a_pass_and_answer_cannot_hide_verification(clients):
    import pytest
    from pydantic import ValidationError
    from backend.service_workflow import ServiceAudit,run
    with pytest.raises(ValidationError):ServiceAudit.model_validate({})
    cid,_,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['tasks']=[{'key':'memory_check','kind':'answer','title':'回应内存问题','evidence':result['plan']['customer_evidence']}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert {t['kind'] for t in state['tasks']}=={'verify','answer'}


def test_pending_event_survives_failed_generation(clients):
    import pytest
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    async def initial(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        return turn(data['current_turn']),{}
    state=asyncio.run(run(cid,service_protocol(initial)))['dialogue'];task=next(t for t in state['tasks'] if t['kind']=='verify')
    post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',{'revision':state['revision'],'status':'completed','result':'已核实'})
    before=dialogue.view(cid)
    async def failed(*args,**kwargs):raise ValueError('测试暂时不可用')
    with pytest.raises(ValueError):asyncio.run(run(cid,failed))
    assert dialogue.view(cid)['pending_service_events']==before['pending_service_events']


def test_old_scope_cannot_be_resurrected_after_it_was_released(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    with Session() as s:
        row=s.get(DialogueState,cid);base=json.loads(row.state);base.update(workflow_version=2,conversation_scope=None);row.state=json.dumps(base);s.commit()
        previous=dialogue.messages_for(s,cid)[0]
    add(cid,'customer','我是设计师，主要做视频剪辑')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan']['conversation_scope']={'mode':'focused','duration':'conversation','evidence':{'message_id':previous['id'],'quote':previous['text']}}
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state.get('conversation_scope') is None


def test_inform_bridge_question_is_optional_without_an_extra_planner_call(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__;calls.append(name)
        if name=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan']['continuation']={'mode':'bridge','reason':'了解实际使用有助于判断是否适合','next_information':'实际用途'}
        result['tasks']=[{'key':'usage','kind':'discover','title':'了解实际用途','target':'usage_tasks','evidence':result['plan']['customer_evidence']}];result['active_task_keys']=['usage']
        result['plan']['question']=q();result['candidates'][1]['question']=q()
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert calls.count('ServicePlanning')==1 and state['action']['question'] is None
    assert any(c.get('question') for c in state['action']['candidates'])


def test_field_question_cannot_bypass_known_value_by_changing_topic_key(clients):
    _,_,state=seed(clients)
    question=q('purchase_budget','购机预算是多少？');question['topic_key']='another_budget_question'
    action=dialogue.checked_action({'action':'inform','reply':'收到。','question':question},state,{},[])
    assert action['kind']=='review'


def test_requirement_question_does_not_search_entire_product_catalog(clients,monkeypatch):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    async def forbidden(*args,**kwargs):raise AssertionError('澄清需求不应全库选型核价')
    monkeypatch.setattr(dialogue,'load_options',forbidden)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);question=q('required_software','有什么必须运行的软件吗？')
        result['plan'].update(goal='recommend',action='ask',question=question)
        for c in result['candidates']:c['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['action']['kind']=='ask' and not state['options']


def test_inconsistent_optional_bridge_is_limited_before_writing(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__;calls.append(name)
        if name=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan']['continuation']={'mode':'bridge','reason':'探索实际用途','next_information':'实际用途'}
        result['tasks']=[{'key':'usage','kind':'discover','title':'了解实际用途','target':'usage_tasks','evidence':result['plan']['customer_evidence']}];result['active_task_keys']=['usage']
        if name=='ServicePlanning' and calls.count('ServicePlanning')==1:
            result['plan']['conversation_scope']={'mode':'focused','duration':'topic','evidence':result['plan']['customer_evidence']}
        result['candidates'][1]['question']=q()
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert calls.count('ServicePlanning')==1 and sum(n in {'ServiceDraft','RefillDraft'} for n in calls)==1
    assert state['continuation']['mode']=='answer'
    assert all(not c.get('question') for c in state['action']['candidates'])


def test_bridge_requires_customer_information_not_store_verification(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    with Session() as s:s.get(Conversation,cid).locked=json.dumps({'budget':{'status':'known','value':'7000元以内'}});s.commit()
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        if kwargs['schema'].__name__ in {'ServiceDraft','RefillDraft'}:
            assert data['state']['continuation']['mode']=='answer'
            return turn(data['current_turn']),{}
        result=turn(data['current_turn']);result['plan']['continuation']={'mode':'bridge','reason':'确认门店价','next_information':'是否有预算内在售配置'}
        result['tasks']=[{'key':'store_price','kind':'discover','target':'purchase_budget','title':'核实门店在售价格','evidence':result['plan']['customer_evidence']}]
        result['active_task_keys']=['store_price'];return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['continuation']['mode']=='answer' and len(state['action']['candidates'])==3
    assert all(not c.get('question') for c in state['action']['candidates'])


def test_discovery_domain_is_customer_fields_and_detail_does_not_auto_complete(clients):
    import pytest
    from pydantic import ValidationError
    from backend.service_workflow import ServicePlanning
    from backend.service_tasks import sync_tasks
    cid,_,state=seed(clients)
    with Session() as s:messages=dialogue.messages_for(s,cid)
    result=turn(messages[-1]);result['tasks']=[{'key':'compat','kind':'discover','title':'核实兼容性','target':'产品是否兼容','evidence':result['plan']['customer_evidence']}]
    with pytest.raises(ValidationError):ServicePlanning.model_validate({k:v for k,v in result.items() if k in ServicePlanning.model_fields})
    task={'key':'budget_detail','kind':'discover','title':'了解预算是否包含外设','target':'purchase_budget','scope':'detail','topic_key':'budget_includes_peripherals','evidence':result['plan']['customer_evidence']}
    sync_tasks(state,[task],messages,1)
    assert state['tasks'][0]['status']=='ready'


def test_answer_delivery_has_a_task_even_when_model_omits_optional_tasks(clients):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['unresolved']=[];return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert any(t['kind']=='answer' for t in state['tasks'])
    choice=state['action']['candidates'][0]
    post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'answer-task-send'})
    assert next(t for t in dialogue.view(cid)['tasks'] if t['kind']=='answer')['status']=='completed'


def test_receipt_exploration_preserves_verified_sources_for_wording(clients,monkeypatch):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'该参数还需要核实。','client_id':'receipt-original-answer'}).json()
    add(cid,'customer','了解了')
    async def info(_,query='' ):return {'sources':[{'id':'source','excerpt':'32 GB'}]}
    monkeypatch.setattr(dialogue,'load_information',info)
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state);state['topic']={'product_ids':[dialogue.catalog_index()[0]['id']]};row.state=json.dumps(state);s.commit()
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan'].update(customer_act='acknowledge',acknowledged_message_id=sent['id'],
            continuation={'mode':'bridge','reason':'了解实际用途有助于判断是否适合','next_information':'实际用途'})
        result['tasks']=[{'key':'usage','kind':'discover','title':'了解用途','target':'usage_tasks','evidence':result['plan']['customer_evidence']}];result['active_task_keys']=['usage']
        result['candidates'][1]['question']=q()
        if kwargs['schema'].__name__ in {'ServiceDraft','RefillDraft'}:assert data['tools']['sources'][0]['excerpt']=='32 GB'
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['continuation']['mode']=='bridge'


def test_unplanned_optional_question_does_not_discard_good_answers(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        calls.append(kwargs['schema'].__name__)
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['candidates'][1]['question']=q()
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert sum(n in {'ServiceDraft','RefillDraft'} for n in calls)==1 and all(not c.get('question') for c in state['action']['candidates'])


def test_commercial_evidence_is_atomic_and_balanced_across_products():
    from backend.service_workflow import commercial_evidence
    tools={'sources':[{'id':'a','product_id':'a','title':'产品事实','excerpt':'# 甲\n\n## 系统\n\n系统甲\n\n*仅限指定版本。\n\n## 内存\n\n32 GB'},
                      {'id':'b','product_id':'b','title':'产品事实','excerpt':'# 乙\n\n## 系统\n\n系统乙\n\n## 内存\n\n16 GB'}]}
    result=commercial_evidence(tools,'比较系统')
    assert {s['product_id'] for s in result['sources']}=={'a','b'}
    system=next(s for s in result['sources'] if s['product_id']=='a' and '系统甲' in s['excerpt'])
    assert '仅限指定版本' in system['excerpt'] and '32 GB' not in system['excerpt']


def test_purchase_action_is_not_customer_identity_and_intent_veto_is_applied(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','我要给自己换台电脑，预算9000元')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['needs'].update(changes=[{'field':'customer_identity','operation':'replace','fact':fact(mid,'我要给自己换台电脑')},
            {'field':'purchase_budget','operation':'replace','fact':fact(mid,'预算9000元')}],purchase_intent={'mode':'replace','evidence':{'message_id':mid,'quote':'我要给自己换台电脑'}})
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['needs']['user']['status']=='unknown' and state['needs']['progress']['intent_mode']=='replace'
    mid=add(cid,'customer','可以先说下价格吗？')
    async def pricing(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':['purchase_intent']},{}
        result=turn(data['current_turn']);result['needs']['purchase_intent']={'mode':'new','evidence':{'message_id':mid,'quote':'可以先说下价格吗？'}};return result,{}
    state=asyncio.run(run(cid,service_protocol(pricing)))['dialogue']
    assert state['needs']['progress']['intent_mode']=='replace'


def test_current_service_delegation_is_not_an_agreed_followup(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','配置你按用途选，预算9000元')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);ev={'message_id':mid,'quote':'配置你按用途选'}
        result['plan'].update(customer_act='request_recommendation',customer_evidence=ev,delegation=ev)
        result['needs']['changes']=[{'field':'agreed_followup','operation':'replace','fact':fact(mid,'配置你按用途选')}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['needs']['next_step']['status']=='unknown' and state['delegation']


def test_replayed_old_need_cannot_overwrite_newer_customer_fact(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);old=add(cid,'customer','预算8000元');new=add(cid,'customer','预算改为9000元')
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state);messages=dialogue.messages_for(s,cid)
        state.update(workflow_version=2,message_seq=s.get(Conversation,cid).seq)
        state['needs']=dialogue.fact_view(dialogue.build_requirements({'budget':fact(new,'预算改为9000元')},messages));row.state=json.dumps(state);s.commit()
    add(cid,'customer','继续')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['needs']['changes']=[{'field':'purchase_budget','operation':'replace','fact':fact(old,'预算8000元')}];return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert '9000' in state['needs']['budget']['value']


def test_waiting_business_task_still_gets_response_to_new_customer_turn(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    async def initial(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        return turn(data['current_turn']),{}
    first=asyncio.run(run(cid,service_protocol(initial)))['dialogue'];pending=next(t for t in first['tasks'] if t['kind']=='verify')
    add(cid,'customer','这个先帮我核实一下')
    async def waiting(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan']['action']='wait';result['unresolved']=[]
        result['tasks']=[{'key':pending['key'],'kind':'answer','title':pending['title'],'product_ids':pending['product_ids'],'evidence':result['plan']['customer_evidence']}]
        result['active_task_keys']=[pending['key']];return result,{}
    state=asyncio.run(run(cid,service_protocol(waiting)))['dialogue']
    assert state['action']['kind']=='inform' and len(state['action']['candidates'])==3
    assert next(t for t in state['tasks'] if t['id']==pending['id'])['status']=='waiting_staff'


def test_updated_quote_data_resumes_without_another_customer_message(clients,monkeypatch):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    post(staff,f'/conversations/{cid}/messages',{'content':'价格还需要核对。','client_id':'quote-wait-response'})
    option={'id':'sale','product_id':dialogue.catalog_index()[0]['id'],'name':'设备甲','variant':'销售款'}
    old={'option_id':'sale','level':'L1','state':'needs_price','total_minor':None,'quantity':1}
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state);state.update(workflow_version=2,goal='quote',options=[option],quotes=[old],selection={'status':'confirmed','option_id':'sale'});row.state=json.dumps(state);s.commit()
    new={**old,'state':'ready_for_review','total_minor':800900,'rule_id':'new-price-rule'}
    monkeypatch.setattr(dialogue,'prepare_quotes',lambda *args,**kwargs:[new])
    async def options(*args,**kwargs):return {'options':[option],'sources':[]}
    monkeypatch.setattr(dialogue,'load_options',options)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        assert data['trigger']=='staff_result'
        result=turn(data['current_turn']);result['plan'].update(goal='quote',action='quote',option_ids=['sale']);result['unresolved']=[];return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['action']['kind']=='quote' and len(state['action']['candidates'])==3
    assert state['quotes'][0]['total_minor']==800900


def test_model_may_reference_verification_but_cannot_complete_it(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['tasks']=[{'key':'memory_check','kind':'verify','title':'核实内存版本','evidence':result['plan']['customer_evidence'],
            'status':'completed','completed_by':'model','result':'已经确认'}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    tasks=[t for t in state['tasks'] if t['kind']=='verify']
    assert len(tasks)==1 and tasks[0]['status']=='waiting_staff'
    assert not tasks[0].get('completed_by') and not tasks[0]['result']


def test_selection_can_propose_unknown_customer_context_after_retrieval(clients,monkeypatch):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    async def options(*args,**kwargs):return {'options':[],'sources':[]}
    monkeypatch.setattr(dialogue,'load_options',options)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan']['goal']='recommend'
        result['candidates'][1]['question']=q('required_software','您主要用什么开发工具？')
        result['candidates'][1]['answer']='我先按用途筛选。您使用的开发环境是哪一种？'
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['continuation']['mode']=='bridge'
    choice=next(candidate for candidate in state['action']['candidates'] if candidate.get('question'))
    assert choice['question'] and choice['reply'].count('？')==1
    assert any(t['kind']=='discover' and t['target']=='required_software' for t in state['tasks'])


@pytest.mark.parametrize('claim',['此功能不支持离线运行。','这款不兼容环境乙。','没有容量更大的版本。','全系都是该配置。','它不是输入接口。','只能对外供电。'])
def test_positive_evidence_cannot_prove_exclusion_or_absence(claim):
    from backend.service_workflow import strong_assertion_errors
    candidates=[{'answer':claim,'citations':[{'source_id':'s','excerpt':'支持环境甲；容量16 GB；具备数据接口。'}]}]
    assert strong_assertion_errors(candidates,{'needs':{}},{'sources':[{'id':'s','excerpt':'支持环境甲；容量16 GB；具备数据接口。'}]})


@pytest.mark.parametrize('text',['现有资料没有列出其他版本，需要再核实。','这项能力我还不能确认。','该功能不支持离线运行。','没有查到明确说法。','我没有看到相关测试结论。','这份材料没有写能否使用外接设备。'])
def test_unknownness_and_explicit_negative_source_remain_usable(text):
    from backend.service_workflow import strong_assertion_errors
    quote='此功能不支持离线运行。'
    assert not strong_assertion_errors([{'answer':text,'citations':[{'source_id':'s','excerpt':quote}]}],{'needs':{}},{'sources':[{'id':'s','excerpt':quote}]})


def test_valid_candidates_are_available_without_waiting_to_fill_three(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);drafts=[]
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn'])
        if kwargs['schema'].__name__ in {'ServiceDraft','RefillDraft'}:
            drafts.append(data.get('output_count'))
            if len(drafts)==1:result['candidates'][0]['answer']='没有更大版本。'
            else:
                assert data['output_count']==1
                assert 'tools' not in data and 'catalog' not in data
                result['candidates']=[{'label':'补充答复','answer':'大容量版本是否在售，我还需要确认。','question':None,'citations':[]}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert drafts==[3] and len(state['action']['candidates'])==2
    assert state['action']['candidates'][0]['answer']=='我这边还需要确认是否有更大内存版本。'


def test_auditor_uses_actual_turn_not_planner_inferred_request():
    from backend.service_workflow import audit
    messages=[{'id':'m','role':'customer','text':'主要剪视频，预算8000元。'}]
    async def model(_,data,*args,**kwargs):
        assert data['current_turn']==messages[-1]
        assert 'plan' not in data
        assert 'topic' not in data.get('plan',{})
        assert 'customer_act' not in data.get('plan',{})
        return clean_audit()
    asyncio.run(audit(model,{'candidates':[],'plan':{'topic':{'request':'证明内存足够'},'customer_act':'request_information'}},messages,{'sources':[]}))


def test_duplicate_candidate_cannot_inflate_the_available_count():
    from backend.service_workflow import retain_candidates
    candidate={'answer':'更大的内存配置还要确认。','question':None,'citations':[]}
    accepted=[candidate];errors=[]
    retain_candidates(accepted,[candidate],errors,{'invalid_candidates':[]})
    assert len(accepted)==1 and any('重复' in error for error in errors)


def test_all_auditor_vetoes_never_save_an_unreviewed_batch(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':
            return {'errors':[],'invalid_need_fields':[],'invalid_candidates':list(range(len(data['candidates'])))},{}
        return turn(data['current_turn']),{}
    with pytest.raises(ValueError):asyncio.run(run(cid,service_protocol(model)))


def test_optional_bridge_cannot_force_replanning_when_customer_is_focused(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);ev=result['plan']['customer_evidence']
        if kwargs['schema'].__name__=='ServicePlanning':
            calls.append(1)
            result['plan']['conversation_scope']={'mode':'focused','duration':'conversation','evidence':ev}
            result['plan']['continuation']={'mode':'bridge','reason':'探索其他用途','next_information':'用途'}
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert len(calls)==1 and state['continuation']['mode']=='answer'


def test_partial_customer_answer_completes_field_discovery_without_resolution():
    from backend.service_tasks import refresh_tasks
    state={'needs':{'software':{'status':'partial','value':'内部工具，版本待补充'}},
           'tasks':[{'key':'apps','kind':'discover','target':'required_software','status':'ready'}]}
    refresh_tasks(state)
    assert state['tasks'][0]['status']=='completed'
    assert state['tasks'][0]['result']=='内部工具，版本待补充'


def test_audit_requires_individual_grounding_and_relevance_verdicts():
    from backend.service_workflow import audit
    result={'candidates':[{'answer':'该配置能满足所有负载。','citations':[]}]}
    async def empty(*args,**kwargs):return clean_audit()
    verdict,_=asyncio.run(audit(empty,result,[],{'sources':[]}))
    assert verdict['invalid_candidates']==[0] and verdict['errors']
    async def explicit(*args,**kwargs):
        return {'errors':[],'invalid_need_fields':[],'reviews':[{'index':0,'grounded':False,'responsive':True,'reason':'资料仅列配置，未证明负载表现'}]},{}
    verdict,_=asyncio.run(audit(explicit,result,[],{'sources':[]}))
    assert verdict['invalid_candidates']==[0] and '负载' in verdict['errors'][0]


def test_ordinary_answer_cannot_become_a_communication_restriction(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);add(cid,'customer','我用工具乙')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn'])
        result['plan']['conversation_scope']={'mode':'focused','duration':'topic','evidence':result['plan']['customer_evidence']}
        return result,{}
    wrapped=service_protocol(model)
    async def admission(*args,**kwargs):
        if kwargs['schema'].__name__=='ScopeAdmission':return {'explicit_restriction':False},{}
        return await wrapped(*args,**kwargs)
    state=asyncio.run(run(cid,admission))['dialogue']
    assert (state.get('conversation_scope') or {}).get('mode')!='focused'


def test_recommendation_with_unpriced_options_discloses_budget_uncertainty():
    from backend.service_workflow import quote_suffix
    state={'goal':'recommend','options':[{'id':'a','name':'设备甲','variant':'版本乙','budget_fit':'unknown'}]}
    assert '实际售价和预算匹配仍待核实' in quote_suffix(state,{'option_ids':['a']})
