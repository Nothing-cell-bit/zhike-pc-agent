from .dialogue_fakes import legacy_analysis
from .dialogue_fakes import protocol_model
import asyncio
import json
import pytest
from backend import ai
from backend.db import Session,Conversation,Message,Job
from backend.requirements import build_requirements,SCHEMA_VERSION
from .test_workflow import guest
from .conftest import post


def msg(key,text,role='customer',seq=1):return dict(id=key,text=text,role=role,seq=seq)
def request(key='b',quote='可以给我报价了吗'):return dict(kind='price',message_id=key,quote=quote)


def test_pricing_request_is_separate_and_prioritized_over_customer_profile():
    messages=[msg('a','我想换电脑'),msg('b','可以给我报价了吗',seq=2)]
    raw={'progress':{'status':'known','quotes':[dict(message_id='a',quote='想换电脑')]},'service_request':request()}
    result=build_requirements(raw,messages)
    assert result['progress']['value']=='想换电脑'
    assert result['service_request']['kind']=='price'
    assert result['next_question']['state']=='review'
    assert result['next_question']['text']==''
    assert build_requirements(result,messages)['service_request']['kind']=='price'


@pytest.mark.parametrize('message',[msg('b','可以给我报价了吗','staff'),msg('b','你好')])
def test_invalid_or_staff_request_cannot_bypass_missing_requirements(message):
    result=build_requirements({'service_request':request()},[message])
    assert result.get('service_request',{}).get('kind')!='price'
    assert result['next_question']['field']!='pricing'


