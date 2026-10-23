import asyncio
import io
import json

import httpx
import pytest
from PIL import Image

from backend import ai_poster,main,opendesign_engine
from backend.db import Asset,Job,Session,Work
from .conftest import post
from .test_workflow import make_work


@pytest.fixture
def poster_request(clients,monkeypatch):
    admin,*_=clients;wid,iid=make_work(admin)
    monkeypatch.setattr(ai_poster,'IMAGE_KEY','test-key')
    async def noop(jid):pass
    monkeypatch.setattr(main,'run_poster',noop)
    async def design(payload,reference,folder,feedback=None):
        return {'engine':'OpenDesign','revision':opendesign_engine.REVISION,'model':'test-vlm','spec':{'brief':'学习与编程','canvas':{'w_px':960,'h_px':1280}},'prompt':'大学学习和写代码，使用产品参考图设计整张海报','trace':[]}
    async def review(*args):
        return {'engine':'OpenDesign','model':'test-vlm','verdict':'pass','score':.9,'issues':[],'summary':'图文通过','review_state':'completed','vision_images':['poster_full','product_reference']}
    monkeypatch.setattr(opendesign_engine,'plan',design)
    monkeypatch.setattr(opendesign_engine,'review',review)
    body={'image_id':iid,'expected_version':1,'scene':'大学学习和写代码','ratio':'3:4','request_id':'poster-test-request-001'}
    return admin,wid,body


def test_poster_task_validates_version_review_and_idempotency(poster_request):
    admin,wid,body=poster_request
    first=post(admin,f'/works/{wid}/poster-tasks',body)
    assert first.status_code==200
    assert post(admin,f'/works/{wid}/poster-tasks',body).json()==first.json()
    assert post(admin,f'/works/{wid}/poster-tasks',{**body,'request_id':'other-poster-request','expected_version':2}).status_code==409
    with Session() as s:
        w=s.get(Work,wid);w.report=json.dumps({'status':'unchecked'});s.commit()
    assert post(admin,f'/works/{wid}/poster-tasks',{**body,'request_id':'unchecked-poster-001'}).status_code==409


def mock_provider(monkeypatch):
    requests=[];output=io.BytesIO();Image.new('RGB',(960,1280),'navy').save(output,format='PNG')
    def handle(request):
        requests.append(request)
        if request.method=='POST':return httpx.Response(200,json={'task_id':'remote-poster-001'})
        return httpx.Response(200,json={'task_status':'SUCCEED','output_images':['https://public.example/output.png']})
    original=httpx.AsyncClient
    monkeypatch.setattr(ai_poster.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle)))
    async def download(url):return output.getvalue()
    monkeypatch.setattr(ai_poster,'download_image',download)
    return requests,output.getvalue()


