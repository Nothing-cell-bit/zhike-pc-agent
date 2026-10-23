from .dialogue_fakes import legacy_analysis
from .dialogue_fakes import protocol_model,reply_protocol_model
"""Multi-turn behavior tests drive the same persisted orchestration as production."""
import asyncio
import json
import pytest
from sqlalchemy import select
from backend import ai
from backend.db import Session,Conversation,Message,Job
from .conftest import post
from .test_workflow import guest


def evidence(mid,text):return {'message_id':mid,'quote':text}
def fact(mid,text):return {'status':'known','quotes':[dict(**evidence(mid,text),kind='fact')]}

def add(cid,role,text):
    with Session() as s:
        c=s.get(Conversation,cid);c.seq+=1
        m=Message(conversation_id=cid,sender_id=c.customer_id if role=='customer' else c.owner_id or 'staff',role=role,content=text,client_id='dialogue-'+str(c.seq)+'-'+cid,seq=c.seq)
        s.add(m);s.commit();return m.id


def test_answer_delegation_recommendation_selection_and_quote_form_one_workflow(clients,monkeypatch):
    from backend import dialogue
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim')
    calls=[]
    async def model(instruction,data,*args,**kwargs):
        calls.append(data)
        if data.get('phase')=='compose':
            options=data['tools']['options'];chosen=options[:2]
            return {'action':'recommend','reply':'这里有两套可供比较的配置。','option_ids':[o['id'] for o in chosen]},{}
        newest=data['messages'][-1]
        if newest['text']=='预算一万元以内，学习和写代码':
            return {'facts':{'budget':fact(newest['id'],'预算一万元以内'),'tasks':fact(newest['id'],'学习和写代码')},'goal':'quote','action':'ask','target':'configuration','reply':'您有明确的内存和存储要求，还是希望我按用途推荐？'},{}
        if newest['text']=='给我最好的':
            question=data['state']['questions'][-1]
            return {'goal':'quote','action':'recommend','delegation':evidence(newest['id'],'给我最好的'),'resolutions':[{'question_id':question['id'],'status':'delegated','evidence':evidence(newest['id'],'给我最好的')}]},{}
        if newest['text']=='就第二套，报价吧':
            return {'goal':'quote','action':'quote','selection':{'option_id':data['state']['presentations'][-1]['option_ids'][1],'evidence':evidence(newest['id'],'就第二套，报价吧')}},{}
        raise AssertionError('Unexpected turn')
    options=[{'id':'o1','product_id':'p','name':'产品甲','variant':'16GB/512GB','facts':[],'price':None},
             {'id':'o2','product_id':'p','name':'产品甲','variant':'32GB/1TB','facts':[],'price':None}]
    async def catalog(*args,**kwargs):return {'options':options,'sources':[],'warnings':[]}
    monkeypatch.setattr(ai,'model_json',protocol_model(model));monkeypatch.setattr(dialogue,'load_options',catalog)
    add(cid,'customer','预算一万元以内，学习和写代码')
    first=asyncio.run(legacy_analysis(cid))
    action=first['dialogue']['action'];assert action['kind']=='ask'
    sent=post(staff,f'/conversations/{cid}/messages',{'content':action['reply'],'client_id':'dialogue-sent-question','action_id':action['id']})
    assert sent.status_code==200
    add(cid,'customer','给我最好的')
    second=asyncio.run(legacy_analysis(cid));state=second['dialogue']
    assert state['action']['kind']=='recommend'
    assert state['questions'][-1]['status']=='delegated'
    assert state['selection']['status']=='unconfirmed'
    assert len(state['options'])==2
    action=state['action']
    assert post(staff,f'/conversations/{cid}/messages',{'content':action['reply'],'client_id':'dialogue-sent-options','action_id':action['id']}).status_code==200
    add(cid,'customer','就第二套，报价吧')
    # The composer can explain missing authoritative prices, but cannot invent one.
    async def quote_model(instruction,data,*args,**kwargs):
        if data.get('phase')=='compose':return {'action':'quote','reply':'已确认第二套配置，门店有效价格还需核对。','option_ids':['o2']},{}
        return await model(instruction,data,*args,**kwargs)
    monkeypatch.setattr(ai,'model_json',protocol_model(quote_model))
    third=asyncio.run(legacy_analysis(cid))['dialogue']
    assert third['selection']['option_id']=='o2'
    assert third['quotes'][0]['state']=='needs_price'
    assert third['quotes'][0]['total_minor'] is None
    assert third['action']['kind']=='quote'
    assert staff.get('/api/conversations/'+cid).json()['dialogue']['action']['kind']=='quote'
    assert 'dialogue' not in customer.get('/api/conversations/'+cid).json()


