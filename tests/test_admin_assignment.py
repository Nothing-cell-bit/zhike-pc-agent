import json
import pytest
from sqlalchemy import select
from backend.db import Session,User,Conversation,ConversationDismissal,Followup,Audit,Message
from backend.main import ph
from .conftest import post
from .test_workflow import guest


def setup_assignment(clients):
    admin,staff,customer,_=clients
    cid=guest(customer)
    aid=admin.get('/api/me').json()['user']['id'];sid=staff.get('/api/me').json()['user']['id']
    with Session() as session:
        other=User(username='assignment_staff',display_name='客服乙',password=ph.hash('TestAssignmentPass123'),role='staff')
        inactive=User(username='inactive_staff',display_name='已停用客服',password='!',role='staff',active=False)
        session.add_all([other,inactive]);session.flush()
        session.add(Followup(id='pending-task',conversation_id=cid,owner_id=sid,due_at='2026-10-21T01:00:00+00:00',purpose='确认软件',status='pending'))
        session.add(Followup(id='completed-task',conversation_id=cid,owner_id=sid,due_at='2026-10-20T01:00:00+00:00',purpose='历史提醒',status='completed'))
        session.get(Conversation,cid).owner_id=sid;session.get(Conversation,cid).status='active'
        session.add(ConversationDismissal(user_id=other.id,conversation_id=cid));session.commit()
        return cid,aid,sid,other.id,inactive.id


def assign(client,owner,rows):
    return post(client,'/admin/conversations/assign',{'owner_id':owner,'conversations':rows})


def test_macro_overview_includes_dismissed_conversations_and_staff_workload(clients):
    admin,staff,customer,_=clients;cid,aid,sid,target,inactive=setup_assignment(clients)
    with Session() as session:
        session.add(ConversationDismissal(user_id=aid,conversation_id=cid));session.commit()
    response=admin.get('/api/admin/conversations')
    assert response.status_code==200
    data=response.json();assert data['summary']['active']==1 and data['summary']['total']==1
    row=next(row for row in data['conversations'] if row['id']==cid)
    assert row['owner_id']==sid and 'analysis' not in row and 'messages' not in row
    employee=next(row for row in data['staff'] if row['id']==sid)
    assert employee['active_count']==1 and employee['pending_followups']==1
    assert staff.get('/api/admin/conversations').status_code==403
    assert customer.get('/api/admin/conversations').status_code==403


def test_assignment_moves_pending_followups_clears_recipient_dismissal_and_audits(clients):
    admin,staff,customer,_=clients;cid,aid,sid,target,_=setup_assignment(clients)
    response=assign(admin,target,[{'id':cid,'expected_owner':sid}])
    assert response.status_code==200 and response.json()['count']==1
    with Session() as session:
        conv=session.get(Conversation,cid)
        assert conv.owner_id==target and conv.status=='active'
        assert session.get(Followup,'pending-task').owner_id==target
        assert session.get(Followup,'completed-task').owner_id==sid
        assert not session.get(ConversationDismissal,(target,cid))
        log=session.scalar(select(Audit).where(Audit.action=='assign_conversation'))
        assert log.actor_id==aid and json.loads(log.target)['previous_owner']==sid
        assert session.query(Message).filter_by(conversation_id=cid).count()==0
    assert assign(admin,None,[{'id':cid,'expected_owner':target}]).status_code==200
    with Session() as session:
        assert session.get(Conversation,cid).owner_id is None
        assert session.get(Conversation,cid).status=='waiting'
        assert session.get(Followup,'pending-task').owner_id==''


def test_batch_is_atomic_on_conflict_and_can_assign_legacy_admin_owned_conversations(clients):
    admin,_,_,_=clients;cid,aid,sid,target,_=setup_assignment(clients)
    with Session() as session:
        other=Conversation(customer_id='customer-other',customer_name='另一位客户',owner_id=aid,status='active');session.add(other);session.commit();second=other.id
    failed=assign(admin,target,[{'id':cid,'expected_owner':sid},{'id':second,'expected_owner':sid}])
    assert failed.status_code==409
    with Session() as session:assert session.get(Conversation,cid).owner_id==sid
    ok=assign(admin,target,[{'id':cid,'expected_owner':sid},{'id':second,'expected_owner':aid}])
    assert ok.status_code==200 and ok.json()['count']==2


def test_assignment_validates_target_closed_status_duplicate_and_missing_owner(clients):
    admin,staff,customer,_=clients;cid,aid,sid,target,inactive=setup_assignment(clients)
    rows=[{'id':cid,'expected_owner':sid}]
    for invalid in [aid,inactive,customer.get('/api/me').json()['user']['id'],'missing']:
        assert assign(admin,invalid,rows).status_code==400
    assert assign(staff,target,rows).status_code==403
    assert assign(customer,target,rows).status_code==403
    assert assign(admin,target,rows*2).status_code==422
    assert assign(admin,target,[{'id':cid}]).status_code==422
    assert assign(admin,target,[{'id':'missing','expected_owner':None}]).status_code==404
    assert assign(admin,target,[{'id':str(index),'expected_owner':None} for index in range(51)]).status_code==422
    with Session() as session:session.get(Conversation,cid).status='closed';session.commit()
    assert assign(admin,target,rows).status_code==409
