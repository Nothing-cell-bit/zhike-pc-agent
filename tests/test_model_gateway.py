import httpx
from fastapi.testclient import TestClient
from scripts.model_gateway import create_app

CONFIG={'token':'private-gateway-test-token','upstream_url':'http://private.invalid/v1','upstream_key':'private-upstream-test-key'}


def test_gateway_auth_and_route_allowlist():
    with TestClient(create_app(CONFIG,transport=httpx.MockTransport(lambda r:httpx.Response(200,json={})))) as c:
        assert c.get('/v1/models').status_code==401
        assert c.get('/v1/models',headers={'Authorization':'Bearer wrong'}).status_code==401
        assert c.get('/admin',headers={'Authorization':'Bearer '+CONFIG['token']}).status_code==404


def test_gateway_substitutes_upstream_credential_and_checks_model():
    calls=[]
    def upstream(request):
        calls.append(request)
        assert request.headers['Authorization']=='Bearer '+CONFIG['upstream_key']
        return httpx.Response(200,json={'choices':[{'message':{'content':'ok'}}]})
    with TestClient(create_app(CONFIG,transport=httpx.MockTransport(upstream))) as c:
        headers={'Authorization':'Bearer '+CONFIG['token']}
        assert c.post('/v1/chat/completions',headers=headers,json={'model':'qwen3.8-27b','messages':[],'max_tokens':20}).status_code==200
        assert c.post('/v1/chat/completions',headers=headers,json={'model':'other'}).status_code==400
        assert c.post('/v1/chat/completions',headers=headers,json={'model':'qwen3.8-27b','max_tokens':100000}).status_code==400
        assert len(calls)==1


def test_gateway_does_not_disclose_upstream_network_error():
    def upstream(request):raise httpx.ConnectError(CONFIG['upstream_url'])
    with TestClient(create_app(CONFIG,transport=httpx.MockTransport(upstream))) as c:
        r=c.get('/v1/models',headers={'Authorization':'Bearer '+CONFIG['token']})
        assert r.status_code==502
        assert CONFIG['upstream_url'] not in r.text
        assert CONFIG['upstream_key'] not in r.text


def test_gateway_rejects_oversize_request_before_forwarding():
    def upstream(request):raise AssertionError('Must not forward oversize data')
    with TestClient(create_app(CONFIG,transport=httpx.MockTransport(upstream))) as c:
        assert c.post('/v1/chat/completions',content=b'x'*250001,
            headers={'Authorization':'Bearer '+CONFIG['token']}).status_code==413