def test_get_is_projection_only_and_does_not_redecide_or_repeat_question(clients,monkeypatch):
    from backend import dialogue
    _,staff,customer,_=clients;cid=guest(customer)
    add(cid,'customer','帮我挑个适合写作的')
    async def model(*args,**kwargs):return {'goal':'recommend','action':'ask','target':'budget','reply':'您准备的购机预算范围是多少？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model))
    asyncio.run(legacy_analysis(cid))
    def forbidden(*args,**kwargs):raise AssertionError('GET must not run business decision logic')
    monkeypatch.setattr(ai,'model_json',protocol_model(forbidden))
    a=staff.get('/api/conversations/'+cid).json();b=staff.get('/api/conversations/'+cid).json()
    assert a['dialogue']['action']==b['dialogue']['action']
    assert a['requires_analysis'] and a['analysis']['next_question']['state']=='refresh_required'
    assert a['dialogue']['action']['question']['text']=='您准备的购机预算范围是多少？'


def test_budget_revision_invalidates_quote_and_keeps_other_facts(clients,monkeypatch):
    from backend import dialogue
    _,_,customer,_=clients;cid=guest(customer)
    first=add(cid,'customer','预算8000以内，需要用单位自研的星帆系统')
    async def model(*args,**kwargs):return {'facts':{'budget':fact(first,'预算8000以内'),'software':fact(first,'单位自研的星帆系统')},'goal':'recommend','action':'inform','reply':'已记录预算和必须运行的系统。'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model));asyncio.run(legacy_analysis(cid))
    revised=add(cid,'customer','预算改成6000以内，其他不变')
    async def change(*args,**kwargs):
        assert data_state(kwargs,args)['needs']['software']['value']=='单位自研的星帆系统'
        return {'facts':{'budget':fact(revised,'预算改成6000以内')},'goal':'recommend','action':'inform','reply':'我会按新预算重新筛选。'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(change))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert '6000' in state['needs']['budget']['value']
    assert state['needs']['software']['value']=='单位自研的星帆系统'

def data_state(kwargs,args):return args[1]['state']


def test_stale_model_result_never_overwrites_new_customer_turn(clients,monkeypatch):
    from backend import dialogue
    _,_,customer,_=clients;cid=guest(customer);add(cid,'customer','先了解一下')
    async def model(*args,**kwargs):
        add(cid,'customer','补充一个要求')
        return {'goal':'information','action':'inform','reply':'旧消息生成的建议'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model))
    assert asyncio.run(legacy_analysis(cid))['stale'] is True


def test_configuration_preferences_require_attribute_evidence_and_do_not_create_sale_sku():
    from backend.dialogue import configuration_options
    tools={'options':[{'id':'p','product_id':'pc','name':'产品甲','variant':'系列'}],
           'sources':[{'id':'s','product_id':'pc','excerpt':'内存可选16 GB / 32 GB，硬盘1 TB。'}]}
    proposals=[{'product_id':'pc','attributes':[{'key':'内存','value':'32 GB','source_id':'s','quote':'内存可选16 GB / 32 GB'},{'key':'硬盘','value':'1 TB','source_id':'s','quote':'硬盘1 TB'}]},
               {'product_id':'pc','attributes':[{'key':'内存','value':'128 GB','source_id':'s','quote':'内存可选16 GB / 32 GB'}]}]
    result=configuration_options(proposals,tools)
    assert len(result)==1
    assert result[0]['sku_verified'] is False
    assert '32 GB' in result[0]['variant'] and '待核实' in result[0]['variant']
    combined=[{'product_id':'pc','attributes':[{'key':'内存','value':'16 GB / 32 GB','source_id':'s','quote':'内存可选16 GB / 32 GB'}]}]
    assert configuration_options(combined,tools)==[]


