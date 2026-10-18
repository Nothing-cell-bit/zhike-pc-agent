import io
import json
import zipfile
from pathlib import Path
from sqlalchemy import select
from backend.db import Session,Conversation,Message,Work,WorkVersion,Followup,Job
from backend.knowledge import knowledge,import_zip
from backend.main import work_markdown
from backend.images import compose
from .conftest import post

def guest(c,name='林同学'):
    assert post(c,'/auth/guest',{'name':name}).status_code==200
    return post(c,'/conversations').json()['id']

def test_customer_isolation_and_private_ai(clients):
    admin,staff,c,other=clients;cid=guest(c);guest(other,'其他客户')
    assert other.get('/api/conversations/'+cid).status_code==403
    assert other.get('/api/conversations/'+cid+'/messages').status_code in {404,405}
    assert other.get('/api/jobs').status_code==403
    assert 'analysis' not in c.get('/api/conversations/'+cid).json()

def test_claim_takeover_idempotency_and_reopen(clients):
    admin,staff,c,other=clients;cid=guest(c)
    body={'content':'我想给孩子买电脑，预算六千元','client_id':'client-message-000001'}
    first=post(c,f'/conversations/{cid}/messages',body)
    assert first.status_code==200
    assert post(c,f'/conversations/{cid}/messages',body).json()['id']==first.json()['id']
    assert post(staff,f'/conversations/{cid}/messages',{'content':'你好','client_id':'staff-message-000001'}).status_code==409
    assert post(staff,f'/conversations/{cid}/claim').status_code==200
    assert post(admin,f'/conversations/{cid}/claim').status_code==409
    owner=admin.get('/api/conversations/'+cid).json()['owner_id']
    assert post(admin,f'/conversations/{cid}/takeover',{'expected_owner':'wrong'}).status_code==409
    assert post(admin,f'/conversations/{cid}/takeover',{'expected_owner':owner}).status_code==200
    assert post(staff,f'/conversations/{cid}/messages',{'content':'旧负责人','client_id':'staff-message-000002'}).status_code==409
    assert post(admin,f'/conversations/{cid}/messages',{'content':'您好，请问主要使用什么软件？','client_id':'admin-message-000001'}).status_code==200
    response=admin.patch('/api/conversations/'+cid,json={'status':'closed'},headers={'X-Store-Request':'1'})
    assert response.status_code==200
    assert post(c,f'/conversations/{cid}/messages',{'content':'还有问题','client_id':'client-message-000003'}).status_code==409
    assert c.patch('/api/conversations/'+cid,json={'status':'active'},headers={'X-Store-Request':'1'}).status_code==200
    assert len(c.get('/api/conversations/'+cid).json()['messages'])==2

def test_registration_preserves_guest_history_and_role(clients):
    admin,staff,c,other=clients;cid=guest(c)
    r=post(c,'/auth/register',{'username':'customer_new','password':'LongCustomerPass123','display_name':'林同学','role':'admin'})
    assert r.status_code==200 and r.json()['role']=='customer'
    assert c.get('/api/conversations/'+cid).status_code==200
    assert c.get('/api/admin/status').status_code==403
    post(c,'/auth/logout')
    assert c.get('/api/conversations/'+cid).status_code==401
    assert post(c,'/auth/login',{'username':'customer_new','password':'LongCustomerPass123'}).status_code==200
    assert c.get('/api/conversations/'+cid).status_code==200

def test_csrf_and_staff_permission(clients):
    admin,staff,c,other=clients
    assert admin.post('/api/auth/logout').status_code==403
    assert admin.post('/api/auth/logout',headers={'X-Store-Request':'1','Origin':'https://evil.example'}).status_code==403
    assert post(staff,'/admin/users',{'username':'evil_staff','password':'LongCustomerPass123'}).status_code==403
    assert post(admin,'/admin/users',{'username':'new_staff','password':'LongCustomerPass123','display_name':'新顾问'}).status_code==200
    me=admin.get('/api/me').json()['user']
    assert admin.patch('/api/admin/users/'+me['id'],headers={'X-Store-Request':'1'},json={'active':False,'role':'staff'}).status_code==400

