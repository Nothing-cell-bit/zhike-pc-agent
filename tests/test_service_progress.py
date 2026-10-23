import asyncio
import copy
import json

from backend.db import Session,DialogueState
from backend import dialogue
from .test_service_workflow import service_protocol,turn,clean_audit
from .test_reply_choices import seed,q
from .test_dialogue_workflow import add
import pytest


def test_receipt_cannot_silently_accept_a_session_ending_plan(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);staff_id=add(cid,'staff','已介绍基础规格。');add(cid,'customer','收到')
    attempts=[]
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn'])
        result['plan'].update(customer_act='acknowledge',acknowledged_message_id=staff_id)
        if kwargs['schema'].__name__=='ServicePlanning':attempts.append(1)
        if len(attempts)==1:
            result['plan']['continuation']={'mode':'close','reason':'介绍完成所以结束'}
        else:
            question=q();result['next_question']=question;result['candidates'][1]['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert len(attempts)==2
    assert state['continuation']['mode']=='bridge'


@pytest.mark.parametrize('customer_act,text',[('acknowledge','明白了'),('provide_information','主要做设计')])
def test_next_question_is_compiled_before_continuation_validation(clients,customer_act,text):
    from backend.service_workflow import run
    cid,_,_=seed(clients);staff_id=add(cid,'staff','产品基础资料已介绍。');add(cid,'customer',text)
    plans=[]
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);question=q('purchase_budget','这次大概准备多少预算？')
        result['plan'].update(customer_act=customer_act,acknowledged_message_id=staff_id,
            continuation={'mode':'bridge','reason':'已回应上一项，现在需要预算帮助判断选择范围'})
        result['next_question']=question;result['tasks']=[];result['active_task_keys']=[]
        result['candidates'][1]['question']=question
        if kwargs['schema'].__name__=='ServicePlanning':plans.append(1)
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert len(plans)==1
    assert state['continuation']['mode']=='bridge'
    assert state['continuation']['next_information']==state['planned_question']['missing_information']
    assert any(c.get('question') for c in state['action']['candidates'])
    assert any(t['kind']=='discover' and t['target']=='purchase_budget' and t['status']=='ready' for t in state['tasks'])


def test_grounded_budget_answer_resolves_question_and_task_together():
    from backend.service_state import synchronize_progress
    messages=[{'id':'ask','role':'staff','text':'预算大概多少？','seq':1},
              {'id':'answer','role':'customer','text':'8000以内','seq':2}]
    state={'needs':{'budget':{'status':'known','value':'8000以内','quotes':[{'message_id':'answer','quote':'8000以内','kind':'fact'}]}},
           'questions':[{'id':'ask','seq':1,'scope':'field','target':'购机预算','topic_key':'budget','status':'asked'}],
           'tasks':[{'key':'budget','kind':'discover','target':'purchase_budget','scope':'field','status':'waiting_customer'}]}
    synchronize_progress(state,messages)
    assert state['questions'][0]['status']=='answered'
    assert state['questions'][0]['answer']['message_id']=='answer'
    assert state['tasks'][0]['status']=='completed'


def test_detail_answer_retains_question_context_instead_of_bare_number():
    from backend.service_state import synchronize_progress
    messages=[{'id':'ask','role':'staff','text':'同时处理几个项目？','seq':2},
              {'id':'answer','role':'customer','text':'10个','seq':3}]
    state={'needs':{'tasks':{'status':'partial','value':'写代码；10个','quotes':[
               {'message_id':'intro','quote':'写代码','kind':'fact'},{'message_id':'answer','quote':'10个','kind':'fact'}]}},
           'questions':[{'id':'ask','seq':2,'text':'同时处理几个项目？','scope':'detail','target':'并行项目数量',
              'topic_key':'parallel_projects','status':'answered','answer':{'message_id':'answer','quote':'10个'}}],
           'tasks':[{'key':'parallel','kind':'discover','target':'usage_tasks','scope':'detail','topic_key':'parallel_projects','status':'waiting_customer'}]}
    synchronize_progress(state,messages)
    assert state['needs']['tasks']['value']=='写代码；并行项目数量：10个'
    synchronize_progress(state,messages)
    assert state['needs']['tasks']['value']=='写代码；并行项目数量：10个'
    assert state['tasks'][0]['status']=='completed'


