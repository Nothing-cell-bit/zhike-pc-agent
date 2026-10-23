from .dialogue_fakes import legacy_analysis
"""Behavioral contracts independent of product names or question templates."""
import asyncio
import copy
import pytest
from backend import ai,dialogue
from backend.dialogue_contract import NEED_NAMES
from .dialogue_fakes import reply_protocol_model
from .test_dialogue_workflow import add,evidence,fact
from .test_workflow import guest


def clean_review(data=None,**changes):
    for key in ('valid_need_fields','invalid_need_fields'):
        if key in changes:changes[key]=[NEED_NAMES.get(field,field) for field in changes[key]]
    return {'valid_need_fields':[],'invalid_need_fields':[],'invalid_controls':[],'response_errors':[],'block_checks':[{'index':i,'supported':True,'reason':'测试给定的事实依据'} for i,_ in enumerate((data or {}).get('reply_blocks',[]))],**changes}


def test_identity_cannot_reuse_software_evidence_but_distinct_identity_is_preserved():
    facts={'user':fact('m','团队自研应用甲'),'software':fact('m','应用甲')}
    assert 'user' not in dialogue.independent_identity(facts)
    assert 'software' in dialogue.independent_identity(facts)
    facts['user']=fact('m','平面设计师')
    assert dialogue.independent_identity(facts)['user']==facts['user']


def test_public_field_name_cannot_bypass_known_requirement_question_guard():
    state={'needs':{'budget':{'value':'7000元以内','status':'known'}},'questions':[],'quotes':[]}
    question={'target':'purchase_budget','text':'预算是多少？','missing_information':'预算','why_needed':'选型'}
    decision={'action':'ask','question':question,'reply':question['text']}
    assert dialogue.checked_action(decision,state,{},[])['kind']=='review'


def test_information_sources_keep_each_spec_with_its_applicability_conditions():
    from backend.dialogue_catalog import information_sections
    source={'id':'s','product_id':'p','title':'设备甲','excerpt':'# 设备甲\n\n## 处理器\n\n选项A\n仅限系统甲\n选项B\n\n## 内存\n\n32 GB\n'}
    sections=information_sections(source)
    cpu=next(s for s in sections if '## 处理器' in s['excerpt'])
    assert '选项A\n仅限系统甲\n选项B' in cpu['excerpt']
    assert '32 GB' not in cpu['excerpt']
    assert len({s['id'] for s in sections})==len(sections)


def test_long_specification_sections_are_individually_citable():
    from backend.dialogue_catalog import information_sections
    body='## 参数\n\n'+'\n\n'.join(f'属性{i}\n\n值{i}\n\n*该值仅适用于版本{i}。' for i in range(20))
    parts=information_sections({'id':'s','product_id':'p','title':'设备','excerpt':body})
    assert len(parts)>1 and all(len(part['excerpt'])<350 for part in parts)
    assert all('仅适用' in part['excerpt'] for part in parts)


def test_product_fact_text_is_rendered_from_source_instead_of_model_inference():
    from backend.dialogue import materialize_facts
    tools={'sources':[{'id':'cpu','excerpt':'## 处理器\n\n处理器X\n\n*仅限系统甲版本。\n\n处理器Y'}]}
    blocks=[{'kind':'fact','text':'系统乙只能使用处理器Y。','citations':[{'source_id':'cpu','excerpt':'处理器X'}]}]
    assert materialize_facts(blocks,tools)==[]
    assert '系统乙' not in blocks[0]['text']
    assert '处理器X' in blocks[0]['text'] and '仅限系统甲' in blocks[0]['text']


def test_fact_and_natural_explanation_have_different_output_contracts():
    with pytest.raises(ValueError):
        dialogue.Composition.model_validate({'blocks':[{'kind':'fact','text':'未验证的自由改写',
            'citations':[{'source_id':'s','excerpt':'原文事实'}]}]})
    parsed=dialogue.Composition.model_validate({'blocks':[{'kind':'fact','citations':[{'source_id':'s','excerpt':'原文事实'}]},
        {'kind':'limitation','text':'资料未说明这一项。'}]})
    assert len(parsed.blocks)==2


