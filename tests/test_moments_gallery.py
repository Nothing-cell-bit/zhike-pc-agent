import asyncio
import io
import json
import zipfile
import httpx
import pytest
from PIL import Image
from backend import moments_gallery as gallery,main
from backend.db import Session,Job,Asset,Work
from backend.knowledge import work_images
from .test_workflow import make_work
from .conftest import post


@pytest.fixture
def gallery_request(clients,monkeypatch):
    admin,*_=clients;wid,iid=make_work(admin)
    with Session() as session:
        work=session.get(Work,wid);images=work_images(json.loads(work.content),json.loads(work.brief))[:3]
    monkeypatch.setattr(gallery,'work_images',lambda *args:images)
    monkeypatch.setattr(gallery,'IMAGE_KEY','test-image-key')
    async def idle(jid):pass
    monkeypatch.setattr(main,'run_moments_gallery',idle)
    return admin,wid,{'expected_version':1,'count':9,'mode':'mixed','scene':'大学学习和写代码','request_id':'moments-grid-request-001'}


def test_nine_grid_has_unique_originals_and_explicit_ai_count(gallery_request):
    admin,wid,body=gallery_request
    response=post(admin,f'/works/{wid}/moments-gallery-tasks',body)
    assert response.status_code==200
    assert response.json()['ai_count']==6 and response.json()['original_count']==3
    with Session() as session:
        payload=json.loads(session.get(Job,response.json()['job_id']).payload)
    assert [item['slot'] for item in payload['items'] if item['kind']=='original']==[0,4,8]
    ids=[item['image_id'] for item in payload['items'] if item['kind']=='original']
    assert len(ids)==len(set(ids))==3
    assert post(admin,f'/works/{wid}/moments-gallery-tasks',body).json()['job_id']==response.json()['job_id']
    assert post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':3}).status_code==409


def test_originals_do_not_repeat_to_fill_nine_and_version_is_checked(gallery_request):
    admin,wid,body=gallery_request
    assert post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'mode':'original'}).status_code==409
    assert post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'expected_version':2}).status_code==409
    assert post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':12}).status_code==422
    with Session() as session:
        work=session.get(Work,wid);work.report=json.dumps({'status':'unchecked'});session.commit()
    assert post(admin,f'/works/{wid}/moments-gallery-tasks',body).status_code==409


def test_moments_creation_starts_album_only_after_text_is_approved(gallery_request,monkeypatch):
    from backend import ai
    admin,wid,body=gallery_request;started=[]
    with Session() as session:
        work=session.get(Work,wid)
        row=Job(kind='generate',actor_id=work.actor_id,status='queued',payload=json.dumps({'platform':'朋友圈','moments_image_count':3,'moments_image_mode':'original','scene':'学习和写代码'}));session.add(row);session.commit();jid=row.id
    async def generate(*args):return {'work_id':wid,'report':{'status':'passed'}}
    async def images(identifier):started.append(identifier)
    monkeypatch.setattr(ai,'generate',generate);monkeypatch.setattr(gallery,'run_moments_gallery',images)
    async def run():await ai.run_text_job(jid);await asyncio.sleep(0)
    asyncio.run(run())
    response=admin.get('/api/jobs/'+jid).json()
    assert response['status']=='completed' and response['result']['gallery_job_id'] in started
    child=admin.get('/api/jobs/'+response['result']['gallery_job_id']).json()
    assert child['kind']=='moments_gallery' and child['payload']['ai_count']==0