def test_manual_value_and_declined_question_are_not_overwritten():
    from backend.service_state import synchronize_progress
    state={'needs':{'budget':{'manual':True,'status':'known','value':'5000','quotes':[]}},
           'questions':[{'id':'ask','seq':1,'scope':'field','target':'purchase_budget','status':'declined'}],'tasks':[]}
    before=copy.deepcopy(state)
    synchronize_progress(state,[])
    assert state==before


def test_next_question_compiles_task_without_waiting_for_an_acknowledgement(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);add(cid,'customer','我在学校做设计')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn'])
        question=q('purchase_budget','这次准备投入多少预算？')
        result['next_question']=question
        result['plan'].update(customer_act='provide_information')
        result['tasks']=[];result['active_task_keys']=[]
        result['candidates'][1]['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['continuation']['mode']=='bridge'
    assert any(c.get('question') for c in state['action']['candidates'])
    assert any(t['kind']=='discover' and t['target']=='purchase_budget' for t in state['tasks'])


def test_regenerate_handles_echoed_questions_and_preserves_business_state(clients):
    from backend.service_workflow import run,regenerate
    cid,_,_=seed(clients)
    async def initial(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);question=q()
        result['next_question']=question;result['candidates'][1]['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(initial)))['dialogue']
    async def wording(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        question=q();question['text']='您主要拿来做什么工作？'
        return {'candidates':[{'label':str(i),'answer':text,'question':question if i else None,'citations':[]}
                for i,text in enumerate(['这项还要确认一下。','收到。'+question['text'],'了解了。'+question['text']])]},{}
    result=asyncio.run(regenerate(cid,service_protocol(wording)))['dialogue']
    assert len(result['action']['candidates'])==3
    assert all(c['reply'].count('？')<=1 for c in result['action']['candidates'])
    for key in ('needs','tasks','questions','selection','quotes','mission'):
        assert result.get(key)==state.get(key)
    assert result['action']['reply']==result['action']['candidates'][0]['reply']


def test_blocking_next_question_has_one_source_of_truth(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);calls=[]
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn'])
        if kwargs['schema'].__name__=='ServicePlanning':calls.append(1)
        question=q('purchase_budget','预算大概多少？')
        result['next_question']=question;result['plan']['action']='ask'
        result['plan']['continuation']={'mode':'bridge','reason':'需要预算才能缩小范围','next_information':'预算'}
        for c in result['candidates']:c['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert len(calls)==1 and state['action']['kind']=='ask'
    assert state['action']['question']['target']=='purchase_budget'


def test_rejected_fact_cannot_complete_discovery_work(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);ask=add(cid,'staff','主要做什么？');mid=add(cid,'customer','屏幕多大？')
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state)
        state['questions']=[{'id':ask,'seq':2,'target':'usage_tasks','scope':'field','status':'asked'}]
        state['tasks']=[{'id':'usage','key':'usage','kind':'discover','target':'usage_tasks','scope':'field','status':'waiting_customer'}]
        row.state=json.dumps(state);s.commit()
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':['usage_tasks']},{}
        result=turn(data['current_turn'])
        result['needs']['changes']=[{'field':'usage_tasks','operation':'replace','fact':fact(mid,'屏幕多大？')}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['needs']['tasks']['status']=='unknown'
    assert next(t for t in state['tasks'] if t['key']=='usage')['status']=='waiting_customer'
    assert state['questions'][0]['status']=='asked'


def test_distinct_clauses_preserve_identity_activity_and_software(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','我是学生，主要画图，用工具甲，同时开三个项目。')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn'])
        result['needs']['changes']=[
            {'field':'customer_identity','operation':'add','fact':fact(mid,'我是学生')},
            {'field':'usage_tasks','operation':'add','fact':fact(mid,'我是学生，主要画图，用工具甲，同时开三个项目。')},
            {'field':'required_software','operation':'add','fact':fact(mid,'用工具甲')}]
        return result,{}
    needs=asyncio.run(run(cid,service_protocol(model)))['dialogue']['needs']
    assert needs['user']['value']=='学生'
    assert needs['tasks']['value']=='主要画图；同时开三个项目'
    assert needs['software']['value']=='用工具甲'


def test_planner_does_not_reuse_previous_generated_strategy_as_customer_intent(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state)
        state['topic']={'subject':'产品外观','request':'接下来应继续问外观','product_ids':[]}
        state['continuation']={'mode':'bridge','reason':'猜客户关心外观','next_information':'外观'}
        state['planned_question']=q('purchase_concerns','还要聊外观吗？')
        row.state=json.dumps(state);s.commit()
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        if kwargs['schema'].__name__=='ServicePlanning':
            assert 'continuation' not in data['state']
            assert 'planned_question' not in data['state']
            assert 'request' not in (data['state'].get('topic') or {})
        return turn(data['current_turn']),{}
    asyncio.run(run(cid,service_protocol(model)))


def test_partial_refill_is_not_judged_as_a_complete_three_choice_group(clients):
    from backend.service_workflow import validate_choices
    cid,_,state=seed(clients)
    state['action']={'kind':'inform'};state['continuation']={'mode':'bridge'}
    with Session() as s:messages=dialogue.messages_for(s,cid)
    candidates=[{'label':'确认','answer':'已记录您的需求。','question':None,'citations':[]}]
    assert not validate_choices(candidates,state,messages,{'sources':[]},group_complete=False)


def test_auditor_sees_program_rendered_options():
    from backend.service_workflow import audit
    async def model(_,data,*args,**kwargs):
        assert '设备甲，配置乙' in data['visible_candidates'][0]['text']
        return {'errors':[],'invalid_need_fields':[],'reviews':[{'index':0,'grounded':True,'responsive':True,'reason':'推荐列表由程序展示'}]},{}
    result={'candidates':[{'answer':'可以先比较这些候选。','question':None,'citations':[]}],'display_suffix':'\n\n设备甲，配置乙'}
    asyncio.run(audit(model,result,[],{'sources':[]}))


def test_derived_quantity_reaches_semantic_review_but_unverified_money_does_not():
    from backend.service_workflow import validate_choices
    state={'action':{'kind':'inform'},'continuation':{'mode':'answer'},'needs':{},'questions':[],'quotes':[]}
    messages=[]
    excerpt='插槽甲×1，插槽乙×2'
    context={'sources':[{'id':'spec','excerpt':excerpt}]}
    candidate={'label':'数量','answer':'共3个插槽。','question':None,'citations':[{'source_id':'spec','excerpt':excerpt}]}
    assert not validate_choices([candidate],state,messages,context)
    candidate['answer']='售价9999元。'
    assert validate_choices([candidate],state,messages,context)


def test_auditor_can_ground_against_retrieved_evidence_and_correct_citation():
    from backend.service_workflow import audit
    sources=[{'id':'memory','excerpt':'设备甲内存16GB。'},{'id':'system','excerpt':'设备甲运行系统乙。'}]
    result={'candidates':[{'answer':'设备甲运行系统乙。','question':None,'citations':[{'source_id':'memory','excerpt':sources[0]['excerpt']}]}]}
    async def model(_,data,*args,**kwargs):
        assert {s['id'] for s in data['sources']}=={'memory','system'}
        return {'errors':[],'invalid_need_fields':[],'reviews':[{'index':0,'grounded':True,'responsive':True,'reason':'系统来源支持','source_ids':['system']}]},{}
    verdict,_=asyncio.run(audit(model,result,[],{'sources':sources}))
    assert not verdict['errors']
    assert result['candidates'][0]['citations']==[{'source_id':'system','excerpt':'设备甲运行系统乙。'}]


def test_grounded_flag_cannot_admit_inferred_application_capability():
    from backend.service_workflow import audit
    result={'candidates':[{'answer':'这个配置运行工具甲没问题。','question':None,'citations':[]}]}
    async def model(_,data,*args,**kwargs):
        return {'errors':[],'invalid_need_fields':[],'reviews':[{'index':0,'grounded':True,'responsive':True,'reason':'参数推断',
            'source_ids':['spec'],'capability_claims':[{'claim':'运行工具甲没问题','relation':'inferred','source_id':'spec','quote':'内存16GB。'}]}]},{}
    verdict,_=asyncio.run(audit(model,result,[],{'sources':[{'id':'spec','excerpt':'内存16GB。'}]}))
    assert verdict['invalid_candidates']==[0]
    assert any('没有直接原文依据' in e for e in verdict['errors'])


def test_reviewed_direct_negative_meaning_is_not_rejected_for_different_wording():
    from backend.service_workflow import audit,strong_assertion_errors
    candidates=[{'answer':'设备甲没有功能乙。','question':None,'citations':[]}]
    sources=[{'id':'spec','excerpt':'设备甲不支持功能乙。'}]
    async def model(_,data,*args,**kwargs):
        return {'errors':[],'invalid_need_fields':[],'reviews':[{'index':0,'grounded':True,'responsive':True,'reason':'同义否定',
            'source_ids':['spec'],'categorical_claims':[{'claim':'设备甲没有功能乙','relation':'direct','source_id':'spec','quote':'设备甲不支持功能乙。'}]}]},{}
    verdict,_=asyncio.run(audit(model,{'candidates':candidates},[],{'sources':sources}))
    assert not verdict['errors']
    assert not strong_assertion_errors(candidates,{'needs':{}},{'sources':sources})


def test_stating_an_unknown_capability_does_not_require_proving_a_negative():
    from backend.service_workflow import audit,strong_assertion_errors
    text='本轮资料没有给出工具甲的运行数据，具体表现还需核实。'
    candidates=[{'answer':text,'question':None,'citations':[]}]
    async def model(_,data,*args,**kwargs):
        claim={'claim':'没有给出工具甲的运行数据','stance':'unknown','relation':'inferred','source_id':None,'quote':''}
        return {'errors':[],'invalid_need_fields':[],'reviews':[{'index':0,'grounded':True,'responsive':True,'reason':'保留未知',
            'source_ids':[],'capability_claims':[claim],'categorical_claims':[claim]}]},{}
    verdict,_=asyncio.run(audit(model,{'candidates':candidates},[],{'sources':[]}))
    assert not verdict['errors'] and not strong_assertion_errors(candidates,{'needs':{}},{'sources':[]})


@pytest.mark.parametrize('rename',[True,False])
def test_reply_cannot_rename_planned_question_and_disconnect_its_task(clients,rename):
    from backend.service_workflow import run
    from .conftest import post
    cid,staff,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);planned=q('usage_tasks','通常同时开几个项目？')
        planned.update(scope='detail',topic_key='parallel_projects')
        result['next_question']=planned
        result['candidates'][1]['question']={**planned,'topic_key':'renamed_by_writer' if rename else planned['topic_key'],'text':'这次预算是多少？'}
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    choice=next(candidate for candidate in state['action']['candidates'] if candidate.get('question'))
    assert choice['question']['topic_key']=='parallel_projects'
    assert choice['question']['text']=='通常同时开几个项目？'
    response=post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'canonical-question'})
    assert response.status_code==200
    task=next(t for t in dialogue.view(cid)['tasks'] if t['kind']=='discover')
    assert task['status']=='waiting_customer'


