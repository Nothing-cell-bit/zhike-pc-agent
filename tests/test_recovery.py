"""Regression gates for the unfinished spec flows; no external model calls."""
import asyncio
import json
import sqlite3
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

from backend import ai, images, knowledge as kb
from backend.db import Session, Job, Work, Conversation, Followup
from .conftest import post
from .test_workflow import guest, make_work


def test_invalid_verification_cannot_pass(clients, monkeypatch):
    admin, *_ = clients
    wid, _ = make_work(admin)
    with Session() as s:
        w = s.get(Work, wid)
        content, brief = json.loads(w.content), json.loads(w.brief)
    content['claims'] = [{'text': '产品事实', 'source_id': content['sources'][0]['id']}]
    async def invalid(*args, **kwargs):
        return {}, {}
    monkeypatch.setattr(ai, 'model_json', invalid)
    with pytest.raises(ValueError):
        asyncio.run(ai.verify(content, brief))


def test_cancellation_is_terminal(clients):
    with Session() as s:
        j = Job(kind='generate', actor_id='test', status='cancelled')
        s.add(j); s.commit(); jid = j.id
    ai.job_update(jid, status='failed', step='late failure')
    with Session() as s:
        assert s.get(Job, jid).status == 'cancelled'


def test_declined_followup_cannot_be_reactivated(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    post(staff, f'/conversations/{cid}/claim')
    post(staff, '/followups/plan', {'conversation_id': cid})
    fid = staff.get('/api/followups').json()[0]['id']
    staff.patch('/api/conversations/'+cid, json={'stage':'暂不购买'}, headers={'X-Store-Request':'1'})
    r = staff.patch('/api/followups/'+fid, json={'status':'pending'}, headers={'X-Store-Request':'1'})
    assert r.status_code == 409


def test_takeover_transfers_pending_followups(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    post(staff, f'/conversations/{cid}/claim')
    post(staff, '/followups/plan', {'conversation_id': cid})
    owner = staff.get('/api/me').json()['user']['id']
    post(admin, f'/conversations/{cid}/takeover', {'expected_owner':owner})
    admin_id = admin.get('/api/me').json()['user']['id']
    assert all(x['owner_id'] == admin_id for x in admin.get('/api/followups').json())


def test_next_step_can_be_corrected_and_locked(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    post(staff, f'/conversations/{cid}/claim')
    r = staff.patch(f'/api/conversations/{cid}/analysis', json={'field':'next_step','value':'周六到店核对软件','locked':True}, headers={'X-Store-Request':'1'})
    assert r.status_code == 200
    assert staff.get('/api/conversations/'+cid).json()['locked']['next_step']['manual']


def test_missing_brief_reports_needs_input_without_model(clients, monkeypatch):
    async def never(*args, **kwargs):
        raise AssertionError('incomplete brief must not call model')
    monkeypatch.setattr(ai,'model_json',never)
    result = asyncio.run(ai.generate({'platform':'小红书'}, 'unused'))
    assert set(result['needs_input']) == {'product_id','audience','scene','goal'}


def test_historical_documents_and_images_survive_reindex(tmp_path, monkeypatch):
    image = tmp_path/'old.png'; image.write_bytes(b'old-image')
    index = tmp_path/'index.db'
    for file in [index, tmp_path/'index-v1.db']:
        with sqlite3.connect(file) as c:
            c.executescript('CREATE TABLE documents(id TEXT,urls TEXT,title TEXT); CREATE TABLE images(id TEXT,path TEXT);')
            if file != index:
                c.execute('INSERT INTO documents VALUES(?,?,?)',('old-doc','[]','原始资料'))
                c.execute('INSERT INTO images VALUES(?,?)',('old-image',str(image)))
    monkeypatch.setattr(kb,'INDEX',index)
    monkeypatch.setattr(kb,'KNOWLEDGE',tmp_path)
    assert kb.knowledge.document('old-doc')['title'] == '原始资料'
    assert kb.knowledge.image_path('old-image') == image


def test_json_structure_repaired_only_once(monkeypatch):
    calls=[]
    def response(request):
        calls.append(json.loads(request.content))
        body = 'invalid JSON' if len(calls)==1 else '{"ok":true}'
        return httpx.Response(200,json={'choices':[{'message':{'content':body}}],'usage':{'total_tokens':5}})
    original=httpx.AsyncClient
    monkeypatch.setattr(ai,'TEXT_BASE','https://model.test/v1')
    monkeypatch.setattr(ai,'TEXT_KEY','test-token')
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(response)))
    result,usage=asyncio.run(ai.model_json('JSON',{}))
    assert result == {'ok':True}
    assert len(calls)==2 and usage['total_tokens']==10


def test_schema_structure_repair_is_bounded(monkeypatch):
    calls=[]
    def response(request):
        calls.append(request)
        body = {} if len(calls)==1 else {'title':'标题','body':'正文'}
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps(body)}}]})
    original=httpx.AsyncClient
    monkeypatch.setattr(ai,'TEXT_BASE','https://model.test/v1')
    monkeypatch.setattr(ai,'TEXT_KEY','test-token')
    monkeypatch.setattr(ai.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(response)))
    result,_=asyncio.run(ai.model_json('JSON',{},schema=ai.GeneratedArticle))
    assert result['title']=='标题' and len(calls)==2