def test_original_gallery_is_downloadable_and_reorder_is_versioned(gallery_request,monkeypatch):
    admin,wid,body=gallery_request
    async def forbidden(*args,**kwargs):raise AssertionError('原图模式不能调用生成模型')
    monkeypatch.setattr(gallery,'model_json',forbidden)
    result=post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':3,'mode':'original'}).json()
    asyncio.run(gallery.run_moments_gallery(result['job_id']))
    saved=admin.get(f'/api/works/{wid}/moments-gallery').json()['gallery']
    assert len(saved['items'])==3 and saved['revision']==1
    assert all(item['kind']=='original' and item['url'].startswith('/api/knowledge/images/') for item in saved['items'])
    downloaded=admin.get(f'/api/works/{wid}/moments-gallery/{saved["id"]}/download')
    with zipfile.ZipFile(io.BytesIO(downloaded.content)) as archive:
        assert len([name for name in archive.namelist() if name.startswith('images/')])==3
    edit={'expected_version':1,'expected_revision':1,'order':[2,0,1]}
    response=admin.patch(f'/api/works/{wid}/moments-gallery/{saved["id"]}',headers={'X-Store-Request':'1'},json=edit)
    assert response.status_code==200
    updated=admin.get(f'/api/works/{wid}/moments-gallery').json()['gallery']
    assert updated['items'][0]['image_id']==saved['items'][2]['image_id'] and updated['revision']==2
    listed=next(work for work in admin.get('/api/works').json() if work['id']==wid)
    assert listed['cover_image']['url']==updated['items'][0]['url']
    assert admin.get(listed['cover_image']['url']).status_code==200
    assert admin.patch(f'/api/works/{wid}/moments-gallery/{saved["id"]}',headers={'X-Store-Request':'1'},json=edit).status_code==409


def test_publication_export_includes_gallery_and_old_album_keeps_old_caption(gallery_request):
    admin,wid,body=gallery_request
    result=post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':3,'mode':'original'}).json()
    asyncio.run(gallery.run_moments_gallery(result['job_id']))
    saved=admin.get(f'/api/works/{wid}/moments-gallery').json()['gallery']
    old=admin.get('/api/works/'+wid).json()['content']['body']
    publication=admin.get(f'/api/works/{wid}/export?format=html&scope=publication').text
    assert 'moments-image-grid' in publication and publication.count('src="data:image/')==3
    archive=admin.get(f'/api/works/{wid}/export?format=zip&scope=publication')
    with zipfile.ZipFile(io.BytesIO(archive.content)) as zipped:
        assert len([name for name in zipped.namelist() if name.startswith('images/moments-')])==3
    response=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={'expected_version':1,'title':'新文案','body':'这是新的朋友圈正文','image_ids':[]})
    assert response.status_code==200
    assert admin.get(f'/api/works/{wid}/moments-gallery').json()['gallery'] is None
    listed=next(work for work in admin.get('/api/works').json() if work['id']==wid)
    assert listed['content']['images']==[]
    assert listed['cover_image']['url']==saved['items'][0]['url']
    # Saving text must not drop the existing pictures from the current publication.
    current=admin.get(f'/api/works/{wid}/export?format=html&scope=publication&draft=true')
    assert current.status_code==200
    assert current.text.count('src="data:image/')==3
    assert '这是新的朋友圈正文' in current.text
    current_zip=admin.get(f'/api/works/{wid}/export?format=zip&scope=publication&draft=true')
    with zipfile.ZipFile(io.BytesIO(current_zip.content)) as zipped:
        assert len([name for name in zipped.namelist() if name.startswith('images/moments-')])==3
        assert '这是新的朋友圈正文' in zipped.read('article.html').decode()
    historical=admin.get(f'/api/works/{wid}/moments-gallery/{saved["id"]}/download')
    with zipfile.ZipFile(io.BytesIO(historical.content)) as zipped:assert zipped.read('caption.txt').decode()==old


def mock_provider(monkeypatch):
    requests=[];output=io.BytesIO();Image.new('RGB',(1024,1024),'navy').save(output,format='PNG')
    def handle(request):
        requests.append(request)
        if request.method=='POST':return httpx.Response(200,json={'task_id':'remote-gallery-1'})
        return httpx.Response(200,json={'task_status':'SUCCEED','output_images':['https://public.example/result.png']})
    original=httpx.AsyncClient
    monkeypatch.setattr(gallery.httpx,'AsyncClient',lambda **kwargs:original(transport=httpx.MockTransport(handle)))
    async def download(url):return output.getvalue()
    monkeypatch.setattr(gallery,'download_image',download)
    async def plan(instruction,data,max_tokens=0,schema=None,**kwargs):
        return {'theme':'清爽校园','images':[{'title':f'学习场景{index}','scene':f'不同场景{index}','composition':f'不同镜头{index}'} for index in range(data['count'])]},{}
    monkeypatch.setattr(gallery,'model_json',plan)
    return requests