def test_followup_rejection_stops_plan(clients):
    admin,staff,c,other=clients;cid=guest(c);post(staff,f'/conversations/{cid}/claim')
    assert post(staff,'/followups/plan',{'conversation_id':cid,'days':[1,3,7]}).status_code==200
    assert post(staff,'/followups/plan',{'conversation_id':cid,'days':[1]}).status_code==409
    assert len(staff.get('/api/followups').json())==3
    assert staff.patch('/api/conversations/'+cid,json={'stage':'暂不购买'},headers={'X-Store-Request':'1'}).status_code==200
    assert all(f['status']=='cancelled' for f in staff.get('/api/followups').json())
    assert post(staff,'/followups/plan',{'conversation_id':cid,'days':[1]}).status_code==409

def make_work(admin):
    p=knowledge.products()[0];images=knowledge.images(p['id'])[:1]
    content={'title':'适合移动办公的选择','intro':'根据使用需求核对配置','body':'## 选择之前\n了解使用环境。','cta':'欢迎到店体验','images':images,'sources':[knowledge.document(p['facts_id'])],'claims':[]}
    with Session() as s:
        u=admin.get('/api/me').json()['user'];w=Work(actor_id=u['id'],brief=json.dumps({'product_id':p['id'],'platform':'朋友圈'}),content=json.dumps(content),report=json.dumps({'status':'passed'}));s.add(w);s.flush();s.add(WorkVersion(work_id=w.id,version=1,content=w.content,report=w.report));s.commit();return w.id,images[0]['id']

def test_work_versions_validation_and_export(clients):
    admin,staff,c,other=clients;wid,iid=make_work(admin)
    assert c.get('/api/works/'+wid).status_code==401
    assert admin.get('/api/works/'+wid+'/export?format=zip').status_code==200
    edit={'expected_version':1,'title':'新标题','body':'<script>alert(1)</script>\n正文','intro':'','cta':'欢迎咨询','image_ids':[iid]}
    assert admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json=edit).status_code==200
    assert admin.get('/api/works/'+wid).json()['report']['status']=='unchecked'
    assert admin.get('/api/works/'+wid+'/export?format=html').status_code==409
    exported=admin.get('/api/works/'+wid+'/export?format=html&draft=true')
    assert exported.status_code==200 and '<script>' not in exported.text
    assert admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json=edit).status_code==409
    assert len(admin.get('/api/works/'+wid).json()['versions'])==2

def test_composite_keeps_original_and_rejects_cross_model(clients):
    admin,staff,c,other=clients;wid,iid=make_work(admin)
    uid=admin.get('/api/me').json()['user']['id'];original=knowledge.image_path(iid).read_bytes()
    r=post(admin,'/works/'+wid+'/compose',{'image_id':iid,'ratio':'3:4'})
    assert r.status_code==200
    assert knowledge.image_path(iid).read_bytes()==original
    assert admin.get('/api/assets/'+r.json()['id']).status_code==200
    otherpid=next(p['id'] for p in knowledge.products() if all(im['id']!=iid for im in knowledge.images(p['id'])))
    wrong=knowledge.images(otherpid)[0]['id']
    assert post(admin,'/works/'+wid+'/compose',{'image_id':wrong}).status_code==400

def test_knowledge_integrity_search_and_boundaries(clients):
    state=knowledge.status();assert state['products']==10 and state['images']==112
    result=knowledge.search('屏幕 续航 学生')
    assert result and all(not r['path'].startswith('P4-') for r in result)
    assert knowledge.document(result[0]['id'])['sha256']

def test_websocket_origin_and_authorization(clients):
    admin,staff,c,other=clients;cid=guest(c)
    from starlette.websockets import WebSocketDisconnect
    import pytest
    with pytest.raises(WebSocketDisconnect):
        with other.websocket_connect('/api/ws/'+cid,headers={'origin':'http://testserver'}):pass
    with c.websocket_connect('/api/ws/'+cid,headers={'origin':'http://testserver'}) as ws:
        ws.send_text('ping');assert ws.receive_json()['event']=='pong'

def test_image_idempotency_does_not_resubmit(clients,monkeypatch):
    admin,staff,c,other=clients
    async def no_call(jid):pass
    monkeypatch.setattr('backend.main.run_image',no_call)
    body={'scene':'自然光下的简洁图书馆环境','request_id':'image-request-idempotent-1','ratio':'3:4'}
    first=post(admin,'/images/tasks',body);second=post(admin,'/images/tasks',body)
    assert first.json()['job_id']==second.json()['job_id']
    with Session() as s:assert len(list(s.scalars(select(Job).where(Job.kind=='image'))))==1
