"""ModelScope runtime adapter. No credentials, customers or source assets are shipped."""
import asyncio
import hashlib
import json
import os
import re
import sqlite3
from contextlib import closing
from pathlib import Path

from .cloud_config import apply_private_environment
apply_private_environment()

from argon2 import PasswordHasher
from sqlalchemy import select
from .db import init_db, Session, User, Conversation
from .knowledge import INDEX, stable
from .ima import ImaClient, LIBRARY_NAME
from .main import app as application
from .ai import delayed_analysis as original_analysis


class CloudHeaders:
    """Permit only the hosting site's iframe; retain application auth and origin checks."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        async def secured(message):
            if message['type'] == 'http.response.start':
                headers = []
                for key, value in message.get('headers', []):
                    if key.lower() == b'x-frame-options':
                        continue
                    if key.lower() == b'content-security-policy':
                        value = value.replace(b"frame-ancestors 'none'",
                            b'frame-ancestors https://modelscope.cn https://www.modelscope.cn')
                    if key.lower() == b'set-cookie':
                        value = re.sub(br'SameSite=[^;]+', b'SameSite=none', value, flags=re.I)
                        if not re.search(br'(?:^|;)\s*Secure(?:;|$)', value, re.I):
                            value += b'; Secure'
                        # CHIPS supports authenticated use in a cross-site Studio iframe.
                        if b'partitioned' not in value.lower():
                            value += b'; Partitioned'
                    headers.append((key, value))
                message = {**message, 'headers': headers}
            await send(message)
        await self.app(scope, receive, secured)


def admin_credentials():
    name = os.getenv('CLOUD_ADMIN_USERNAME', 'admin')
    password = os.getenv('CLOUD_ADMIN_PASSWORD', '')
    if not re.fullmatch(r'[A-Za-z0-9_-]{3,40}', name) or len(password) < 16:
        raise ValueError('Configure a private CLOUD_ADMIN_PASSWORD of at least 16 characters.')
    return name, password


def ensure_admin():
    init_db()
    with Session() as db:
        if db.scalar(select(User).where(User.role == 'admin')):
            return  # Never overwrite persistent users or reset their passwords on deployment.
        name, password = admin_credentials()
        if db.scalar(select(User).where(User.username == name)):
            raise ValueError('Cloud administrator name is already in use.')
        db.add(User(username=name, display_name='门店管理员',
                    password=PasswordHasher().hash(password), role='admin'))
        db.commit()


async def claimed_analysis(conversation_id, actor_id):
    # A public visitor cannot spend inference quota until a staff member accepts the chat.
    with Session() as db:
        conversation = db.get(Conversation, conversation_id)
        if not conversation or not conversation.owner_id:
            return
    await original_analysis(conversation_id, actor_id)


def write_catalog(index: Path, products):
    """Seed only names/paths obtained from ima; never fabricate product specifications."""
    if index.exists():
        return
    paths = [p['path'] for p in products]
    if len(paths) != len(set(paths)) or any(
        not p.startswith('P1-产品参数库/') or any(s in {'', '.', '..'} for s in p.split('/'))
        or '\\' in p or ':' in p for p in paths
    ):
        raise ValueError('Invalid or duplicated product directory.')
    if not products:
        raise ValueError('No product directories were found in ima.')
    index.parent.mkdir(parents=True, exist_ok=True)
    temporary = index.with_suffix('.building')
    temporary.unlink(missing_ok=True)
    # The file is private runtime state, not included in either Git repository or image.
    with closing(sqlite3.connect(temporary)) as db:
        db.executescript('''
          CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
          CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,title TEXT,category TEXT,product_id TEXT,body TEXT,sha256 TEXT,urls TEXT,version TEXT);
          CREATE TABLE chunks(id TEXT PRIMARY KEY,doc_id TEXT,heading TEXT,body TEXT);
          CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,doc_id UNINDEXED,body);
          CREATE TABLE products(id TEXT PRIMARY KEY,name TEXT,path TEXT,facts_id TEXT,summary TEXT);
          CREATE TABLE images(id TEXT PRIMARY KEY,product_id TEXT,path TEXT,name TEXT,url TEXT,source TEXT,description TEXT,width INTEGER,height INTEGER,version TEXT);
          CREATE TABLE prices(id TEXT PRIMARY KEY,body TEXT);
        ''')
        for product in products:
            pid = stable(product['path'])
            did = 'catalog-' + pid
            body = '尚未读取产品参数；新建营销任务后从 ima 检索对应资料和原图。'
            db.execute('INSERT INTO products VALUES(?,?,?,?,?)',
                       (pid, product['name'], product['path'], did, ''))
            db.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',
                       (did, product['path'] + '/目录说明', '产品目录说明', 'P1', pid,
                        body, hashlib.sha256(body.encode()).hexdigest(), '[]', 'cloud-catalog-v1'))
        for key, value in {'source':'ima_catalog', 'version':'cloud-catalog-v1',
                           'products':len(products), 'documents':0, 'images':0,
                           'ima_connected':False}.items():
            db.execute('INSERT INTO meta VALUES(?,?)', (key, json.dumps(value)))
        db.commit()
    temporary.replace(index)


async def discover_catalog():
    async with ImaClient() as client:
        bases = await client.listing('search_knowledge_base',
                                    {'query':LIBRARY_NAME, 'limit':20}, 'info_list')
        matches = [b for b in bases if b.get('kb_name', b.get('name')) == LIBRARY_NAME]
        if len(matches) != 1:
            raise ValueError('The configured account cannot uniquely locate the required ima library.')
        kb = matches[0].get('kb_id', matches[0].get('id'))
        async def children(folder=None):
            body = {'knowledge_base_id':kb, 'limit':50}
            if folder:
                body['folder_id'] = folder
            return await client.listing('get_knowledge_list', body, 'knowledge_list')
        entries = await children()
        wrappers = [e for e in entries if e.get('media_type') == 99 and e.get('title') == LIBRARY_NAME]
        if len(wrappers) == 1:
            entries = await children(wrappers[0]['media_id'])
        roots = [e for e in entries if e.get('media_type') == 99 and e.get('title') == 'P1-产品参数库']
        if len(roots) != 1:
            raise ValueError('ima product root was not found.')
        categories = await children(roots[0]['media_id'])
        products = []
        for category in categories:
            if category.get('media_type') != 99 or not re.match(r'^0[12]-', category.get('title', '')):
                continue
            for item in await children(category['media_id']):
                if item.get('media_type') != 99:
                    continue
                name = item['title']
                if '鸿蒙' in category['title'] and '鸿蒙' not in name:
                    name += '（鸿蒙版）'
                products.append({'path':'P1-产品参数库/'+category['title']+'/'+item['title'], 'name':name})
        return products


def bootstrap():
    ensure_admin()
    if not INDEX.exists():
        products = asyncio.run(asyncio.wait_for(discover_catalog(), timeout=150))
        write_catalog(INDEX, products)
    from . import main
    main.delayed_analysis = claimed_analysis
    print('Cloud initialization complete; private runtime state is retained.')


app = CloudHeaders(application)


if __name__ == '__main__':
    import uvicorn
    bootstrap()
    uvicorn.run(app, host='0.0.0.0', port=7860, workers=1)
