import json
from backend import dialogue
from backend.db import Session,DialogueState,Conversation,PriceRule
from backend.quoting import prepare_quotes
from .test_quote_engine import rule
from backend.service_workflow import ensure_budget_followthrough
from backend.service_workflow import finish_candidates
from .test_reply_choices import seed
from .conftest import post


def test_return_to_comparison_does_not_send_previous_quote_card(clients):
    cid,_,state=seed(clients)
    option={'id':'old-option','product_id':'pc','name':'演示电脑','variant':'16GB/1TB'}
    with Session() as s:
        s.add(PriceRule(product_id='pc',variant_id=option['id'],author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule())));s.commit()
    state.update(goal='compare',options=[option],quotes=prepare_quotes([option]))
    state['action'].update(kind='compare',option_ids=['old-option'])
    with Session() as s:
        s.get(DialogueState,cid).state=json.dumps(state);s.commit()
        assert dialogue.check_send_action(s,s.get(Conversation,cid),'old',state['action']['reply'])=={}


def test_comparison_with_new_budget_and_unknown_price_creates_owned_verification():
    message={'id':'m','role':'customer','text':'预算8000以内，帮我比较配置','seq':5}
    state={'goal':'compare','needs':{'budget':{'status':'known','value':'8000以内','quotes':[{'message_id':'m','quote':'预算8000以内'}]}},'tasks':[],
           'options':[{'product_id':'pc','budget_fit':'unknown','price_verified':False}]}
    plan={'customer_act':'request_recommendation','topic':{'product_ids':['pc']}}
    ensure_budget_followthrough(state,plan,[message],5,[{'id':'pc','name':'演示电脑'}])
    assert len(state['tasks'])==1 and state['tasks'][0]['kind']=='verify'
    assert state['tasks'][0]['owner']=='staff' and state['tasks'][0]['target']=='purchase_budget'


def test_verified_budget_match_does_not_create_redundant_price_verification():
    message={'id':'m','role':'customer','text':'预算8000以内，帮我比较配置','seq':5}
    state={'goal':'compare','needs':{'budget':{'status':'known','value':'8000以内','quotes':[{'message_id':'m','quote':'预算8000以内'}]}},'tasks':[],
           'options':[{'id':'v','product_id':'pc'}]}
    dialogue.verified_budget_fit(state,state['options'],[{'option_id':'v','state':'ready_for_review','total_minor':599900}])
    plan={'customer_act':'request_recommendation','topic':{'product_ids':['pc']}}
    assert ensure_budget_followthrough(state,plan,[message],5,[{'id':'pc','name':'演示电脑'}])==''
    assert not state['tasks']


def test_sent_standard_quote_does_not_wait_on_unselected_optional_discounts():
    state={'goal':'quote','tasks':[],'quotes':[
        {'level':'L1','state':'ready_for_review','delivery_status':'sent','sent_message_id':'actual-message'},
        {'level':'L2','state':'needs_qualification'}, {'level':'L4','state':'needs_approval'}]}
    assert dialogue.waiting_owner(state)=='customer'


def test_verified_price_feedback_binds_exact_sku_card_even_when_intro_has_no_citation():
    state={'goal':'quote','action':{'kind':'quote','option_ids':['v']},'tasks':[{'id':'price','kind':'verify','status':'completed','product_ids':['pc'],
        'verification':{'kind':'price','configuration':'SALE-SKU-001 / 16GB/1TB'}}],
        'quotes':[{'state':'ready_for_review','option_id':'v','product_id':'pc','sku_ref':'SALE-SKU-001'}]}
    c=finish_candidates([{'answer':'请查看已核价明细。','citations':[],'question':None}],'',state=state)[0]
    assert c['price_feedback']=={'price':['SALE-SKU-001']}
    state['tasks'][0]['verification']['configuration']='SALE-SKU-0010 / 16GB/1TB'
    c=finish_candidates([{'answer':'请查看已核价明细。','citations':[],'question':None}],'',state=state)[0]
    assert not c['price_feedback']
    state['tasks'][0]['verification']['configuration']='另一款销售SKU'
    c=finish_candidates([{'answer':'请查看已核价明细。','citations':[],'question':None}],'',state=state)[0]
    assert not c['price_feedback']


def test_sending_price_card_closes_matching_verification_feedback(clients):
    cid,staff,state=seed(clients)
    option={'id':'sale-v','product_id':'pc','name':'演示电脑','variant':'16GB/1TB'}
    with Session() as s:
        s.add(PriceRule(product_id='pc',variant_id=option['id'],author_id='author',approved_by='reviewer',status='approved',payload=json.dumps(rule())));s.commit()
    state.update(goal='quote',options=[option],quotes=prepare_quotes([option]),tasks=[{'id':'price','key':'verify:price','kind':'verify','status':'completed','product_ids':['pc'],
        'feedback_status':'pending','verification':{'kind':'price','configuration':'verified-sale-sku / 16GB/1TB'}}])
    state['action'].update(kind='quote',option_ids=[option['id']])
    candidate=finish_candidates([{'answer':'请查看报价卡。','question':None,'citations':[]}],'',state=state)[0]
    state['action']['candidates']=[candidate]
    with Session() as s:s.get(DialogueState,cid).state=json.dumps(state);s.commit()
    r=post(staff,f'/conversations/{cid}/messages',{'content':candidate['intro'],'action_id':candidate['id'],'client_id':'exact-price-card-feedback'})
    assert r.status_code==200 and r.json()['card']['type']=='quote'
    saved=dialogue.view(cid)
    assert saved['tasks'][0]['feedback_status']=='sent' and saved['tasks'][0]['feedback_message_id']==r.json()['id']
    assert saved['next_owner']=='customer'
