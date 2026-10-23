import asyncio
import httpx
from backend import ai
from backend.model_settings import ModelConfig
from backend.service_workflow import ServiceAudit,ServicePlanning


def test_decoder_schema_closes_objects_and_binds_reference_values():
    from backend.ai import decoder_schema
    from backend.service_workflow import SourceReference
    schema=decoder_schema(SourceReference,{'source_id':['R1','R2']})
    assert schema['additionalProperties'] is False
    assert schema['properties']['source_id']['enum']==['R1','R2']
    planned=decoder_schema(ServicePlanning)
    assert all(s.get('additionalProperties') is False for s in planned['$defs'].values() if s.get('type')=='object')
    assert 'title' in planned['$defs']['ResultWork']['properties']
    assert 'title' in planned['$defs']['ResultWork']['required']
    from backend.service_workflow import DraftChoice
    assert 'citations' in decoder_schema(DraftChoice)['required']


def test_gateway_uses_server_side_schema_instead_of_prompt_only(monkeypatch):
    monkeypatch.setattr(ai,'get_config',lambda:ModelConfig('https://model.test/v1','qwen-test','test-key','environment',True))
    calls=[]
    async def completion(settings,payload,timeout=100):
        calls.append(payload)
        assert payload['response_format']['type']=='json_schema'
        schema=payload['response_format']['json_schema']['schema']
        assert schema['required']==['errors','invalid_need_fields','invalid_candidates','reviews']
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"errors":[],"invalid_need_fields":[]}'},'finish_reason':'stop'}]})
    monkeypatch.setattr(ai,'completion',completion)
    result,_=asyncio.run(ai.model_json('校验客服草稿',{},schema=ServiceAudit,compact_schema=True,structured_output=True))
    assert result=={'errors':[],'invalid_need_fields':[],'invalid_candidates':[],'reviews':[]} and len(calls)==1
