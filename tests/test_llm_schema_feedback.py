import json
import asyncio
import httpx
from backend import ai
from backend.dialogue import Decision
from backend.model_settings import ModelConfig


def test_format_recovery_receives_exact_invalid_field_path(monkeypatch):
    calls=[]
    monkeypatch.setattr(ai,'get_config',lambda:ModelConfig('https://llm.example/v1','qwen-test','test-key'))
    async def completion(settings,payload,timeout=100):
        calls.append(json.loads(json.dumps(payload)))
        if len(calls)==1:content={'customer_act':'other','customer_evidence':None,'action':'inform','reply':'收到','facts':{'progress':{}}}
        else:
            assert 'facts' in payload['messages'][-1]['content'] and 'progress' in payload['messages'][-1]['content']
            content={'customer_act':'other','customer_evidence':None,'action':'inform','reply':'收到','facts':{}}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(content,ensure_ascii=False)},'finish_reason':'stop'}]})
    monkeypatch.setattr(ai,'completion',completion)
    result,_=asyncio.run(ai.model_json('校验字段',{},schema=Decision))
    assert len(calls)==2 and result['facts']['budget'] is None


def test_validator_context_is_serializable_during_bounded_repair(monkeypatch):
    monkeypatch.setattr(ai,'get_config',lambda:ModelConfig('https://llm.example/v1','qwen-test','test-key'))
    count=0
    async def completion(settings,payload,timeout=100):
        nonlocal count
        count+=1
        content={} if count==1 else {'title':'资料支持的标题','body':'资料支持的正文'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(content,ensure_ascii=False)},'finish_reason':'stop'}]})
    monkeypatch.setattr(ai,'completion',completion)
    result,_=asyncio.run(ai.model_json('输出文章',{},schema=ai.GeneratedArticle))
    assert count==2 and result['title']=='资料支持的标题'


def test_transient_upstream_disconnect_is_retried_once(monkeypatch):
    monkeypatch.setattr(ai,'get_config',lambda:ModelConfig('https://llm.example/v1','qwen-test','test-key'))
    count=0
    async def completion(settings,payload,timeout=100):
        nonlocal count
        count+=1
        if count==1:raise httpx.RemoteProtocolError('upstream disconnected')
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'},'finish_reason':'stop'}]})
    monkeypatch.setattr(ai,'completion',completion)
    result,_=asyncio.run(ai.model_json('结构化回复',{}))
    assert result['ok'] is True and count==2
