"""ima integration tests use synthetic media and a network mock, never real credentials."""
import asyncio
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image


@pytest.fixture
def remote(tmp_path,monkeypatch):
    from backend import ima as module
    monkeypatch.setattr(module,'CACHE_ROOT',tmp_path)
    image=io.BytesIO();Image.new('RGB',(20,30),'green').save(image,format='PNG')
    calls=[]
    def item(mid,title,kind):return {'media_id':mid,'title':title,'media_type':kind}
    folders={None:[item('root','任德耀新建华为PC知识库',99)],'root':[item('p1','P1-产品参数库',99)],'p1':[item('os','01-鸿蒙电脑',99)],'os':[item('pc','HUAWEI MateBook 14',99)],'pc':[item('facts','产品事实.md',7),item('limits','卖点与限制.md',7),item('pictures','images',99)],'pictures':[item('pic','课堂学习.png',9)]}
    def handle(request):
        calls.append(request)
        if request.method=='GET':
            assert 'ima-openapi-apikey' not in request.headers
            if request.url.path.endswith('/pic'):return httpx.Response(200,content=image.getvalue(),headers={'content-type':'image/png'})
            body='# HUAWEI MateBook 14\n\n屏幕比例为3:2，系统为鸿蒙。' if request.url.path.endswith('/facts') else '# 卖点与限制\n\n专业软件请先核对系统支持。'
            return httpx.Response(200,content=body.encode())
        assert request.url.host=='ima.qq.com'
        assert request.headers['ima-openapi-apikey']=='test-secret'
        body=json.loads(request.content);api=request.url.path.rsplit('/',1)[-1]
        if api=='search_knowledge_base':data={'info_list':[{'kb_id':'kb','kb_name':'任德耀新建华为PC知识库'}],'is_end':True}
        elif api=='search_knowledge':data={'info_list':[]}
        elif api=='get_knowledge_list':data={'knowledge_list':folders[body.get('folder_id')],'is_end':True,'next_cursor':''}
        elif api=='get_media_info':data={'media_type':9 if body['media_id']=='pic' else 7,'url_info':{'url':'https://test.cos.ap-shanghai.myqcloud.com/'+body['media_id']}}
        else:raise AssertionError('Unexpected API')
        return httpx.Response(200,json={'code':0,'msg':'success','data':data})
    provider=module.ImaProvider(lambda:module.ImaClient('test-client','test-secret',transport=httpx.MockTransport(handle)))
    product={'id':'pc-id','name':'HUAWEI MateBook 14（鸿蒙版）','path':'P1-产品参数库/01-鸿蒙电脑/HUAWEI MateBook 14'}
    return module,provider,product,calls


def test_search_fallback_fetches_exact_product_and_immutable_evidence(remote):
    module,provider,product,calls=remote
    p,refs,sid=asyncio.run(provider.fetch_product(product,{'scene':'课堂学习','audience':'学生'}))
    assert refs and all(r['source_type']=='ima' for r in refs)
    assert p['images'][0]['source_type']=='ima'
    assert p['images'][0]['product_id']==product['id']
    loaded,original=module.load_snapshot(sid,product['id'])
    assert original==refs and loaded['name']==product['name']
    assert module.image_path(p['images'][0]['id']).is_file()
    assert any('/search_knowledge' in str(c.url) for c in calls)
    assert len([c for c in calls if c.url.path.endswith('/get_knowledge_list')])>=5
    public=json.dumps([refs,p['images']],ensure_ascii=False)
    assert 'test-secret' not in public and 'media_id' not in public and 'kb_id' not in public
    assert 'cos.ap-shanghai' not in public


def test_snapshot_rejects_cross_product_and_modified_image(remote):
    module,provider,product,_=remote
    p,refs,sid=asyncio.run(provider.fetch_product(product,{}))
    with pytest.raises(ValueError):module.load_snapshot(sid,'another-product')
    module.image_path(p['images'][0]['id']).write_bytes(b'changed')
    with pytest.raises(ValueError,match='完整性'):module.load_snapshot(sid,product['id'])
    with pytest.raises(ValueError):module.load_snapshot('../escape',product['id'])


def test_wrong_folder_never_falls_back_to_local_facts(remote):
    module,provider,product,_=remote
    product['path']='P1-产品参数库/01-鸿蒙电脑/不存在的型号'
    with pytest.raises(ValueError,match='完整型号'):asyncio.run(provider.fetch_product(product,{}))
    assert not list((module.CACHE_ROOT/'snapshots').glob('*.json'))


def test_auth_error_is_explained_without_leaking_secret():
    from backend.ima import ImaClient
    async def run():
        async with ImaClient('client','secret-value',transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'code':200002,'msg':'secret-value'}))) as c:
            await c.call('search_knowledge_base',{'query':'x'})
    with pytest.raises(ValueError,match='鉴权') as e:asyncio.run(run())
    assert 'secret-value' not in str(e.value)


@pytest.mark.parametrize('url',['http://example.com/x','https://evil.test/x','https://127.0.0.1/x','https://test.myqcloud.com@evil.test/x'])
def test_media_url_rejects_untrusted_destinations(url):
    from backend.ima import ImaClient
    async def run():
        async with ImaClient('client','secret',transport=httpx.MockTransport(lambda r:pytest.fail('must not send'))) as c:
            await c.download({'url':url})
    with pytest.raises(ValueError):asyncio.run(run())