def test_service_request_cannot_enter_purchase_plan_without_typed_purchase_evidence(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer);mid=add(cid,'customer','想了解产品，要运行单位自研软件')
    async def model(*args,**kwargs):return {'facts':{'progress':fact(mid,'要运行单位自研软件')},'goal':'information','action':'ask','target':'software_system','reply':'该软件需要什么操作系统环境？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model))
    with pytest.raises(ValueError):asyncio.run(legacy_analysis(cid))


def test_adopted_draft_is_rejected_after_a_new_customer_message(clients,monkeypatch):
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim');add(cid,'customer','先了解一下')
    async def model(*args,**kwargs):return {'goal':'information','action':'ask','target':'tasks','reply':'平时主要处理哪些事情？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model))
    action=asyncio.run(legacy_analysis(cid))['dialogue']['action']
    add(cid,'customer','补充一下，主要写代码')
    r=post(staff,f'/conversations/{cid}/messages',{'content':action['reply'],'client_id':'stale-adopted-draft','action_id':action['id']})
    assert r.status_code==409


def test_manual_lock_updates_canonical_state_and_is_visible_to_next_model(clients,monkeypatch):
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim');mid=add(cid,'customer','预算9000元以内')
    async def initial(*args,**kwargs):return {'facts':{'budget':fact(mid,'预算9000元以内')},'goal':'recommend','action':'ask','target':'tasks','reply':'主要有哪些使用需求？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(initial));asyncio.run(legacy_analysis(cid))
    assert staff.patch(f'/api/conversations/{cid}/analysis',json={'field':'budget','value':'7000元以内','locked':True},headers={'X-Store-Request':'1'}).status_code==200
    assert staff.get('/api/conversations/'+cid).json()['dialogue']['needs']['budget']['value']=='7000元以内'
    later=add(cid,'customer','现在只考虑6000元以内')
    async def revise(instruction,data,*args,**kwargs):
        assert data['manual_locks']['budget']['value']=='7000元以内'
        return {'facts':{'budget':fact(later,'6000元以内')},'goal':'recommend','action':'ask','target':'tasks','reply':'主要有哪些使用需求？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(revise))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert state['needs']['budget']['value']=='7000元以内'
    assert state['conflicts'][0]['field']=='budget'


def test_same_customer_evidence_cannot_be_both_delegation_and_configuration_confirmation():
    from backend.dialogue import apply_decision
    from backend.requirements import build_requirements
    messages=[{'id':'a','role':'customer','text':'你决定就行','seq':3}]
    state={'needs':build_requirements({},messages),'constraints':[],'conflicts':[],'quotes':[],'questions':[],
           'selection':{'status':'unconfirmed'},'options':[{'id':'v'}],'presentations':[{'seq':2,'option_ids':['v']}],'goal':'recommend'}
    decision={'customer_act':'confirm_option','delegation':evidence('a','你决定就行'),'selection':{'option_id':'v','evidence':evidence('a','你决定就行')}}
    updated,_=apply_decision(state,decision,messages,{},'新咨询')
    assert updated['selection']['status']=='unconfirmed'


def test_full_selection_to_authorised_quote_and_revoke_before_send(clients,monkeypatch):
    from backend import dialogue
    from backend.db import PriceRule
    from .test_quote_engine import rule
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim')
    option={'id':'verified-variant','product_id':'pc','name':'测试产品','variant':'已核实销售配置','sku_verified':True,'price':None}
    async def catalog(*args,**kwargs):return {'options':[option],'sources':[],'warnings':[]}
    async def model(instruction,data,*args,**kwargs):
        if data['phase']=='compose':return {'action':data['plan']['action'],'reply':'已整理对应方案，供您确认。','option_ids':[option['id']]},{}
        if not data['state']['presentations']:return {'goal':'recommend','action':'recommend'},{}
        latest=data['messages'][-1]
        return {'goal':'quote','action':'quote','selection':{'option_id':option['id'],'evidence':evidence(latest['id'],latest['text'])}},{}
    monkeypatch.setattr(dialogue,'load_options',catalog);monkeypatch.setattr(ai,'model_json',protocol_model(model))
    add(cid,'customer','预算9000元以内，帮我选一套')
    first=asyncio.run(legacy_analysis(cid))['dialogue']['action']
    assert post(staff,f'/conversations/{cid}/messages',{'content':first['reply'],'action_id':first['id'],'client_id':'formal-options-sent'}).status_code==200
    with Session() as s:
        s.add(PriceRule(id='authorised',product_id='pc',variant_id=option['id'],author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule())));s.commit()
    add(cid,'customer','就这套，报价吧')
    quoted=asyncio.run(legacy_analysis(cid))['dialogue']
    assert quoted['selection']['status']=='confirmed'
    assert quoted['quotes'][0]['total_minor']==800900
    assert '8009' in quoted['action']['reply']
    action=quoted['action']
    changed=post(staff,f'/conversations/{cid}/messages',{'content':action['reply'].replace('8009','9000'),'action_id':action['id'],'client_id':'edited-formal-amount'})
    assert changed.status_code==409
    with Session() as s:s.get(PriceRule,'authorised').status='revoked';s.commit()
    action=quoted['action']
    response=post(staff,f'/conversations/{cid}/messages',{'content':action['reply'],'action_id':action['id'],'client_id':'revoked-formal-quote'})
    assert response.status_code==409
    with Session() as s:
        s.add(PriceRule(id='new-authorised-version',product_id='pc',variant_id=option['id'],author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule(approval_id='new-approval'))));s.commit()
    renewed=asyncio.run(legacy_analysis(cid))['dialogue']['action']
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'您好，'+renewed['intro'],'action_id':renewed['id'],'client_id':'renewed-formal-quote'})
    assert sent.status_code==200
    delivered=staff.get('/api/conversations/'+cid).json()['dialogue']
    assert delivered['action']['kind']=='wait' and delivered['quotes'][0]['delivery_status']=='sent'
    card=customer.get('/api/conversations/'+cid).json()['messages'][-1]['card']
    assert card['type']=='quote' and card['quotes'][0]['total_minor']==800900
    assert 'approval_id' not in json.dumps(card) and 'rule_id' not in json.dumps(card)


