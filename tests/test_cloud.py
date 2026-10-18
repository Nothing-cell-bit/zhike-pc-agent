import json
import sqlite3
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
