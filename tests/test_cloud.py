import json
import sqlite3
import asyncio
import pytest
from fastapi.testclient import TestClient
from backend import cloud
from backend.main import app
from .conftest import post


def test_cloud_embedding_preserves_auth_and_csrf(clients):
    with TestClient(cloud.CloudHeaders(app), base_url='https://work.example') as client:
        response = post(client, '/auth/guest', {'name': '云端访客'})
        assert response.status_code == 200
        cookie = response.headers['set-cookie']
        assert 'Secure' in cookie and 'HttpOnly' in cookie
        assert 'SameSite=none' in cookie and 'Partitioned' in cookie
        policy = response.headers['content-security-policy']
        assert 'frame-ancestors https://modelscope.cn https://www.modelscope.cn' in policy
        assert 'x-frame-options' not in response.headers
        assert client.get('/api/admin/status').status_code == 403
        assert client.post('/api/auth/guest',json={'name':'x'},headers={
            'Origin':'https://evil.example','X-Store-Request':'1'}).status_code == 403


def test_cloud_catalog_has_no_fabricated_facts_and_is_idempotent(tmp_path):
    index = tmp_path / 'knowledge' / 'index.db'
    products = [{'path':'P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook 14','name':'HUAWEI MateBook 14（鸿蒙版）'}]
    cloud.write_catalog(index, products)
    with sqlite3.connect(index) as db:
        assert db.execute('select count(*) from products').fetchone()[0] == 1
        assert db.execute('select count(*) from images').fetchone()[0] == 0
        assert '尚未读取' in db.execute('select body from documents').fetchone()[0]
    before = index.read_bytes()
    cloud.write_catalog(index, [])
    assert index.read_bytes() == before


def test_catalog_rejects_unsafe_or_duplicate_paths(tmp_path):
    for items in [[{'path':'../private','name':'x'}],
                  [{'path':'P1-产品参数库/01-鸿蒙电脑/a','name':'a'}]*2]:
        with pytest.raises(ValueError):
            cloud.write_catalog(tmp_path/'index.db',items)


def test_bootstrap_does_not_replace_existing_admin(clients,monkeypatch):
    monkeypatch.setenv('CLOUD_ADMIN_USERNAME','cloud_admin')
    monkeypatch.setenv('CLOUD_ADMIN_PASSWORD','a-new-private-password')
    from backend.db import Session,User
    from sqlalchemy import select
    cloud.ensure_admin()
    with Session() as db:
        assert db.scalar(select(User).where(User.username=='cloud_admin')) is None


def test_bootstrap_requires_private_admin_password(monkeypatch):
    monkeypatch.delenv('CLOUD_ADMIN_PASSWORD',raising=False)
    with pytest.raises(ValueError):
        cloud.admin_credentials()


def test_live_directory_discovery_uses_account_library_and_category(monkeypatch):
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def listing(self,api,body,field):
            if api=='search_knowledge_base':return [{'kb_name':cloud.LIBRARY_NAME,'kb_id':'kb'}]
            assert body['knowledge_base_id']=='kb'
            return {
                None:[{'title':cloud.LIBRARY_NAME,'media_type':99,'media_id':'wrapper'}],
                'wrapper':[{'title':'P1-产品参数库','media_type':99,'media_id':'p1'}],
                'p1':[{'title':'01-鸿蒙电脑','media_type':99,'media_id':'harmony'},
                      {'title':'08-价格','media_type':99,'media_id':'price'}],
                'harmony':[{'title':'HUAWEI MateBook 14','media_type':99,'media_id':'product'},
                           {'title':'导航.md','media_type':7,'media_id':'nav'}],
            }[body.get('folder_id')]
    monkeypatch.setattr(cloud,'ImaClient',Client)
    result=asyncio.run(cloud.discover_catalog())
    assert result==[{'name':'HUAWEI MateBook 14（鸿蒙版）',
                    'path':'P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook 14'}]


def test_missing_library_cannot_seed_fake_products(monkeypatch):
    class Client:
        async def __aenter__(self):return self
        async def __aexit__(self,*args):pass
        async def listing(self,*args):return []
    monkeypatch.setattr(cloud,'ImaClient',Client)
    with pytest.raises(ValueError):asyncio.run(cloud.discover_catalog())


def test_first_admin_uses_private_secret_and_catalog_bootstraps_once(tmp_path,monkeypatch):
    from sqlalchemy import create_engine,select
    from sqlalchemy.orm import sessionmaker
    from backend.db import Base,User
    from argon2 import PasswordHasher
    engine=create_engine('sqlite://')
    Base.metadata.create_all(engine)
    sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(cloud,'Session',sessions)
    monkeypatch.setattr(cloud,'init_db',lambda:None)
    monkeypatch.setenv('CLOUD_ADMIN_USERNAME','cloud_admin')
    monkeypatch.setenv('CLOUD_ADMIN_PASSWORD','only-a-private-test-password')
    calls=[]
    async def discover():
        calls.append(1)
        return [{'path':'P1-产品参数库/02-Windows电脑/Test','name':'Test'}]
    monkeypatch.setattr(cloud,'discover_catalog',discover)
    monkeypatch.setattr(cloud,'INDEX',tmp_path/'knowledge/index.db')
    cloud.bootstrap()
    cloud.bootstrap()
    assert calls==[1]
    with sessions() as db:
        admin=db.scalar(select(User))
        assert admin.role=='admin'
        assert PasswordHasher().verify(admin.password,'only-a-private-test-password')
    engine.dispose()


def test_unclaimed_public_chat_does_not_spend_model_quota(clients,monkeypatch):
    from backend.db import Session,Conversation
    calls=[]
    async def analyze(cid,actor):calls.append((cid,actor))
    monkeypatch.setattr(cloud,'original_analysis',analyze)
    with Session() as db:
        c=Conversation(customer_id='visitor',customer_name='访客')
        db.add(c);db.commit();cid=c.id
    asyncio.run(cloud.claimed_analysis(cid,'visitor'))
    assert calls==[]
    with Session() as db:
        db.get(Conversation,cid).owner_id='staff';db.commit()
    asyncio.run(cloud.claimed_analysis(cid,'visitor'))
    assert calls==[(cid,'visitor')]
