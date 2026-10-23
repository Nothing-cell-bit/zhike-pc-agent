from .dialogue_fakes import legacy_analysis
from .dialogue_fakes import protocol_model
import asyncio
import io
import json
from pathlib import Path

import httpx
import pytest
from PIL import Image
from sqlalchemy import select
from backend import ai,images
from backend.db import Session,Job,Asset,Conversation,Message,Work
from backend.knowledge import knowledge
from .conftest import post
from .test_workflow import guest,make_work


def image_job(status='queued',remote=''):
    with Session() as s:
        j=Job(kind='image',actor_id='test',status=status,remote_id=remote,payload=json.dumps({'scene':'空白图书馆背景','ratio':'3:4'}))
        s.add(j);s.commit();return j.id


def mock_images(monkeypatch,handler):
    original=httpx.AsyncClient
    monkeypatch.setattr(images,'IMAGE_KEY','test-key')
    monkeypatch.setattr(images,'IMAGE_BASE','https://images.test/v1')
    monkeypatch.setattr(images.httpx,'AsyncClient',lambda **kw:original(transport=httpx.MockTransport(handler)))
    async def prompt(*a,**kw):return {'prompt':'empty library'},{}
    monkeypatch.setattr(images,'model_json',prompt)


def test_cancel_during_prompt_does_not_submit_paid_image(clients,monkeypatch):
    jid=image_job();calls=[]
    def handler(r):calls.append(r);return httpx.Response(401)
    mock_images(monkeypatch,handler)
    async def cancelled(*args,**kwargs):
        with Session() as s:s.get(Job,jid).status='cancelled';s.commit()
        return {'prompt':'empty library'},{}
    monkeypatch.setattr(images,'model_json',cancelled)
    asyncio.run(images.run_image(jid))
    assert calls==[]


def test_remote_failure_is_terminal(clients,monkeypatch):
    jid=image_job(remote='remote-1')
    mock_images(monkeypatch,lambda r:httpx.Response(200,json={'task_status':'FAILED'}))
    asyncio.run(images.run_image(jid))
    with Session() as s:assert s.get(Job,jid).status=='failed'


@pytest.mark.parametrize('code,expected',[(401,'鉴权'),(403,'权限'),(429,'额度')])
def test_image_errors_are_explained(clients,monkeypatch,code,expected):
    jid=image_job()
    mock_images(monkeypatch,lambda r:httpx.Response(code,text='error'))
    asyncio.run(images.run_image(jid))
    with Session() as s:
        j=s.get(Job,jid);assert j.status=='failed' and expected in j.error


def test_resume_only_polls_existing_task_and_saves_image_once(clients,monkeypatch):
    jid=image_job(remote='saved-remote');calls=[]
    def handler(r):
        calls.append(r)
        return httpx.Response(200,json={'task_status':'SUCCEED','output_images':['https://media.test/image.png']})
    mock_images(monkeypatch,handler)
    async def blob(url):
        out=io.BytesIO();Image.new('RGB',(32,32),'white').save(out,format='PNG');return out.getvalue()
    monkeypatch.setattr(images,'download_image',blob)
    asyncio.run(images.run_image(jid))
    asyncio.run(images.run_image(jid))
    assert len(calls)==1 and calls[0].method=='GET'
    assert calls[0].headers['X-ModelScope-Task-Type']=='image_generation'
    with Session() as s:
        assert len(list(s.scalars(select(Asset))))==1
        assert s.get(Job,jid).remote_id=='saved-remote'


def test_image_timeout_retains_remote_id_without_second_submission(clients,monkeypatch):
    jid=image_job(remote='saved-remote')
    mock_images(monkeypatch,lambda r:httpx.Response(200,json={'task_status':'RUNNING'}))
    class Clock:
        value=0
        def monotonic(self):self.value+=181;return self.value
    monkeypatch.setattr(images,'time',Clock())
    asyncio.run(images.run_image(jid))
    with Session() as s:
        j=s.get(Job,jid);assert j.status=='waiting_remote' and j.remote_id=='saved-remote'


def test_analysis_new_messages_and_manual_locks_win(clients,monkeypatch):
    admin,staff,customer,_=clients;cid=guest(customer)
    post(staff,f'/conversations/{cid}/claim')
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=1
        s.add(Message(id='evidence',conversation_id=cid,sender_id=c.customer_id,role='customer',content='预算六千',client_id='evidence-message',seq=1));s.commit()
    async def model(*a,**kw):
        with Session() as s:
            c=s.get(Conversation,cid);c.locked=json.dumps({'budget':{'value':'人工六千','evidence':['evidence'],'manual':True}});s.commit()
        return {'goal':'recommend','action':'inform','reply':'旧建议'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(model))
    result=asyncio.run(legacy_analysis(cid))
    assert result['stale'] is True
    assert staff.get('/api/conversations/'+cid).json()['analysis']['budget']['value']=='人工六千'
    async def stale(*a,**kw):
        with Session() as s:c=s.get(Conversation,cid);c.seq+=1;s.commit()
        return {'goal':'recommend','action':'inform','reply':'旧建议'},{}
    monkeypatch.setattr(ai,'model_json',protocol_model(stale))
    assert asyncio.run(legacy_analysis(cid))['stale']


def test_edit_during_verification_never_verifies_new_revision(clients,monkeypatch):
    admin,*_=clients;wid,_=make_work(admin)
    with Session() as s:
        j=Job(kind='verify',target_id=wid,actor_id='test');s.add(j);s.commit();jid=j.id
    async def verify(*a,**kw):
        with Session() as s:
            w=s.get(Work,wid);w.version+=1;w.report=json.dumps({'status':'unchecked'});s.commit()
        return {'status':'passed'}
    monkeypatch.setattr(ai,'verify',verify)
    asyncio.run(ai.run_text_job(jid))
    with Session() as s:
        assert json.loads(s.get(Work,wid).report)['status']=='unchecked'
        assert s.get(Job,jid).status=='failed'


def test_marketing_removes_contact_details_before_model(clients,monkeypatch):
    admin,*_=clients;received=[]
    with Session() as s:
        job=Job(kind='generate',actor_id=admin.get('/api/me').json()['user']['id']);s.add(job);s.commit();jid=job.id
    async def capture(*args,**kwargs):
        received.append(json.dumps(args[1],ensure_ascii=False))
        raise ValueError('stop after input check')
    monkeypatch.setattr(ai,'model_json',protocol_model(capture))
    brief={'product_id':knowledge.products()[0]['id'],'audience':'张同学，手机13800138000','scene':'联系 student@example.com','goal':'到店','platform':'朋友圈'}
    with pytest.raises(ValueError):asyncio.run(ai.generate(brief,jid))
    assert '13800138000' not in received[0] and 'student@example.com' not in received[0]