def test_ima_export_labels_do_not_relabel_old_local_work():
    from backend.marketing import unified_markdown
    c={'title':'文章','body':'正文','source_type':'ima','knowledge_base_name':'比赛库','images':[]}
    text=unified_markdown(c,{}, {'status':'passed','ima_verified':True})
    assert '比赛库' in text and '本地 ZIP' not in text and '尚未验证' not in text
    assert '本地 ZIP' in unified_markdown({'title':'旧稿','body':'正文'}, {}, {'status':'passed'})


def test_ima_first_failure_falls_back_as_a_whole_with_reason(clients,monkeypatch):
    from backend import ai
    from backend.knowledge import knowledge
    monkeypatch.setattr(ai,'MARKETING_SOURCE','ima_first')
    async def failed(*a,**kw):raise ValueError('ima 连接失败')
    monkeypatch.setattr(ai.ima,'fetch_product',failed)
    p,refs,metadata=asyncio.run(ai.marketing_evidence({'product_id':knowledge.products()[0]['id'],'platform':'朋友圈'}))
    assert metadata['source_type']=='local_zip' and metadata['fallback_reason']=='ima 连接失败'
    assert refs and not any(im['id'].startswith('ima-') for im in p['images'])


def test_strict_ima_does_not_fall_back(clients,monkeypatch):
    from backend import ai
    from backend.knowledge import knowledge
    monkeypatch.setattr(ai,'MARKETING_SOURCE','ima')
    async def failed(*a,**kw):raise ValueError('ima 连接失败')
    monkeypatch.setattr(ai.ima,'fetch_product',failed)
    with pytest.raises(ValueError):asyncio.run(ai.marketing_evidence({'product_id':knowledge.products()[0]['id'],'platform':'朋友圈'}))


def test_ima_work_images_edit_export_and_verification_use_snapshot(remote,clients,monkeypatch):
    from backend import ai
    from backend.db import Work,WorkVersion,Session
    from backend.knowledge import knowledge
    module,provider,product,_=remote;admin,staff,guest,_=clients
    local=next(p for p in knowledge.products() if '14（鸿蒙' in p['name']);product['id']=local['id']
    p,refs,sid=asyncio.run(provider.fetch_product(product,{}));iid=p['images'][0]['id']
    content={'title':'课堂学习','body':'屏幕比例为3:2。','cta':'到店看看','source_type':'ima','source_snapshot':sid,'knowledge_base_name':module.LIBRARY_NAME,'images':p['images'],'sources':refs}
    brief={'product_id':product['id'],'platform':'朋友圈'}
    with Session() as s:
        w=Work(actor_id=admin.get('/api/me').json()['user']['id'],brief=json.dumps(brief),content=json.dumps(content),report=json.dumps({'status':'passed','ima_verified':True}));s.add(w);s.flush();s.add(WorkVersion(work_id=w.id,version=1,content=w.content,report=w.report));s.commit();wid=w.id
    assert admin.get('/api/knowledge/images/'+iid).status_code==200
    assert guest.get('/api/knowledge/images/'+iid).status_code==401
    work=admin.get('/api/works/'+wid).json();assert work['available_images'][0]['id']==iid
    assert 'ima共享知识库' in admin.get('/api/works/'+wid+'/export?format=html').text
    wrong=knowledge.images(product['id'])[0]['id']
    edit={'expected_version':1,'title':'修订稿','body':'屏幕比例为3:2。','image_ids':[wrong]}
    assert admin.patch('/api/works/'+wid,json=edit,headers={'X-Store-Request':'1'}).status_code==400
    edit['image_ids']=[iid]
    assert admin.patch('/api/works/'+wid,json=edit,headers={'X-Store-Request':'1'}).status_code==200
    async def clean(instruction,data,*args,**kwargs):
        assert data['evidence'][0]['source_type']=='ima'
        return {'issues':[],'pending':[],'claims':[{'text':'屏幕比例为3:2','source_id':refs[0]['id']}]},{}
    monkeypatch.setattr(ai,'model_json',clean)
    report=asyncio.run(ai.verify(content,brief));assert report['ima_verified'] and report['status']=='passed'


def test_ima_generation_records_source_and_keeps_model_evidence_ima(remote,clients,monkeypatch):
    from backend import ai
    from backend.db import Job,Session,Work
    from backend.knowledge import knowledge
    module,provider,product,_=remote;admin,*_=clients
    local=next(p for p in knowledge.products() if '14（鸿蒙' in p['name']);product['id']=local['id']
    p,refs,sid=asyncio.run(provider.fetch_product(product,{}))
    monkeypatch.setattr(ai,'MARKETING_SOURCE','ima_first')
    async def fetch(*args):return p,refs,sid
    monkeypatch.setattr(ai.ima,'fetch_product',fetch)
    async def model(instruction,data,*args,schema=None,**kwargs):
        if schema is ai.GeneratedArticle:
            assert data['source_type']=='ima' and not data['writing_reference']
            return {'title':'课堂学习','body':'屏幕比例为3:2。','cta':'到店体验','strategy':'课堂阅读'},{}
        return {'issues':[],'pending':[],'claims':[{'text':'屏幕比例为3:2','source_id':refs[0]['id']}]},{}
    monkeypatch.setattr(ai,'model_json',model)
    with Session() as s:
        j=Job(kind='generate',actor_id=admin.get('/api/me').json()['user']['id']);s.add(j);s.commit();jid=j.id
    result=asyncio.run(ai.generate({'product_id':product['id'],'audience':'学生','scene':'课堂','goal':'到店','platform':'朋友圈'},jid))
    with Session() as s:
        w=s.get(Work,result['work_id']);saved=json.loads(w.content)
        assert saved['source_type']=='ima' and saved['source_snapshot']==sid
        assert all(i['id'].startswith('ima-') for i in saved['images'])