def test_budget_filter_uses_valid_payable_amounts_not_historical_snapshots():
    from backend.dialogue import verified_budget_fit
    state={'needs':{'budget':{'value':'7000元以内'}},'constraints':[]}
    options=[{'id':'above'},{'id':'within'},{'id':'historical','price':{'amount_minor':100000}}]
    verified_budget_fit(state,options,[{'option_id':'above','state':'ready_for_review','total_minor':800000},
                                      {'option_id':'within','state':'ready_for_review','total_minor':600000}])
    assert [o['budget_fit'] for o in options]==['exceeds','fits','unknown']


def test_staff_can_edit_greeting_without_losing_presented_option_identity(clients,monkeypatch):
    from backend import dialogue
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim');add(cid,'customer','帮我选一套')
    async def catalog(*args,**kwargs):return {'options':[{'id':'v','product_id':'p','name':'电脑甲','variant':'32GB/1TB'}],'sources':[],'warnings':[]}
    async def model(instruction,data,*args,**kwargs):return ({'action':'recommend','reply':'请看这套方案。','option_ids':['v']} if data['phase']=='compose' else {'goal':'recommend','action':'recommend'}),{}
    monkeypatch.setattr(dialogue,'load_options',catalog);monkeypatch.setattr(ai,'model_json',protocol_model(model))
    action=asyncio.run(legacy_analysis(cid))['dialogue']['action']
    assert post(staff,f'/conversations/{cid}/messages',{'content':'您好，'+action['reply'],'action_id':action['id'],'client_id':'edited-greeting-options'}).status_code==200
    state=staff.get('/api/conversations/'+cid).json()['dialogue']
    assert state['presentations'][-1]['option_ids']==['v']


