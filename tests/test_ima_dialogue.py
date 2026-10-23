import asyncio
from .test_ima import remote


def test_dialogue_retrieval_reads_exact_product_facts_without_images(remote):
    from backend import ima_dialogue
    module,provider,product,calls=remote
    result=asyncio.run(ima_dialogue.retrieve(product,'软件适配要求',provider.client_factory))
    assert result['sources'] and all(s['source_type']=='ima' for s in result['sources'])
    assert result['status']=='retrieved'
    assert not any('pic' in str(r.url) for r in calls)
    count=len(calls)
    cached=asyncio.run(ima_dialogue.retrieve(product,'另一个问题',provider.client_factory))
    assert cached['status']=='cached' and len(calls)==count


def test_dialogue_cache_rejects_tampered_original(remote):
    from backend import ima_dialogue
    import json
    module,provider,product,calls=remote
    asyncio.run(ima_dialogue.retrieve(product,'用途',provider.client_factory))
    path=next((module.CACHE_ROOT/'dialogue').glob('*.json'))
    data=json.loads(path.read_text(encoding='utf-8'));data['sources'][0]['excerpt']='伪造事实'
    path.write_text(json.dumps(data),encoding='utf-8')
    count=len(calls)
    result=asyncio.run(ima_dialogue.retrieve(product,'用途',provider.client_factory))
    assert result['status']=='retrieved' and len(calls)>count
    assert all(s['excerpt']!='伪造事实' for s in result['sources'])


def test_selection_uses_current_ima_facts_without_fetching_entire_catalog(monkeypatch):
    from backend import dialogue_catalog as catalog
    monkeypatch.setattr(catalog,'MARKETING_SOURCE','ima_first')
    monkeypatch.setattr(catalog.knowledge,'products',lambda:[{'id':'p','name':'设备'}])
    monkeypatch.setattr(catalog.knowledge,'product',lambda _: {'facts':{'id':'local','title':'产品事实','body':'本地事实','sha256':'h'},'prices':[]})
    calls=[]
    async def info(ids,query=''):
        calls.append(ids)
        return {'sources':[{'id':'current-fact','product_id':'p','title':'产品事实.md','excerpt':'本次 ima 确认的事实','source_type':'ima'}],
                'retrieval':[{'status':'retrieved'}]}
    monkeypatch.setattr(catalog,'load_information',info)
    result=asyncio.run(catalog.load_options(['p']))
    assert calls==[['p']] and result['options'][0]['source_ids']==['current-fact']
    calls.clear()
    asyncio.run(catalog.load_options())
    assert calls==[]
