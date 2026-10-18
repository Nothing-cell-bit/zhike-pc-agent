import json
import sqlite3

from backend import knowledge as kb


def test_product_prices_use_exact_identity_without_limit(tmp_path,monkeypatch):
    index=tmp_path/'index.db'
    monkeypatch.setattr(kb,'INDEX',index)
    monkeypatch.setattr(kb.knowledge,'document',lambda _: {})
    monkeypatch.setattr(kb.knowledge,'images',lambda _: [])
    with sqlite3.connect(index) as c:
        c.executescript('CREATE TABLE products(id TEXT,name TEXT,facts_id TEXT); CREATE TABLE documents(id TEXT,title TEXT,category TEXT,product_id TEXT); CREATE TABLE prices(body TEXT);')
        c.executemany('INSERT INTO products VALUES(?,?,?)',[
            ('harmony','HUAWEI MateBook 14（鸿蒙版）','facts'),
            ('pro','HUAWEI MateBook Pro','facts'),
        ])
        rows=[{'规范产品名称':'HUAWEI MateBook 14（鸿蒙版）','记录ID':str(n)} for n in range(15)]
        rows.extend([
            {'规范产品名称':'HUAWEI MateBook 14 酷睿 Ultra'},
            {'规范产品名称':'HUAWEI MateBook Pro S'},
            {'规范产品名称':'HUAWEI MateBook Pro（鸿蒙版）'},
            {'规范产品名称':'华为鼠标','条件摘要':'HUAWEI MateBook 14（鸿蒙版） HUAWEI MateBook Pro 搭配购'},
        ])
        c.executemany('INSERT INTO prices VALUES(?)',[(json.dumps(row,ensure_ascii=False),) for row in rows])
    harmony=kb.knowledge.product('harmony')['prices']
    assert len(harmony)==15
    assert {r['规范产品名称'] for r in harmony}=={'HUAWEI MateBook 14（鸿蒙版）'}
    assert kb.knowledge.product('pro')['prices']==[{'规范产品名称':'HUAWEI MateBook Pro（鸿蒙版）'}]
