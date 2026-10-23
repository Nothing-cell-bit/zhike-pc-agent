import asyncio
import json
from backend import dialogue
from backend.db import Session,Conversation,DialogueState,PriceRule
from backend.service_tasks import observe_delivery
from backend.service_workflow import focus_sources
from .test_service_workflow import turn,service_protocol
from .test_reply_choices import seed
from .test_reception_plan import pending_state
from .test_dialogue_workflow import add
from .test_quote_engine import rule
from .conftest import post


def test_question_punctuation_does_not_import_an_unrelated_negation_into_price_evidence():
    from backend.requirements import _grounded
    assert _grounded('这台具体配置和价格大概多少？','它处理Excel会不会卡顿？另外这台具体配置和价格大概多少？','dialogue')
    assert not _grounded('能运行这个软件','这台不一定能运行这个软件。','dialogue')


def test_relative_price_claim_needs_actual_priced_options(clients):
    from backend.service_workflow import validate_choices
    _,_,state=seed(clients)
    candidates=[{'label':'配置选择','answer':'这台机器i5和i9两个配置价差挺大。','question':None,'citations':[]}]
    errors=validate_choices(candidates,state,[],{'sources':[]},group_complete=False)
    assert any('价格' in error for error in errors)


def test_information_reply_does_not_append_internal_sale_option_rows():
    from backend.service_workflow import quote_suffix
    state={'goal':'recommend','options':[{'id':'old-record','name':'电脑','variant':'原官网商品ID','budget_fit':'unknown'}]}
    assert quote_suffix(state,{'kind':'inform','option_ids':['old-record']})==''


def test_retrieval_covers_each_requested_property_for_each_product():
    sources=[]
    for pid in ['p1','p2']:
        for i in range(12):sources.append({'id':pid+str(i),'product_id':pid,'title':'产品来源与包装','excerpt':'型号甲 型号乙 包装清单 访问官网 产品介绍'})
        for facet,body in [('weight','## 尺寸与重量\n\n重量\n\n约 980 g'),('resolution','## 屏幕\n\n分辨率\n\n3120 × 2080'),('gamut','## 屏幕\n\n100% sRGB 色域')]:
            sources.append({'id':pid+facet,'product_id':pid,'title':'事实','excerpt':body})
    selected=focus_sources({'sources':sources},'型号甲与型号乙的重量、分辨率、色域是多少？')['sources']
    assert {p+f for p in ['p1','p2'] for f in ['weight','resolution','gamut']}<={s['id'] for s in selected}


def test_delivery_uses_current_complete_fact_pool_not_only_prompt_snippets():
    from backend.service_delivery import build_deliverable
    pool=[{'id':'cpu','product_id':'p','title':'处理器','excerpt':'## 处理器\n\ni7'}]
    result=build_deliverable('answer',['p'],['processor'],{'sources':[],'source_pool':pool},[{'id':'p','name':'机型'}],1)
    assert result['complete'] and 'i7' in result['text']


def test_processor_does_not_take_a_graphics_footnote_and_screen_fields_stay_separate():
    from backend.service_delivery import facet_excerpt
    assert not facet_excerpt({'excerpt':'## 显卡\n\n集成显卡\n\n*部分处理器版本搭载UHD显卡。'},'processor')
    screen={'excerpt':'## 屏幕\n\n分辨率\n\n3120 × 2080\n\n色域\n\nWindows 版：Adobe RGB / P3 / sRGB\n\nLinux 版：P3\n\n色准\n\n平均△E < 1'}
    assert facet_excerpt(screen,'resolution')=='3120 × 2080'
    gamut=facet_excerpt(screen,'gamut')
    assert 'Windows 版' in gamut and 'Linux 版' in gamut and '色准' not in gamut