def test_real_poster_request_sends_reference_and_saves_model_output(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,blob=mock_provider(monkeypatch)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    asyncio.run(ai_poster.run_poster(jid))
    job=admin.get('/api/jobs/'+jid).json()
    assert job['status']=='completed' and job['remote_id']=='remote-poster-001'
    submitted=json.loads(requests[0].content)
    assert submitted['image_url'][0].startswith('data:image/png;base64,')
    assert '写代码' in submitted['prompt'] and submitted['size']=='960x1280'
    assert admin.get('/api/assets/'+job['result']['asset_id']).content==blob
    with Session() as s:
        asset=s.get(Asset,job['result']['asset_id']);metadata=json.loads(asset.metadata_json)
        assert asset.kind=='ai_poster' and metadata['generation']=='full_image'
        assert metadata['product_image_id']==body['image_id'] and metadata['work_version']==1
    asyncio.run(ai_poster.run_poster(jid))
    assert len(requests)==2


def test_resume_only_queries_saved_remote_task(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,_=mock_provider(monkeypatch)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    with Session() as s:
        j=s.get(Job,jid);j.status='waiting_remote';j.remote_id='remote-poster-001';s.commit()
    asyncio.run(ai_poster.run_poster(jid))
    assert all(r.method=='GET' for r in requests)
    assert admin.get('/api/jobs/'+jid).json()['status']=='completed'


def test_cancelled_poster_does_not_save_asset(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,blob=mock_provider(monkeypatch)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    async def cancel_during_download(url):
        with Session() as s:
            j=s.get(Job,jid);j.status='cancelled';s.commit()
        return blob
    monkeypatch.setattr(ai_poster,'download_image',cancel_during_download)
    asyncio.run(ai_poster.run_poster(jid))
    assert admin.get('/api/jobs/'+jid).json()['status']=='cancelled'
    assert admin.get('/api/assets').json()==[]


def test_unknown_submission_cannot_automatically_create_another_paid_task(poster_request,monkeypatch):
    admin,wid,body=poster_request
    original=httpx.AsyncClient
    def timeout(request):raise httpx.ReadTimeout('unknown outcome')
    monkeypatch.setattr(ai_poster.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(timeout)))
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    asyncio.run(ai_poster.run_poster(jid))
    job=admin.get('/api/jobs/'+jid).json()
    assert job['status']=='failed' and not job['remote_id']
    assert post(admin,'/jobs/'+jid+'/retry').status_code==409


def test_timeout_preserves_remote_id_and_continues_without_resubmission(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,_=mock_provider(monkeypatch)
    monkeypatch.setattr(ai_poster,'POLL_SECONDS',0)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    asyncio.run(ai_poster.run_poster(jid))
    assert admin.get('/api/jobs/'+jid).json()['status']=='waiting_remote'
    assert post(admin,'/jobs/'+jid+'/retry').json()['job_id']==jid
    monkeypatch.setattr(ai_poster,'POLL_SECONDS',180)
    asyncio.run(ai_poster.run_poster(jid))
    assert sum(r.method=='POST' for r in requests)==1
    assert admin.get('/api/jobs/'+jid).json()['status']=='completed'


def test_edit_after_queue_stops_before_remote_submission(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,_=mock_provider(monkeypatch)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    with Session() as s:
        work=s.get(Work,wid);work.version=2;s.commit()
    asyncio.run(ai_poster.run_poster(jid))
    assert not requests
    assert admin.get('/api/jobs/'+jid).json()['status']=='failed'


def test_poster_request_rejects_unsafe_identifiers_and_empty_scene(poster_request):
    admin,wid,body=poster_request
    for bad in [{'request_id':'../../unsafe-file'},{'scene':'   '}]:
        assert post(admin,f'/works/{wid}/poster-tasks',{**body,**bad}).status_code==422


def test_upstream_design_and_pixel_review_are_saved_with_final_poster(poster_request,monkeypatch):
    admin,wid,body=poster_request;mock_provider(monkeypatch)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    asyncio.run(ai_poster.run_poster(jid))
    with Session() as s:
        job=s.get(Job,jid);asset=s.get(Asset,json.loads(job.result)['asset_id']);metadata=json.loads(asset.metadata_json)
        assert metadata['design_engine']=='OpenDesign'
        assert metadata['design_revision']==opendesign_engine.REVISION
        assert metadata['review']['review_state']=='completed'
        assert metadata['review']['vision_images']==['poster_full','product_reference']


def test_one_visual_repair_is_bounded_and_keeps_both_attempts(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,_=mock_provider(monkeypatch);reviews=[]
    async def revise(*args):
        reviews.append(1)
        return {'engine':'OpenDesign','verdict':'revise','score':.6,'issues':[{'severity':'medium','category':'typography','description':'标题拥挤，需要调整'}],
                'summary':'需要调整','review_state':'completed','vision_images':['poster_full','product_reference']}
    monkeypatch.setattr(opendesign_engine,'review',revise)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    asyncio.run(ai_poster.run_poster(jid))
    job=admin.get('/api/jobs/'+jid).json()
    assert job['status']=='completed'
    assert sum(r.method=='POST' for r in requests)==2 and len(reviews)==2
    assert len(job['result']['attempts'])==2 and job['result']['review']['verdict']=='revise'


def test_unavailable_visual_review_keeps_output_without_another_charge(poster_request,monkeypatch):
    admin,wid,body=poster_request;requests,_=mock_provider(monkeypatch)
    async def unavailable(*args):
        return {'verdict':'fail','score':0,'issues':[],'summary':'服务暂时异常','review_state':'unavailable','vision_images':[]}
    monkeypatch.setattr(opendesign_engine,'review',unavailable)
    jid=post(admin,f'/works/{wid}/poster-tasks',body).json()['job_id']
    asyncio.run(ai_poster.run_poster(jid))
    job=admin.get('/api/jobs/'+jid).json()
    assert sum(r.method=='POST' for r in requests)==1
    assert job['status']=='completed' and job['result']['review']['review_state']=='unavailable'