def test_ai_tile_uses_reference_and_resume_never_resubmits(gallery_request,monkeypatch):
    admin,wid,body=gallery_request;requests=mock_provider(monkeypatch)
    result=post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':1,'mode':'ai'}).json()
    asyncio.run(gallery.run_moments_gallery(result['job_id']))
    job=admin.get('/api/jobs/'+result['job_id']).json()
    assert job['status']=='completed'
    sent=json.loads(requests[0].content)
    assert sent['image_url'][0].startswith('data:image/png;base64,') and sent['size']=='1024x1024'
    assert '拼贴' in sent['prompt'] and len(requests)==2
    saved=admin.get(f'/api/works/{wid}/moments-gallery').json()['gallery']
    assert saved['items'][0]['kind']=='ai' and saved['items'][0]['url'].startswith('/api/assets/')
    asyncio.run(gallery.run_moments_gallery(result['job_id']))
    assert len(requests)==2
    changed=admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={'expected_version':1,'title':'调整后的文案','body':'这是当前朋友圈正文','image_ids':[]})
    assert changed.status_code==200
    preview=admin.get(f'/api/works/{wid}/export?format=html&scope=publication&draft=true')
    assert preview.status_code==200 and preview.text.count('src="data:image/')==1
    assert '这是当前朋友圈正文' in preview.text and len(requests)==2


def test_mixed_scenes_do_not_redraw_computer_and_cancellation_stops_polling(gallery_request,monkeypatch):
    admin,wid,body=gallery_request;requests=mock_provider(monkeypatch)
    result=post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':3,'mode':'mixed'}).json()
    real=httpx._client.AsyncClient
    def cancel_after_submit(request):
        requests.append(request)
        with Session() as session:
            row=session.get(Job,result['job_id']);row.status='cancelled';session.commit()
        return httpx.Response(200,json={'task_id':'remote-cancelled-scene'})
    monkeypatch.setattr(gallery.httpx,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(cancel_after_submit)))
    asyncio.run(gallery.run_moments_gallery(result['job_id']))
    assert len(requests)==1 and requests[0].method=='POST'
    request=json.loads(requests[0].content)
    assert 'image_url' not in request and '不要绘制任何电脑' in request['prompt']
    assert admin.get('/api/jobs/'+result['job_id']).json()['status']=='cancelled'
    assert admin.get(f'/api/works/{wid}/moments-gallery').json()['gallery'] is None


def test_unknown_submission_does_not_charge_twice(gallery_request,monkeypatch):
    admin,wid,body=gallery_request;requests=mock_provider(monkeypatch)
    original=httpx.AsyncClient
    def fail(request):raise httpx.ReadTimeout('uncertain submission')
    # Save the real class before replacing the module method a second time.
    monkeypatch.undo()
    monkeypatch.setattr(gallery,'IMAGE_KEY','test-key')
    async def idle(jid):pass
    monkeypatch.setattr(main,'run_moments_gallery',idle)
    import httpx as client_module
    real=__import__('httpx')._client.AsyncClient
    monkeypatch.setattr(client_module,'AsyncClient',lambda **kwargs:real(transport=httpx.MockTransport(fail)))
    async def plan(*args,**kwargs):return {'theme':'学习','images':[{'title':'图书馆','scene':'图书馆学习','composition':'自然光'}]},{}
    monkeypatch.setattr(gallery,'model_json',plan)
    result=post(admin,f'/works/{wid}/moments-gallery-tasks',{**body,'count':1,'mode':'ai'}).json()
    asyncio.run(gallery.run_moments_gallery(result['job_id']))
    assert admin.get('/api/jobs/'+result['job_id']).json()['status']=='failed'
    assert post(admin,'/jobs/'+result['job_id']+'/retry').status_code==409
