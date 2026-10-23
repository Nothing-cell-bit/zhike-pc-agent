import asyncio
import json
import socket

import httpx
import pytest

HEADERS={'X-Store-Request':'1'}
BODY={'base_url':'https://images.example/v1','model':'custom-image-model','api_key':'private-image-test-value'}


def test_image_settings_require_admin(clients):
    admin,staff,customer,_=clients
    assert admin.get('/api/admin/image-model').status_code==200
    for client in [staff,customer]:
        assert client.get('/api/admin/image-model').status_code in (401,403)
        assert client.put('/api/admin/image-model',json=BODY,headers=HEADERS).status_code in (401,403)
        assert client.post('/api/admin/image-model/reset',headers=HEADERS).status_code in (401,403)


@pytest.fixture
def isolated(monkeypatch,tmp_path):
    from backend import image_settings as service
    monkeypatch.setattr(service,'CONFIG_PATH',tmp_path/'image-model.json')
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('93.184.216.34',443))])
    return service


def test_save_redaction_persistence_blank_key_and_reset(clients,isolated):
    admin=clients[0]
    text_before=admin.get('/api/admin/text-model').json()
    response=admin.put('/api/admin/image-model',json=BODY,headers=HEADERS)
    assert response.status_code==200
    assert 'api_key' not in response.json() and BODY['api_key'] not in response.text
    assert response.headers['cache-control']=='no-store'
    assert isolated.get_config().key==BODY['api_key']
    assert json.loads(isolated.CONFIG_PATH.read_text())['model']==BODY['model']
    response=admin.put('/api/admin/image-model',json={**BODY,'api_key':''},headers=HEADERS)
    assert response.status_code==200 and isolated.get_config().key==BODY['api_key']
    assert admin.put('/api/admin/image-model',json={**BODY,'base_url':'https://other.example/v1','api_key':''},headers=HEADERS).status_code==400
    assert admin.get('/api/admin/status').json()['image']['model']==BODY['model']
    assert admin.get('/api/admin/text-model').json()==text_before
    assert BODY['api_key'] not in admin.get('/api/admin/audit').text
    assert admin.post('/api/admin/image-model/reset',headers=HEADERS).status_code==200
    assert not isolated.CONFIG_PATH.exists() and isolated.get_config().source=='environment'


@pytest.mark.parametrize('url',['http://images.example/v1','https://u:p@images.example/v1','https://images.example/v1?key=secret','https://images.example/v1/images/generations','https://images.example/v1/tasks'])
def test_reject_unsafe_base(clients,isolated,url):
    assert clients[0].put('/api/admin/image-model',json={**BODY,'base_url':url},headers=HEADERS).status_code==400
    assert not isolated.CONFIG_PATH.exists()


def test_catalog_test_is_read_only_and_pins_public_dns(clients,isolated,monkeypatch):
    admin=clients[0]
    assert admin.put('/api/admin/image-model',json=BODY,headers=HEADERS).status_code==200
    calls=[]
    def respond(request):
        calls.append(request)
        return httpx.Response(200,json={'data':[{'id':BODY['model']}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(respond)))
    response=admin.post('/api/admin/check-image-model',headers=HEADERS)
    assert response.json()['ok'] is True
    request=calls[0]
    assert request.method=='GET' and request.url.path=='/v1/models'
    assert request.url.host=='93.184.216.34' and request.headers['host']=='images.example'
    assert request.extensions['sni_hostname']=='images.example'
    assert request.headers['authorization']=='Bearer '+BODY['api_key']
    monkeypatch.setattr(socket,'getaddrinfo',lambda *a,**kw:[(socket.AF_INET,socket.SOCK_STREAM,6,'',('10.0.0.1',443))])
    response=admin.post('/api/admin/check-image-model',headers=HEADERS)
    assert not response.json()['ok'] and len(calls)==1


def test_old_job_cannot_send_credentials_to_changed_service(isolated):
    isolated.save_config(BODY)
    first=isolated.get_config();payload={'model':first.model}
    isolated.bind_job(payload,first)
    assert BODY['api_key'] not in json.dumps(payload)
    isolated.save_config({**BODY,'base_url':'https://other.example/v1','api_key':'another-private-test-value'})
    with pytest.raises(ValueError,match='配置已变更'):
        isolated.bind_job(payload,isolated.get_config(),remote=True)


@pytest.mark.parametrize('status',[401,403,404,429,500])
def test_image_check_does_not_echo_provider_errors(clients,isolated,monkeypatch,status):
    admin=clients[0];assert admin.put('/api/admin/image-model',json=BODY,headers=HEADERS).status_code==200
    original=httpx.AsyncClient
    monkeypatch.setattr(httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(lambda request:httpx.Response(status,json={'detail':BODY['api_key']}))))
    response=admin.post('/api/admin/check-image-model',headers=HEADERS)
    assert response.status_code==200 and not response.json()['ok']
    assert BODY['api_key'] not in response.text
