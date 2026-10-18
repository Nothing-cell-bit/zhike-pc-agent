import json
import sqlite3

import pytest
from argon2 import PasswordHasher

from scripts.run_demo import MARKER, PASSWORD, ROOT, USERNAME, prepare_demo


def test_selected_demo_preserves_text_without_private_material(tmp_path):
    folder = tmp_path / 'demo'
    assert prepare_demo(folder, ROOT / 'samples/selected-works.json')
    with sqlite3.connect(folder / 'store.db') as connection:
        name, password, role = connection.execute('SELECT username,password,role FROM users').fetchone()
        assert name == USERNAME and role == 'staff'
        assert PasswordHasher().verify(password, PASSWORD)
        rows = connection.execute('SELECT content,report FROM works').fetchall()
        assert len(rows) == 2
        for raw, report in rows:
            content = json.loads(raw)
            assert content['source_type'] == 'sample'
            assert content['images'] == content['sources'] == []
            assert len(content['body']) > 300
            assert content['historical_verification']['status'] == 'passed'
            assert json.loads(report)['status'] == 'needs_review'
            assert not json.loads(report)['ima_verified']
        assert connection.execute('SELECT count(*) FROM sessions').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM conversations').fetchone()[0] == 0
    with sqlite3.connect(folder / 'knowledge/index.db') as connection:
        assert connection.execute('SELECT count(*) FROM images').fetchone()[0] == 0
        assert connection.execute('SELECT count(*) FROM products').fetchone()[0] == 2


def test_second_run_preserves_demo_edits_and_password(tmp_path):
    folder = tmp_path / 'demo'
    prepare_demo(folder, ROOT / 'samples/selected-works.json')
    with sqlite3.connect(folder / 'store.db') as connection:
        connection.execute("UPDATE users SET password='modified-password'")
        connection.execute("UPDATE works SET version=9")
    assert not prepare_demo(folder, ROOT / 'samples/selected-works.json')
    with sqlite3.connect(folder / 'store.db') as connection:
        assert connection.execute('SELECT password FROM users').fetchone()[0] == 'modified-password'
        assert connection.execute('SELECT min(version) FROM works').fetchone()[0] == 9


def test_unrelated_database_is_refused_unchanged(tmp_path):
    database = tmp_path / 'store.db'
    with sqlite3.connect(database) as connection:
        connection.execute('CREATE TABLE private_records(content TEXT)')
        connection.execute("INSERT INTO private_records VALUES('preserve')")
    before = database.read_bytes()
    with pytest.raises(ValueError, match='非演示'):
        prepare_demo(tmp_path, ROOT / 'samples/selected-works.json')
    assert database.read_bytes() == before


def test_demo_export_identifies_the_reduced_sample():
    from backend.marketing import unified_markdown
    package = json.loads((ROOT / 'samples/selected-works.json').read_text(encoding='utf8'))
    item = package['works'][0]
    content = {**item['content'], 'source_type': 'sample', 'images': [], 'sources': []}
    result = unified_markdown(content, item['brief'], {'status': 'needs_review'}, True)
    assert '公开历史样例' in result
    assert '未附原图及资料快照' in result
    assert '知识来源：ima' not in result