def test_windows_screen_mode_is_not_an_operating_system_value():
    from backend.service_delivery import facet_excerpt
    assert not facet_excerpt({'excerpt':'## 屏幕\n\n刷新率\n\nWindows 版：120 Hz*'},'os')
    assert 'Windows 11' in facet_excerpt({'excerpt':'## 操作系统\n\nWindows 11 家庭版\n\nLinux V20 版'},'os')


def test_available_price_is_not_reported_missing_when_budget_is_not_a_hard_limit():
    from backend.service_workflow import quote_suffix
    options=[{'id':'a','name':'设备','variant':'配置'}]
    state={'goal':'recommend','needs':{'budget':{'value':'预算大约2万元'}},'options':options}
    dialogue.verified_budget_fit(state,options,[{'option_id':'a','state':'ready_for_review','total_minor':1599900}])
    assert options[0]['price_verified'] and options[0]['budget_fit']=='unknown'
    assert '售价和预算匹配仍待核实' not in quote_suffix(state,{'option_ids':['a']})


def test_recommendation_does_not_redeliver_the_same_parameter_table():
    from backend.service_delivery import build_turn_deliverable
    tools={'sources':[{'id':'w','product_id':'p','excerpt':'## 重量\n\n980 g'}]}
    catalog=[{'id':'p','name':'机型'}]
    first=build_turn_deliverable('recommend',['p'],['weight'],tools,catalog,1,{})
    first['sent_message_id']='sent'
    state={'deliverables':[first]}
    assert build_turn_deliverable('recommend',['p'],['weight'],tools,catalog,3,state) is None
    assert build_turn_deliverable('compare',['p'],['weight'],tools,catalog,3,state)


def test_default_recommendation_and_discovery_do_not_append_internal_specs():
    from backend.service_delivery import public_deliverable
    delivery={'facets':['processor','memory'],'product_ids':['p'],'cells':[], 'text':'internal table'}
    task={'key':'recommend','kind':'recommend','required_facets':['processor','memory'],'product_ids':['p']}
    assert public_deliverable(delivery,[task],['recommend'],'recommend') is None
    task['kind']='compare'
    assert public_deliverable(delivery,[task],['recommend'],'ask') is None


def test_explicit_single_fact_is_plain_customer_text_without_debug_markup():
    from backend.service_delivery import public_deliverable
    delivery={'id':'d','kind':'inform','facets':['weight'],'product_ids':['p'],'cells':[{'product_id':'p','facet':'weight','quote':'约 980 g\n\n*实际重量依配置不同可能有所差异。','status':'sourced'}],
              'text':'| 机型 | 重量（资料原文） |','complete':True}
    task={'key':'answer','kind':'answer','required_facets':['weight'],'product_ids':['p']}
    result=public_deliverable(delivery,[task],['answer'],'inform')
    assert '980 g' in result['text'] and '依配置' in result['text']
    assert '<br>' not in result['text'] and '|' not in result['text'] and '资料原文' not in result['text']


def test_regenerating_old_reply_context_rebuilds_instead_of_reusing_debug_suffix(clients,monkeypatch):
    from backend import ai
    from backend.service_workflow import run,WORKFLOW_VERSION
    cid,_,_=seed(clients)
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='Wording':raise AssertionError('旧版缓存应重新分析，不能沿用调试附表换话术')
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        return turn(data['current_turn']),{}
    protocol=service_protocol(model)
    asyncio.run(run(cid,protocol))
    with Session() as session:
        row=session.get(DialogueState,cid);state=json.loads(row.state)
        state['workflow_version']=WORKFLOW_VERSION-1
        state['reply_context']['suffix']='\n\n| 机型 | 内存（资料原文） |\n| --- | --- |\n| 机型 | 16GB<br> |'
        row.state=json.dumps(state);session.commit()
    monkeypatch.setattr(ai,'model_json',protocol)
    result=asyncio.run(ai.suggestions(cid,{}))
    assert '资料原文' not in result['dialogue']['action']['reply']