def test_information_route_does_not_expose_internal_sales_guidance(monkeypatch):
    from backend import dialogue_catalog as catalog
    monkeypatch.setattr(catalog,'MARKETING_SOURCE','ima_first')
    monkeypatch.setattr(catalog.knowledge,'products',lambda:[{'id':'p','name':'设备甲'}])
    monkeypatch.setattr(catalog.knowledge,'product',lambda _: {'facts':{'id':'local','title':'产品事实','body':'本地事实','sha256':'h'}})
    from backend import ima_dialogue
    async def retrieve(*args):return {'status':'retrieved','retrieved_at':'2026-10-21T00:00:00+00:00','sources':[
        {'id':'technical','title':'产品事实.md','excerpt':'## 参数\n32 GB'},
        {'id':'sales','title':'卖点与限制.md','excerpt':'内部营销话术'}]}
    monkeypatch.setattr(ima_dialogue,'retrieve',retrieve)
    result=asyncio.run(catalog.load_information(['p']))
    assert all('内部营销话术' not in source['excerpt'] for source in result['sources'])
    assert any('32 GB' in source['excerpt'] for source in result['sources'])


@pytest.mark.parametrize('subject',['接口','显示效果','电池寿命'])
def test_product_question_is_not_a_customer_requirement(subject):
    from backend.requirements import build_requirements
    messages=[{'id':'q','role':'customer','text':subject,'seq':1}]
    state={'needs':build_requirements({},messages),'constraints':[],'conflicts':[],'quotes':[],
           'questions':[],'selection':{'status':'unconfirmed'},'options':[],'presentations':[],'goal':'information'}
    decision={'customer_act':'request_information','customer_evidence':evidence('q',subject),
              'topic':{'subject':subject,'request':'了解产品的'+subject,'product_ids':['p'],'evidence':evidence('q',subject)},
              'facts':{'software':fact('q',subject)},'goal':'information'}
    updated,_=dialogue.apply_decision(state,decision,messages,{},'新咨询')
    assert updated['needs']['software']['status']=='unknown'
    assert updated['topic']['subject']==subject


def test_information_route_never_reads_quotes_and_writer_has_no_action_authority(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer);mid=add(cid,'customer','这款设备接口有哪些？')
    def no_quotes(*args,**kwargs):raise AssertionError('Ordinary information must not invoke pricing')
    async def information(*args,**kwargs):return {'products':[{'id':'p','name':'设备甲'}],'sources':[{'id':'s','product_id':'p','excerpt':'USB-C接口2个'}]}
    async def model(instruction,data,*args,**kwargs):
        if data['phase']=='needs':return {'changes':[]},{}
        if data['phase']=='interpret':return {'customer_act':'request_information','customer_evidence':evidence(mid,'这款设备接口有哪些？'),
            'topic':{'subject':'接口','request':'查询接口数量','product_ids':['p'],'evidence':evidence(mid,'这款设备接口有哪些？')},
            'goal':'information','action':'inform','product_ids':['p'],'question':None},{}
        if data['phase']=='compose':
            assert data['messages'][-1]['id']==mid
            assert 'quotes' not in data['tools'] and 'quote_checks' not in data['tools']
            assert 'action' not in kwargs['schema'].model_json_schema()['properties']
            return {'blocks':[{'kind':'fact','citations':[{'source_id':'s','excerpt':'USB-C接口2个'}]},
                {'kind':'explanation','text':'也就是2个USB-C接口。','citations':[{'source_id':'s','excerpt':'USB-C接口2个'}]}]},{}
        assert data['phase'] in {'review','entailment'}
        return clean_review(data),{}
    monkeypatch.setattr(dialogue,'prepare_quotes',no_quotes)
    monkeypatch.setattr(dialogue,'load_information',information,raising=False)
    monkeypatch.setattr(ai,'model_json',reply_protocol_model(model))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert state['action']['reply']=='USB-C接口2个\n也就是2个USB-C接口。'
    assert state['action']['question'] is None
    assert state['needs']['tasks']['status']=='unknown'