def test_cancelled_generation_does_not_save_work(clients,monkeypatch):
    admin,*_=clients
    p=kb.knowledge.products()[0]
    with Session() as s:
        j=Job(kind='generate',actor_id=admin.get('/api/me').json()['user']['id'])
        s.add(j);s.commit();jid=j.id
    async def generated(*args,**kwargs):
        return {'title':'测试','body':'测试内容'},{}
    async def cancelled(*args,**kwargs):
        with Session() as s:
            s.get(Job,jid).status='cancelled';s.commit()
        return {'status':'passed'}
    monkeypatch.setattr(ai,'model_json',generated)
    monkeypatch.setattr(ai,'verify',cancelled)
    asyncio.run(ai.generate({'product_id':p['id'],'audience':'学生','scene':'学习','goal':'咨询','platform':'朋友圈'},jid))
    with Session() as s:
        assert s.scalar(select(Work)) is None


def test_duplicate_images_do_not_satisfy_platform_minimum(clients,monkeypatch):
    admin,*_=clients
    wid,_=make_work(admin)
    with Session() as s:
        w=s.get(Work,wid);content=json.loads(w.content);brief=json.loads(w.brief)
    content['images']*=3;brief['platform']='小红书'
    content['claims']=[{'text':'事实','source_id':content['sources'][0]['id']}]
    async def valid(*args,**kwargs):return {'issues':[],'pending':[],'claims':content['claims']},{}
    monkeypatch.setattr(ai,'model_json',valid)
    result=asyncio.run(ai.verify(content,brief))
    assert result['status']=='needs_review'


def test_backup_restore_drill_never_overwrites_live_db(clients):
    from backend import cli
    path=Path(cli.backup())
    before=(cli.DATA/'store.db').read_bytes()
    result=cli.restore_drill(path)
    assert result['integrity']=='ok' and result['tables']['users']>=2
    assert (cli.DATA/'store.db').read_bytes()==before


def test_review_can_resolve_pending_after_edit_but_requires_reverification(clients):
    admin,*_=clients;wid,iid=make_work(admin)
    with Session() as s:
        w=s.get(Work,wid);content=json.loads(w.content);content['pending']=['旧文稿中的待确认事项'];w.content=json.dumps(content);s.commit()
    response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={'expected_version':1,'title':'已删除不确定表述','body':'邀请到店核对需求。','image_ids':[iid],'pending':[],'tags':['到店体验']})
    assert response.status_code==200
    work=admin.get('/api/works/'+wid).json()
    assert work['content']['pending']==[]
    assert work['content']['tags']==['到店体验']
    assert work['report']['status']=='unchecked'


def test_reverification_uses_current_text_and_refreshes_fact_list(clients,monkeypatch):
    admin,*_=clients;wid,_=make_work(admin)
    with Session() as s:
        w=s.get(Work,wid);content=json.loads(w.content);brief=json.loads(w.brief)
    source=content['sources'][0]['id'];seen=[]
    content['claims']=[{'text':'已删除的旧参数','source_id':source}]
    async def verifier(instruction,data,*args,**kwargs):
        seen.append(data)
        return {'issues':[],'pending':[],'claims':[{'text':'当前文稿事实','source_id':source}]},{}
    monkeypatch.setattr(ai,'model_json',verifier)
    report=asyncio.run(ai.verify(content,brief))
    assert 'claims' not in seen[0]['content']
    assert report['claims']==[{'text':'当前文稿事实','source_id':source}]


@pytest.mark.parametrize('ratio',['1:1','3:4','16:9'])
def test_poster_layout_keeps_text_and_product_separate(clients,ratio):
    admin,*_=clients;wid,iid=make_work(admin)
    with Session() as s:
        w=s.get(Work,wid);content=json.loads(w.content);content['title']='差旅办公选电脑：从行李、文档和接口开始核对';w.content=json.dumps(content);s.commit()
    result=post(admin,'/works/'+wid+'/compose',{'image_id':iid,'ratio':ratio}).json()
    layout=result['metadata']['layout']
    def overlaps(a,b):return a[0]<b[2] and b[0]<a[2] and a[1]<b[3] and b[1]<a[3]
    assert not overlaps(layout['title'],layout['product'])
    assert not overlaps(layout['summary'],layout['source'])


def test_restart_keeps_saved_work_and_remote_image_identity(clients):
    from backend.main import app,lifespan
    admin,*_=clients;wid,_=make_work(admin)
    with Session() as s:
        text=Job(kind='generate',actor_id='test',status='running')
        image=Job(kind='image',actor_id='test',status='running',remote_id='persisted-task')
        s.add_all([text,image]);s.commit();text_id,image_id=text.id,image.id
    async def restart():
        async with lifespan(app):
            with Session() as s:
                assert s.get(Job,text_id).status=='failed'
                assert s.get(Job,image_id).status=='waiting_remote'
                assert s.get(Job,image_id).remote_id=='persisted-task'
                assert s.get(Work,wid).version==1
    asyncio.run(restart())


def test_model_alias_search_returns_original_product_documents(clients):
    matches=kb.knowledge.search('MB14',category='P1')
    assert matches
    assert any(row['product_id'] for row in matches)
    assert all('/00-全库横向索引/' not in row['path'] for row in matches)