def test_manual_intention_lock_survives_pricing_request_and_model_refresh(clients,monkeypatch):
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim')
    assert staff.patch(f'/api/conversations/{cid}/analysis',json={'field':'progress','value':'想换电脑'},headers={'X-Store-Request':'1'}).status_code==200
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=1
        s.add(Message(id='b',conversation_id=cid,sender_id=c.customer_id,role='customer',content='可以给我报价了吗',client_id='pricing-request',seq=1));s.commit()
    async def model(*args,**kwargs):return {'goal':'quote','action':'ask','target':'configuration','reply':'希望比较哪些配置？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model))
    asyncio.run(legacy_analysis(cid))
    view=staff.get('/api/conversations/'+cid).json()
    assert view['analysis']['progress']['value']=='想换电脑'
    assert view['analysis']['progress']['manual'] is True
    assert view['locked']['progress']['value']=='想换电脑'
    assert 'pricing_plan' not in customer.get('/api/conversations/'+cid).json()


def test_price_suggestion_does_not_reinterview_identity_or_guess_amount(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer)
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=1;c.analysis_seq=1;c.analysis=json.dumps({'schema_version':SCHEMA_VERSION,'service_request':request()})
        s.add(Message(id='b',conversation_id=cid,sender_id=c.customer_id,role='customer',content='可以给我报价了吗',client_id='pricing-suggestion',seq=1));s.commit()
    async def forbidden(*args,**kwargs):return {'goal':'quote','action':'ask','target':'configuration','reply':'您有配置偏好，还是希望我帮您比较？'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(forbidden))
    result=asyncio.run(legacy_analysis(cid))
    assert result['dialogue']['goal']=='quote'
    assert '配置' in result['reply']
    assert '自己用' not in result['reply']


def test_pricing_evidence_must_come_from_ima_and_generated_claims_require_quotes():
    from backend.pricing import validate_plan
    refs=[{'id':'s1','title':'渠道报价登记.md','excerpt':'本文件不含实际价格。完整 SKU、数量、含税口径、有效期须确认。','source_type':'ima'}]
    raw={'levels':[{'level':'L1','items':[{'text':'确认配置和有效期','source_id':'s1','quote':'完整 SKU、数量、含税口径、有效期须确认。'},{'text':'自动优惠1000元','source_id':'s1','quote':'自动优惠1000元'}]}]}
    result=validate_plan(raw,refs)
    assert len(result['levels'])==4
    assert result['levels'][0]['items'][0]['text']=='确认配置和有效期'
    assert len(result['levels'][0]['items'])==1
    assert all(level['amount'] is None for level in result['levels'])
    assert result['state']=='needs_confirmation'
    with pytest.raises(ValueError):validate_plan(raw,[{**refs[0],'source_type':'local_zip'}])


def test_quote_request_cannot_also_replace_purchase_intention():
    raw={'progress':{'status':'partial','quotes':[dict(message_id='b',quote='可以给我报价了吗')]},'service_request':request()}
    result=build_requirements(raw,[msg('b','可以给我报价了吗')])
    assert result['progress']['value']=='尚未了解'


def test_pricing_job_persists_staff_only_details_and_customer_cannot_start_it(clients,monkeypatch):
    from backend import pricing
    from backend.knowledge import knowledge
    _,staff,customer,other=clients;cid=guest(customer)
    product=knowledge.products()[0]
    async def generate(p,needs):return {'product_id':p['id'],'levels':[],'private_check':'staff only'},{}
    monkeypatch.setattr(pricing,'create_plan',generate)
    assert post(customer,f'/conversations/{cid}/ai/pricing',{'product_id':product['id']}).status_code==403
    with Session() as s:
        j=Job(kind='pricing',target_id=cid,actor_id='staff',payload=json.dumps({'product_id':product['id']}));s.add(j);s.commit();jid=j.id
    asyncio.run(ai.run_text_job(jid))
    with Session() as s:assert s.get(Job,jid).status=='completed'
    assert staff.get('/api/conversations/'+cid).json()['pricing_plan']['private_check']=='staff only'
    assert 'pricing_plan' not in customer.get('/api/conversations/'+cid).json()
    assert customer.get('/api/jobs/'+jid).status_code==403


def test_ima_pricing_retrieval_uses_exact_folder_and_private_snapshot(tmp_path,monkeypatch):
    from backend import pricing
    monkeypatch.setattr(pricing,'DATA',tmp_path)
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def listing(self,api,body,field):
            if api=='search_knowledge_base':return [dict(kb_id='kb',kb_name=pricing.LIBRARY_NAME)]
            if api=='search_knowledge':return []
            if body.get('folder_id')=='p4':return [dict(title='渠道报价登记.md',media_type=7,media_id='doc')]
            return [dict(title='P4-价格政策库（机密）',media_type=99,media_id='p4')]
        async def media(self,item):return '# 渠道报价登记\n\n受控模板，不含实际价格。请核对完整 SKU、数量及有效期。'.encode()
    refs,sid=asyncio.run(pricing.fetch_pricing_sources(Client))
    assert refs[0]['source_type']=='ima'
    saved=tmp_path/'private'/'pricing'/(sid+'.json')
    assert saved.is_file()
    assert not (tmp_path/'ima'/'records').exists()
    assert json.loads(saved.read_text(encoding='utf-8'))['search_hits']==0
    class NeverConnect:
        def __init__(self):raise AssertionError('Valid same-day ima evidence must be reused')
    cached,cached_id=asyncio.run(pricing.fetch_pricing_sources(NeverConnect))
    assert cached==refs and cached_id==sid


def test_tampered_pricing_cache_is_not_used_as_verified_ima_evidence(tmp_path,monkeypatch):
    from backend import pricing
    from backend.ima import save_json,timestamp
    monkeypatch.setattr(pricing,'DATA',tmp_path)
    root=tmp_path/'private'/'pricing';root.mkdir(parents=True)
    save_json(root/'latest.json',{'snapshot_id':'a'*32,'retrieved_at':timestamp()})
    save_json(root/('a'*32+'.json'),{'retrieved_at':timestamp(),'sources':[{'id':'bad','title':'渠道报价登记.md','body':'被篡改','sha256':'wrong','source_type':'ima'}]})
    assert pricing.cached_pricing_sources() is None


def test_enterprise_approval_rules_are_not_classified_as_retail_bundle_terms():
    from backend.pricing import validate_plan
    refs=[{'id':'s','title':'企业采购报价登记.md','source_type':'ima','excerpt':'数量变化后重新审批'}]
    raw={'levels':[{'level':'L3','items':[{'text':'数量变化后重新审批','source_id':'s','quote':'数量变化后重新审批'}]}]}
    assert validate_plan(raw,refs)['levels'][2]['items']==[]
