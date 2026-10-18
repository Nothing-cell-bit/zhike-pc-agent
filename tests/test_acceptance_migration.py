import json
import sqlite3

import pytest

from scripts.migrate_ima_acceptance import migrate


def database(folder):
    folder.mkdir()
    with sqlite3.connect(folder/'store.db') as c:
        c.executescript('''
        CREATE TABLE users(id TEXT PRIMARY KEY,password TEXT);
        CREATE TABLE works(id TEXT PRIMARY KEY,actor_id TEXT,brief TEXT,content TEXT,report TEXT,version INTEGER);
        CREATE TABLE work_versions(id TEXT PRIMARY KEY,work_id TEXT,version INTEGER,content TEXT,report TEXT);
        CREATE TABLE jobs(id TEXT PRIMARY KEY,actor_id TEXT,target_id TEXT,result TEXT,status TEXT);
        CREATE TABLE audit(id TEXT PRIMARY KEY,actor_id TEXT,target TEXT,action TEXT);
        CREATE TABLE assets(id TEXT PRIMARY KEY,actor_id TEXT,path TEXT,metadata_json TEXT);
        CREATE TABLE messages(id TEXT PRIMARY KEY,content TEXT);
        CREATE TABLE sessions(id TEXT PRIMARY KEY,user_id TEXT);
        ''')
        c.execute('INSERT INTO users VALUES(?,?)',('admin','original-secret-hash'))
        c.execute('INSERT INTO messages VALUES(?,?)',('customer-message','original chat'))
        c.execute('INSERT INTO sessions VALUES(?,?)',('original-session','admin'))


@pytest.fixture
def pair(tmp_path):
    source=tmp_path/'source';target=tmp_path/'target'
    database(source);database(target)
    content=json.dumps({'source_type':'local_zip','images':[],'sources':[]})
    with sqlite3.connect(source/'store.db') as c:
        c.execute('UPDATE users SET password=?',('must-not-copy',))
        c.execute('INSERT INTO works VALUES(?,?,?,?,?,?)',('new','admin','{}',content,'{"status":"passed"}',2))
        for version in [1,2]:c.execute('INSERT INTO work_versions VALUES(?,?,?,?,?)',('v'+str(version),'new',version,content,'{"status":"passed"}' if version==2 else '{}'))
        c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',('job','admin','new','{"work_id":"new"}','completed'))
        c.execute('INSERT INTO audit VALUES(?,?,?,?)',('edit','admin','new','edit_work'))
    return source,target


def test_migration_is_additive_and_idempotent(pair):
    source,target=pair
    plan=migrate(source,target,['new'],dry_run=True)
    assert plan['inserted']['works']==1
    with sqlite3.connect(target/'store.db') as c:assert c.execute('select count(*) from works').fetchone()[0]==0
    report=migrate(source,target,['new'])
    assert report['original_rows_unchanged'] and report['inserted']['work_versions']==2
    with sqlite3.connect(target/'store.db') as c:
        assert c.execute('select password from users').fetchone()[0]=='original-secret-hash'
        assert c.execute('select content from messages').fetchone()[0]=='original chat'
        assert c.execute('select id from sessions').fetchone()[0]=='original-session'
    repeated=migrate(source,target,['new'])
    assert all(value==0 for value in repeated['inserted'].values())


def test_conflicting_work_aborts_without_overwrite(pair):
    source,target=pair
    with sqlite3.connect(target/'store.db') as c:c.execute('INSERT INTO works VALUES(?,?,?,?,?,?)',('new','admin','{}','{"title":"original"}','{}',1))
    with pytest.raises(ValueError,match='冲突'):migrate(source,target,['new'])
    with sqlite3.connect(target/'store.db') as c:
        assert c.execute('select content from works').fetchone()[0]=='{"title":"original"}'
        assert c.execute('select count(*) from work_versions').fetchone()[0]==0


def test_active_job_and_missing_actor_are_rejected(pair):
    source,target=pair
    with sqlite3.connect(target/'store.db') as c:c.execute('INSERT INTO jobs VALUES(?,?,?,?,?)',('busy','admin','','{}','running'))
    with pytest.raises(ValueError,match='运行'):migrate(source,target,['new'])
    with sqlite3.connect(target/'store.db') as c:
        c.execute('DELETE FROM jobs');c.execute('DELETE FROM users')
    with pytest.raises(ValueError,match='账号'):migrate(source,target,['new'])
