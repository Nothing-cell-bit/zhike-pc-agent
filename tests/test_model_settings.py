import asyncio
import json
import socket

import httpx
import pytest

from backend import ai

HEADERS = {'X-Store-Request': '1'}
BODY = {'base_url': 'https://provider.example/v1', 'model': 'custom-chat', 'api_key': 'private-test-value'}


def test_model_settings_admin_boundary(clients):
    admin, staff, customer, _ = clients
    assert admin.get('/api/admin/text-model').status_code == 200
    for client in (staff, customer):
        assert client.get('/api/admin/text-model').status_code in (401, 403)
        assert client.put('/api/admin/text-model', json=BODY, headers=HEADERS).status_code in (401, 403)


def test_private_persistence_blank_key_and_reset(clients, monkeypatch, tmp_path):
    from backend import model_settings as ms
    monkeypatch.setattr(ms, 'CONFIG_PATH', tmp_path/'text-model.json')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    admin = clients[0]
    saved = admin.put('/api/admin/text-model', json=BODY, headers=HEADERS)
    assert saved.status_code == 200
    assert 'private-test-value' not in saved.text
    assert saved.json()['key_configured'] and saved.json()['source'] == 'custom'
    assert ms.get_config().key == BODY['api_key']
    assert json.loads(ms.CONFIG_PATH.read_text())['api_key'] == BODY['api_key']
    changed = admin.put('/api/admin/text-model', json={**BODY, 'model': 'new-chat', 'api_key': ''}, headers=HEADERS)
    assert changed.status_code == 200 and ms.get_config().key == BODY['api_key']
    assert ms.get_config().model == 'new-chat'
    # A blank key must not send an old credential to a different provider.
    assert admin.put('/api/admin/text-model', json={**BODY, 'base_url': 'https://other.example/v1', 'api_key': ''}, headers=HEADERS).status_code == 400
    assert 'private-test-value' not in admin.get('/api/admin/text-model').text
    assert 'private-test-value' not in admin.get('/api/admin/audit').text
    assert admin.post('/api/admin/text-model/reset', headers=HEADERS).status_code == 200
    assert not ms.CONFIG_PATH.exists() and ms.get_config().source == 'environment'


@pytest.mark.parametrize('url', ['http://provider.example/v1', 'https://127.0.0.1/v1', 'https://169.254.169.254/v1', 'https://[::1]/v1', 'https://u:p@provider.example/v1', 'https://provider.example/v1?key=oops', 'https://provider.example/v1/chat/completions'])
def test_reject_unsafe_urls(clients, monkeypatch, tmp_path, url):
    from backend import model_settings as ms
    monkeypatch.setattr(ms, 'CONFIG_PATH', tmp_path/'text-model.json')
    assert clients[0].put('/api/admin/text-model', json={**BODY, 'base_url': url}, headers=HEADERS).status_code == 400
    assert not ms.CONFIG_PATH.exists()


def test_runtime_model_used_and_public_dns_pinned(clients, monkeypatch, tmp_path):
    from backend import model_settings as ms
    monkeypatch.setattr(ms, 'CONFIG_PATH', tmp_path/'text-model.json')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    admin = clients[0]
    assert admin.put('/api/admin/text-model', json=BODY, headers=HEADERS).status_code == 200
    calls = []
    def respond(request):
        calls.append(request)
        return httpx.Response(200, json={'choices':[{'message':{'content':'{"ok":true}'}}], 'usage':{'total_tokens':3}})
    original = httpx.AsyncClient
    monkeypatch.setattr(httpx, 'AsyncClient', lambda **kw: original(transport=httpx.MockTransport(respond)))
    result, usage = asyncio.run(ai.model_json('JSON', {}))
    assert result == {'ok': True} and usage['model'] == BODY['model']
    request = calls[0]
    assert request.url.host == '93.184.216.34' and request.headers['host'] == 'provider.example'
    assert request.extensions['sni_hostname'] == 'provider.example'
    assert json.loads(request.content)['model'] == BODY['model']
    assert 'chat_template_kwargs' not in json.loads(request.content)
    test = admin.post('/api/admin/check-model', headers=HEADERS)
    assert test.status_code == 200 and test.json()['ok']
    assert len(calls) == 2 and calls[-1].url.path == '/v1/chat/completions'
    # DNS changes cannot make subsequent requests reach a private address.
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('10.0.0.1', 443))])
    with pytest.raises(ValueError, match='公网'):
        asyncio.run(ai.model_json('JSON', {}))
    assert len(calls) == 2


def test_qwen_non_thinking_is_optional_and_persisted(clients, monkeypatch, tmp_path):
    from backend import model_settings as ms
    monkeypatch.setattr(ms, 'CONFIG_PATH', tmp_path/'text-model.json')
    monkeypatch.setattr(socket, 'getaddrinfo', lambda *a, **k: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))])
    admin=clients[0]
    value={**BODY,'model':'qwen3.8-27b','disable_thinking':True}
    saved=admin.put('/api/admin/text-model',json=value,headers=HEADERS)
    assert saved.status_code==200 and saved.json()['disable_thinking']
    calls=[]
    def respond(request):
        calls.append(json.loads(request.content))
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"ok":true}'}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond)))
    asyncio.run(ai.model_json('JSON',{}))
    assert calls[0]['chat_template_kwargs']=={'enable_thinking':False}