def test_names_alone_do_not_complete_a_parameter_comparison():
    state={'tasks':[{'id':'task','key':'compare','kind':'compare','status':'ready','required_facets':['weight','resolution'],
                     'product_ids':['p1','p2'],'depends_on':[]}], 'needs':{},'questions':[],
           'presentations':[{'message_id':'sent','option_ids':['one','two']}]}
    action={'task_ids':['task'],'option_ids':['one','two'],'reply':'两款机型如下'}
    observe_delivery(state,action,'两款机型如下','sent',2)
    assert state['tasks'][0]['status']!='completed'


def test_followup_confirmation_is_not_a_new_delivery_obligation(clients):
    from backend.service_workflow import run
    cid,staff,_=pending_state(clients)
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'结果核实后由客服回复。','client_id':'existing-arrangement'}).json()
    add(cid,'customer','好的，核实清楚后再告诉我')
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__
        result=turn(data['current_turn']);result.update(tasks=[],unresolved=[])
        result['needs']['changes']=[{'field':'agreed_followup','operation':'confirm','fact':{'status':'known','quotes':[{'message_id':data['current_turn']['id'],'quote':data['current_turn']['text'],'kind':'context'}]}}]
        result['plan'].update(customer_act='acknowledge',acknowledged_message_id=sent['id'])
        if name in {'ServiceDraft','RefillDraft'}:raise AssertionError('确认已有约定不应重写承诺')
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['action']['kind']=='wait' and state['action']['candidates']==[]


def test_conditional_price_request_creates_independent_quote_work(clients,monkeypatch):
    from backend.service_workflow import run
    cid,staff,_=seed(clients)
    pid=dialogue.catalog_index()[0]['id'];option={'id':'sale','product_id':pid,'name':'设备','variant':'明确配置','sku_verified':True,'source_ids':[],'price':None}
    async def options(ids):return {'options':[option],'sources':[],'warnings':[]}
    monkeypatch.setattr(dialogue,'load_options',options)
    with Session() as s:
        s.add(PriceRule(product_id=pid,variant_id='sale',author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule(unit_minor=500000,configuration_label='演示32GB完整配置'))))
        s.add(PriceRule(product_id=pid,variant_id='sale',author_id='author',status='draft',payload=json.dumps(rule(level='L4'))));s.commit()
    add(cid,'customer','如果性能合适，这款是什么价位？')
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__
        if name=='ServiceCustomerUpdate':return {'changes':[],'requests':[{'kind':'quote','subject':'该配置的价格','facets':[],
            'evidence':{'message_id':data['current_turn']['id'],'quote':data['current_turn']['text']}}]},{}
        if name=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[])
        result['plan']['topic']={'subject':'性能与价格','request':data['current_turn']['text'],'product_ids':[pid],'evidence':result['plan']['customer_evidence']}
        # The planner once returned a product ID where a sale-option ID was required.
        result['plan']['option_ids']=[pid]
        return result,{}
    delegated=service_protocol(model)
    async def actual(*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceCustomerUpdate':return await model(*args,**kwargs)
        return await delegated(*args,**kwargs)
    state=asyncio.run(run(cid,actual))['dialogue']
    assert state['goal']=='quote' and state['quotes'][0]['state']=='ready_for_review',state['tasks']
    assert state['quotes'][0]['variant']=='演示32GB完整配置'
    choice=state['action']['candidates'][0]
    response=post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'independent-price-card'})
    assert response.status_code==200,response.text
    assert len(response.json()['card']['quotes'])==1
    assert response.json()['card']['quotes'][0]['variant']=='演示32GB完整配置'
    after=dialogue.view(cid)
    assert next(q for q in after['quotes'] if q['level']=='L1')['delivery_status']=='sent'
    assert next(q for q in after['quotes'] if q['level']=='L4').get('delivery_status')!='sent'