def test_new_customer_request_can_resume_after_pause_without_old_question_in_profile(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer);add(cid,'customer','先不买了')
    async def pause(*args,**kwargs):return {'goal':'none','action':'pause','reply':'好的。'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(pause));asyncio.run(legacy_analysis(cid))
    async def forbidden(*args,**kwargs):raise AssertionError('No new customer input: do not regenerate paused outreach')
    monkeypatch.setattr(ai,'model_json',protocol_model(forbidden))
    assert asyncio.run(legacy_analysis(cid))['dialogue']['action']['kind']=='pause'
    with Session() as s:s.get(Conversation,cid).stage='暂不购买';s.commit()
    add(cid,'customer','我又考虑好了，继续帮我选')
    async def resume(instruction,data,*args,**kwargs):
        assert 'next_question' not in data['state']['needs']
        return {'goal':'recommend','action':'ask','target':'budget','reply':'这次准备的预算范围是多少？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(resume))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert state['action']['kind']=='ask' and state['stage_revisit_required']


def test_replacing_fact_cannot_clear_the_new_value_in_the_same_turn():
    from backend.dialogue import apply_decision
    from backend.requirements import build_requirements
    messages=[{'id':'old','role':'customer','text':'预算8000元以内','seq':1},{'id':'new','role':'customer','text':'预算改到6000元以内，其他不变','seq':2}]
    state={'needs':build_requirements({'budget':fact('old','预算8000元以内')},messages),'constraints':[],'conflicts':[],'quotes':[],'questions':[],
           'selection':{'status':'unconfirmed'},'options':[],'presentations':[],'goal':'recommend'}
    decision={'facts':{'budget':fact('new','预算改到6000元以内')},'clear_fields':[{'field':'budget','evidence':evidence('new','预算改到6000元以内')}]}
    result,_=apply_decision(state,decision,messages,{},'新咨询')
    assert '6000' in result['needs']['budget']['value']


def test_store_price_can_complete_quote_after_staff_informed_customer_without_new_customer_message(clients,monkeypatch):
    from backend import dialogue
    from backend.db import PriceRule
    from .test_quote_engine import rule
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim')
    option={'id':'store-v','product_id':'pc','name':'产品甲','variant':'32GB/1TB','sku_verified':True}
    async def catalog(*args,**kwargs):return {'options':[option],'sources':[],'warnings':[]}
    async def model(instruction,data,*args,**kwargs):
        if data['phase']=='compose':return {'action':data['plan']['action'],'reply':'请查看本次方案的核验结果。','option_ids':['store-v']},{}
        if not data['state']['presentations']:return {'goal':'recommend','action':'recommend'},{}
        latest=data['messages'][-1]
        return {'goal':'quote','action':'quote','selection':{'option_id':'store-v','evidence':evidence(latest['id'],latest['text'])}},{}
    monkeypatch.setattr(dialogue,'load_options',catalog);monkeypatch.setattr(ai,'model_json',protocol_model(model))
    add(cid,'customer','帮我推荐');first=asyncio.run(legacy_analysis(cid))['dialogue']['action']
    post(staff,f'/conversations/{cid}/messages',{'content':first['reply'],'action_id':first['id'],'client_id':'price-work-options'})
    add(cid,'customer','就这套，报价');missing=asyncio.run(legacy_analysis(cid))['dialogue']['action']
    post(staff,f'/conversations/{cid}/messages',{'content':missing['reply'],'action_id':missing['id'],'client_id':'price-work-missing'})
    with Session() as s:
        s.add(PriceRule(product_id='pc',variant_id='store-v',author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule())));s.commit()
    async def compose_only(instruction,data,*args,**kwargs):
        if data['phase'] in {'review','entailment'}:return {'valid_need_fields':[],'invalid_need_fields':[],'invalid_controls':[],'response_errors':[],'block_checks':[{'index':i,'supported':True,'reason':'测试给定内容'} for i,_ in enumerate(data.get('reply_blocks',[]))]},{}
        assert data['phase']=='compose', 'Store data changed: do not interview the customer again'
        assert data['tools']['options'][0]['configuration_status']=='verified'
        assert data['tools']['options'][0]['sku_verified'] is True
        assert 'budget_feasibility' not in data['tools']
        return {'blocks':[{'kind':'explanation','text':'本次授权价格已核验。','citations':[]}],'option_ids':['store-v']},{}
    monkeypatch.setattr(ai,'model_json',reply_protocol_model(compose_only))
    result=asyncio.run(legacy_analysis(cid))['dialogue']
    assert result['quotes'][0]['total_minor']==800900
    assert result['action']['kind']=='quote' and '8009' in result['action']['reply']
