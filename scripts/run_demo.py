"""Open two selected historical text examples in an isolated, local demo workspace."""
import argparse
import hashlib
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
USERNAME = 'demo_staff'
# This is an intentionally public demo credential, never an existing user's password.
PASSWORD = 'ZhikeDemo2026!'
MARKER = 'zhike-public-demo-v1'


def prepare_demo(folder, samples):
    """Create a dedicated database; refuse existing data unless it is this demo."""
    from argon2 import PasswordHasher
    from sqlalchemy import create_engine
    from sqlalchemy.orm import Session
    from backend.db import Base, Setting, User, Work, WorkVersion

    folder = Path(folder).resolve()
    database = folder / 'store.db'
    if database.exists():
        with sqlite3.connect(database.as_uri() + '?mode=ro', uri=True) as connection:
            try:
                marker = connection.execute("SELECT value FROM settings WHERE key='public_demo'").fetchone()
            except sqlite3.DatabaseError:
                marker = None
        if not marker or marker[0] != MARKER:
            raise ValueError('该目录包含非演示数据库，不写入或覆盖。')
        return False

    package = json.loads(Path(samples).read_text(encoding='utf-8'))
    if package.get('format') != MARKER or len(package.get('works', [])) != 2:
        raise ValueError('演示样例格式不正确。')
    folder.mkdir(parents=True, exist_ok=True)
    engine = create_engine('sqlite:///' + database.as_posix())
    try:
        Base.metadata.create_all(engine)
        with Session(engine) as session:
            actor = User(id='public-demo-staff', username=USERNAME, display_name='演示顾问',
                         password=PasswordHasher().hash(PASSWORD), role='staff')
            session.add(actor)
            session.add(Setting(key='public_demo', value=MARKER))
            for item in package['works']:
                content = {**item['content'], 'source_type': 'sample', 'images': [], 'sources': [],
                           'claims': [], 'pending': ['公开样例未附原始图片和资料快照，仅供阅读与草稿导出。'],
                           'historical_verification': item['historical_verification'],
                           'sample_image_plan': item['image_plan']}
                report = {'status': 'needs_review', 'blocked': False, 'issues': [],
                          'pending': content['pending'], 'claims': [], 'ima_verified': False}
                brief = {**item['brief'], 'product_id': item['id']}
                work = Work(id=item['id'], actor_id=actor.id, brief=json.dumps(brief, ensure_ascii=False),
                            content=json.dumps(content, ensure_ascii=False),
                            report=json.dumps(report, ensure_ascii=False), version=1)
                session.add(work)
                session.add(WorkVersion(work_id=work.id, version=1, content=work.content, report=work.report))
            session.commit()

        # A product-name catalog keeps the existing UI usable without distributing the private library.
        catalog = folder / 'knowledge/index.db'
        catalog.parent.mkdir(parents=True, exist_ok=True)
        with sqlite3.connect(catalog) as connection:
            connection.executescript('''
              CREATE TABLE meta(key TEXT PRIMARY KEY,value TEXT);
              CREATE TABLE products(id TEXT PRIMARY KEY,name TEXT,path TEXT,facts_id TEXT,summary TEXT);
              CREATE TABLE documents(id TEXT PRIMARY KEY,path TEXT,title TEXT,category TEXT,product_id TEXT,body TEXT,sha256 TEXT,urls TEXT,version TEXT);
              CREATE TABLE chunks(id TEXT PRIMARY KEY,doc_id TEXT,heading TEXT,body TEXT);
              CREATE VIRTUAL TABLE search USING fts5(id UNINDEXED,doc_id UNINDEXED,body);
              CREATE TABLE images(id TEXT PRIMARY KEY,product_id TEXT,path TEXT,name TEXT,url TEXT,source TEXT,description TEXT,width INTEGER,height INTEGER,version TEXT);
              CREATE TABLE prices(id TEXT PRIMARY KEY,body TEXT);
            ''')
            for item in package['works']:
                body = '公开演示目录，仅提供产品名称；不包含可供新创作核验的知识库原件。'
                doc_id = item['id'] + '-notice'
                connection.execute('INSERT INTO products VALUES(?,?,?,?,?)',
                                   (item['id'], item['content']['product_name'], '公开演示/' + item['id'], doc_id, body))
                connection.execute('INSERT INTO documents VALUES(?,?,?,?,?,?,?,?,?)',
                                   (doc_id, '公开演示/' + item['id'], '演示资料说明', 'P0', item['id'], body,
                                    hashlib.sha256(body.encode()).hexdigest(), '[]', MARKER))
            for key, value in {'source': 'public_demo', 'version': MARKER, 'products': 2, 'documents': 2,
                               'images': 0, 'ima_connected': False}.items():
                connection.execute('INSERT INTO meta VALUES(?,?)', (key, json.dumps(value)))
        return True
    finally:
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--prepare-only', action='store_true', help='只准备演示数据，不启动服务')
    parser.add_argument('--port', type=int, default=8767)
    args = parser.parse_args()
    if not 1024 <= args.port <= 65535:
        parser.error('端口应为 1024-65535。')
    folder = ROOT / 'tmp/public-demo'
    # Set before importing any backend module. Existing .env values cannot override these.
    os.environ.update(STORE_DATA_DIR=str(folder), TEXT_API_BASE='', TEXT_API_KEY='',
                      IMA_OPENAPI_CLIENTID='', IMA_OPENAPI_APIKEY='', MODELSCOPE_IMAGE_API_KEY='',
                      MARKETING_KNOWLEDGE_SOURCE='local_zip', COOKIE_SECURE='false')
    sys.path.insert(0, str(ROOT))
    created = prepare_demo(folder, ROOT / 'samples/selected-works.json')
    print('演示数据已创建。' if created else '使用已有演示数据；不会重置账号或覆盖修改。', flush=True)
    print(f'本地客服入口：http://127.0.0.1:{args.port}/staff', flush=True)
    print(f'公开演示用户名：{USERNAME}；初始密码：{PASSWORD}', flush=True)
    if args.prepare_only:
        return
    if not (ROOT / 'frontend/dist/index.html').exists():
        raise SystemExit('请先执行 npm ci --prefix frontend 与 npm run build --prefix frontend。')
    import uvicorn
    uvicorn.run('backend.main:app', host='127.0.0.1', port=args.port, workers=1)


if __name__ == '__main__':
    main()