def test_unmatched_authorized_configuration_is_not_quoted_as_requested(clients,monkeypatch):
    from backend.service_workflow import run
    cid,_,_=seed(clients);pid=dialogue.catalog_index()[0]['id']
    option={'id':'sale7','product_id':pid,'name':'设备','variant':'目录版本','sku_verified':True,'source_ids':[],'price':None}
    async def options(ids):return {'options':[option],'sources':[],'warnings':[]}
    monkeypatch.setattr(dialogue,'load_options',options)
    with Session() as s:
        s.add(PriceRule(product_id=pid,variant_id='sale7',author_id='author',approved_by='reviewer',status='approved',
                       payload=json.dumps(rule(configuration_label='Ultra 7 / 32GB'))));s.commit()
    add(cid,'customer','我要Ultra 9、32GB版本的价格')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[])
        result['plan'].update(goal='quote',action='quote',option_ids=['sale7'])
        result['plan']['topic']={'subject':'指定配置价格','request':data['current_turn']['text'],'product_ids':[pid],'evidence':result['plan']['customer_evidence']}
        return result,{}
    delegated=service_protocol(model)
    async def actual(*args,**kwargs):
        if kwargs['schema'].__name__=='SaleOptionSelection':return {'option_ids':[],'reason':'授权的是Ultra 7，客户要Ultra 9'},{}
        return await delegated(*args,**kwargs)
    state=asyncio.run(run(cid,actual))['dialogue']
    assert state['quotes']==[] and state['action']['kind']=='inform'
    assert any(t['kind']=='verify' and t['title']=='核实客户指定销售配置及其价格' for t in state['tasks'])


def test_comparison_delivers_parameters_and_only_then_completes(clients,monkeypatch):
    from backend.service_workflow import run
    cid,staff,_=seed(clients);products=dialogue.catalog_index()[:2];pids=[p['id'] for p in products]
    sources=[];options=[]
    for index,product in enumerate(products):
        options.append({'id':'option'+str(index),'product_id':product['id'],'name':product['name'],'variant':'对应版本','source_ids':[],'price':None})
        for facet,text in [('weight','## 尺寸与重量\n\n重量\n\n约 980 g'),('resolution','## 屏幕\n\n分辨率\n\n3120 × 2080'),('gamut','## 屏幕\n\n100% sRGB 色域')]:
            sources.append({'id':product['id']+facet,'product_id':product['id'],'title':'产品事实','excerpt':text})
    async def load(ids):return {'options':options,'sources':sources,'warnings':[]}
    monkeypatch.setattr(dialogue,'load_options',load)
    add(cid,'customer','帮我对比这两款的重量、分辨率和色域')
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__
        if name=='ServiceCustomerUpdate':return {'changes':[],'requests':[{'kind':'compare','subject':'两款参数对比','facets':['weight','resolution','gamut'],'evidence':{'message_id':data['current_turn']['id'],'quote':data['current_turn']['text']}}]},{}
        if name=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[])
        result['plan']['topic']={'subject':'对比','request':data['current_turn']['text'],'product_ids':pids,'evidence':result['plan']['customer_evidence']}
        return result,{}
    delegate=service_protocol(model)
    async def actual(*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceCustomerUpdate':return await model(*args,**kwargs)
        return await delegate(*args,**kwargs)
    state=asyncio.run(run(cid,actual))['dialogue'];choice=state['action']['candidates'][0]
    assert '980 g' in choice['reply'] and '3120 × 2080' in choice['reply'] and '100% sRGB' in choice['reply']
    task=next(t for t in state['tasks'] if t.get('canonical_request'))
    assert task['status']=='ready'
    assert post(staff,f'/conversations/{cid}/messages',{'content':choice['reply'],'action_id':choice['id'],'client_id':'deliver-comparison'}).status_code==200
    saved=dialogue.view(cid);assert next(t for t in saved['tasks'] if t['id']==task['id'])['status']=='completed'
    assert saved['deliverables'][-1]['sent_message_id']