def test_missing_option_ids_cannot_silently_downgrade_recommendation(clients,monkeypatch):
    from backend.service_workflow import run
    cid,_,_=seed(clients);pid=dialogue.catalog_index()[0]['id'];calls=[]
    async def options(*args):return {'options':[{'id':'pick','product_id':pid,'name':'设备甲','variant':'版本乙'}],'sources':[]}
    monkeypatch.setattr(dialogue,'load_options',options)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan'].update(goal='recommend',action='recommend')
        result['retrieve_product_ids']=[pid]
        if kwargs['schema'].__name__=='ServiceDraft':
            calls.append(1);result['option_ids']=[] if len(calls)==1 else ['pick']
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert len(calls)==2
    assert state['action']['kind']=='recommend' and state['action']['option_ids']==['pick']


def test_new_budget_for_known_product_creates_real_followthrough(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','预算6000元以内，主要看网课')
    pid=dialogue.catalog_index()[0]['id']
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);ev={'message_id':mid,'quote':'预算6000元以内，主要看网课'}
        result['plan'].update(customer_act='provide_information',topic={'subject':'判断是否合适','request':'按用途和预算判断产品','product_ids':[pid],'evidence':ev})
        result['needs']['changes']=[{'field':'purchase_budget','operation':'add','fact':fact(mid,'预算6000元以内')}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    work=[t for t in state['tasks'] if t.get('target')=='purchase_budget']
    assert len(work)==1 and work[0]['status']=='waiting_staff' and work[0]['product_ids']==[pid]
    assert all('销售配置与预算匹配仍待核实' in c['reply'] for c in state['action']['candidates'])


def test_expanding_sources_does_not_consume_the_refill_budget(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);drafts=[];audits=[]
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__
        if name=='ServiceAudit':
            audits.append(1)
            if len(audits)==1:return {'errors':['本批没有依据'],'invalid_need_fields':[],'invalid_candidates':[0,1,2]},{}
            return clean_audit()
        result=turn(data['current_turn'])
        if name in {'ServiceDraft','RefillDraft'}:
            drafts.append(1)
            if len(drafts)==1:result['broaden_sources']=True
            elif len(drafts)==3:result['candidates'][0]['answer']='没有其他配置。'
            elif len(drafts)==4:result['candidates']=[{'label':'核实','answer':'销售版本信息还要再确认一下。','question':None,'citations':[]}]
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert len(drafts)==3 and len(audits)==2
    assert len(state['action']['candidates'])==2
    assert all('没有其他配置' not in candidate['answer'] for candidate in state['action']['candidates'])


def test_information_followup_can_discover_customer_workload_after_retrieval(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients);add(cid,'customer','做三维建模，用工具甲')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        result=turn(data['current_turn']);result['plan']['customer_act']='provide_information'
        question=q('usage_tasks','项目主要有多复杂？');question.update(scope='detail',topic_key='project_scale')
        result['candidates'][1]['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['continuation']['mode']=='bridge'
    assert next(candidate for candidate in state['action']['candidates'] if candidate.get('question'))['question']['topic_key']=='project_scale'


def test_canonical_customer_update_separates_facts_and_resolves_compound_answer(clients):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);ask=add(cid,'staff','具体做哪类设计，用什么软件？');mid=add(cid,'customer','三维建模，用栖云工坊')
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state)
        state['questions']=[{'id':ask,'seq':2,'text':'具体做哪类设计，用什么软件？','scope':'detail','topic_key':'design_detail','target':'usage_tasks','status':'asked'}]
        row.state=json.dumps(state);s.commit()
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return clean_audit()
        if kwargs['schema'].__name__=='ServicePlanning':
            assert any(v.get('value')=='三维建模' for v in data['state']['needs'].values())
            assert any(v.get('value')=='用栖云工坊' for v in data['state']['needs'].values())
            assert data['state']['questions'][0]['status']=='answered'
        result=turn(data['current_turn']);result['plan']['customer_act']='provide_information'
        result['needs']['changes']=[{'field':'usage_tasks','operation':'add','fact':fact(mid,'三维建模，用栖云工坊')}]
        return result,{}
    wrapped=service_protocol(model);updates=[]
    async def canonical(*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceCustomerUpdate':
            updates.append(1)
            return {'changes':[{'field':'usage_tasks','operation':'add','fact':fact(mid,'三维建模')},
                               {'field':'required_software','operation':'add','fact':fact(mid,'用栖云工坊')}],
                    'resolutions':[{'question_id':ask,'status':'answered','evidence':{'message_id':mid,'quote':'三维建模，用栖云工坊'}}]},{}
        return await wrapped(*args,**kwargs)
    state=asyncio.run(run(cid,canonical))['dialogue']
    assert len(updates)==1
    assert state['needs']['tasks']['value']=='三维建模' and state['needs']['software']['value']=='用栖云工坊'
    assert state['questions'][0]['status']=='answered'


@pytest.mark.parametrize('invalid',[False,True])
def test_rejected_replies_do_not_discard_reviewed_customer_facts(clients,invalid):
    from backend.service_workflow import run
    from .test_dialogue_workflow import fact
    cid,_,_=seed(clients);mid=add(cid,'customer','预算8000以内')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':
            return {'errors':['本批产品主张无依据'],'invalid_need_fields':['purchase_budget'] if invalid else [],'invalid_candidates':[0,1,2]},{}
        result=turn(data['current_turn'])
        result['plan']['customer_act']='provide_information'
        result['needs']['changes']=[{'field':'purchase_budget','operation':'add','fact':fact(mid,'预算8000以内')}]
        return result,{}
    with pytest.raises(ValueError):asyncio.run(run(cid,service_protocol(model)))
    with Session() as s:state=json.loads(s.get(DialogueState,cid).state)
    assert state['needs']['budget']['status']=='unknown' if invalid else state['needs']['budget']['value']=='8000以内'
    assert state['reply_generation_failed']
    assert state['action']['kind']=='review' and state['action']['candidates']==[]