def test_semantic_review_rejects_hidden_question_even_without_question_mark(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer);mid=add(cid,'customer','我只问刚才这个参数')
    calls=[]
    async def information(*args,**kwargs):return {'products':[],'sources':[{'id':'s','product_id':'p','excerpt':'参数值A'}]}
    async def model(instruction,data,*args,**kwargs):
        calls.append(data['phase'])
        if data['phase']=='needs':return {'changes':[]},{}
        if data['phase']=='interpret':return {'customer_act':'request_information','customer_evidence':evidence(mid,'我只问刚才这个参数'),
            'goal':'information','action':'inform','product_ids':['p'],'topic':None,'question':None},{}
        if data['phase']=='compose':return {'blocks':[{'kind':'explanation','text':'参数值A。请说说您主要关注哪个方面','citations':[]}]},{}
        assert data['phase'] in {'review','entailment'}
        return clean_review(data,response_errors=['正文擅自加入未获准的重复追问']),{}
    monkeypatch.setattr(dialogue,'load_information',information,raising=False);monkeypatch.setattr(ai,'model_json',reply_protocol_model(model))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert state['action']['kind']=='review' and not state['action']['reply']
    assert calls.count('compose')==2 and calls.count('review')==2


def test_review_rejects_misclassified_fact_without_discarding_valid_budget(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer);mid=add(cid,'customer','预算7000元，屏幕是什么规格？')
    async def information(*args,**kwargs):return {'products':[],'sources':[]}
    async def model(instruction,data,*args,**kwargs):
        if data['phase']=='needs':return {'changes':[{'field':'purchase_budget','fact':fact(mid,'预算7000元')},{'field':'usage_tasks','fact':fact(mid,'屏幕是什么规格？')}]},{}
        if data['phase']=='interpret':return {'customer_act':'request_information','customer_evidence':evidence(mid,'屏幕是什么规格？'),
            'goal':'information','action':'inform','product_ids':['p'],'topic':None,'question':None},{}
        if data['phase']=='compose':return {'blocks':[{'kind':'limitation','text':'现有资料未列出这一项。','citations':[]}]},{}
        return clean_review(data,valid_need_fields=['budget'],invalid_need_fields=['tasks']),{}
    monkeypatch.setattr(dialogue,'load_information',information,raising=False);monkeypatch.setattr(ai,'model_json',reply_protocol_model(model))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert state['needs']['tasks']['status']=='unknown'
    assert '7000' in state['needs']['budget']['value']
    assert state['action']['kind']=='inform'


@pytest.mark.parametrize('first_error',['old_request','wait_on_new_input'])
def test_latest_customer_turn_controls_the_topic_when_analysis_missed_earlier_messages(clients,monkeypatch,first_error):
    _,_,customer,_=clients;cid=guest(customer);old=add(cid,'customer','介绍设备甲');latest=add(cid,'customer','只介绍接口')
    decisions=0
    async def information(*args,**kwargs):return {'products':[],'sources':[{'id':'s','excerpt':'两个接口'}]}
    async def model(instruction,data,*args,**kwargs):
        nonlocal decisions
        if data['phase']=='needs':return {'changes':[]},{}
        if data['phase']=='interpret':
            decisions+=1;stale=decisions==1 and first_error=='old_request';mid=old if stale else latest;quote='介绍设备甲' if stale else '只介绍接口'
            if decisions==2:assert data['current_turn']['id']==latest and data['validation_errors']
            return {'goal':'information','action':'wait' if decisions==1 and first_error=='wait_on_new_input' else 'inform','customer_act':'request_information','customer_evidence':evidence(mid,quote),
                    'topic':{'subject':quote,'request':quote,'product_ids':['p'],'evidence':evidence(mid,quote)}},{}
        if data['phase']=='compose':return {'blocks':[{'kind':'fact','citations':[{'source_id':'s','excerpt':'两个接口'}]}]},{}
        return clean_review(data),{}
    monkeypatch.setattr(dialogue,'load_information',information,raising=False);monkeypatch.setattr(ai,'model_json',reply_protocol_model(model))
    state=asyncio.run(legacy_analysis(cid))['dialogue']
    assert decisions==2 and state['topic']['evidence']['message_id']==latest
