from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from backend.db import Conversation, ConversationDismissal, Followup, Message, Session
from .conftest import post
from .test_workflow import guest


HEADERS = {'X-Store-Request': '1'}


def plan(staff, cid):
    assert post(staff, f'/conversations/{cid}/claim').status_code == 200
    assert post(staff, '/followups/plan', {'conversation_id': cid}).status_code == 200
    return staff.get('/api/followups').json()


def edit(client, fid, **values):
    return client.patch('/api/followups/' + fid, json=values, headers=HEADERS)


def test_due_reminders_are_private_stable_and_actionable(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    items = plan(staff, cid)
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    assert edit(staff, items[0]['id'], due_at=due).status_code == 200
    # An offset representation of a future instant must not trigger early.
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).astimezone(timezone(timedelta(hours=-8))).isoformat()
    with Session() as s:
        s.get(Followup, items[1]['id']).due_at = future
        s.commit()
    response = staff.get('/api/notifications')
    assert response.status_code == 200
    reminders = response.json()
    assert [r['id'] for r in reminders] == [items[0]['id']]
    assert reminders[0]['customer_name'] == '林同学'
    assert reminders[0]['conversation_id'] == cid
    assert reminders[0]['kind'] == 'followup'
    assert staff.get('/api/notifications').json() == reminders
    assert admin.get('/api/notifications').json() == []
    assert customer.get('/api/notifications').status_code == 403
    with Session() as s:
        assert list(s.scalars(select(Message).where(Message.conversation_id == cid))) == []
    assert edit(staff, items[0]['id'], status='completed', feedback='已联系').status_code == 200
    assert staff.get('/api/notifications').json() == []
    assert edit(staff, items[0]['id'], status='pending', due_at=due).status_code == 200
    assert edit(staff, items[0]['id'], due_at=future).status_code == 200
    assert staff.get('/api/notifications').json() == []
    assert edit(staff, items[0]['id'], due_at=due, status='cancelled').status_code == 200
    assert staff.get('/api/notifications').json() == []


def test_received_conversation_cannot_be_abandoned_or_lose_reminders(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    items = plan(staff, cid)
    owner = staff.get('/api/me').json()['user']['id']
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    edit(staff, items[0]['id'], due_at=due)
    response = post(staff, f'/conversations/{cid}/abandon', {'expected_owner': owner})
    assert response.status_code == 409
    assert '已接待' in response.json()['detail']
    assert cid in [c['id'] for c in staff.get('/api/conversations').json()]
    post(staff, '/auth/logout')
    post(staff, '/auth/login', {'username': 'staff_test', 'password': 'StrongTestPassword!'})
    assert cid in [c['id'] for c in staff.get('/api/conversations').json()]
    assert [r['id'] for r in staff.get('/api/notifications').json()] == [items[0]['id']]
    assert len(staff.get('/api/followups').json()) == 3
    assert customer.get('/api/conversations/' + cid).status_code == 200
    received = next(c for c in admin.get('/api/conversations').json() if c['id'] == cid)
    assert received['owner_id'] == owner and received['status'] == 'active'
    with Session() as s:
        assert s.get(ConversationDismissal, (owner, cid)) is None
    assert staff.patch('/api/conversations/' + cid, json={'status': 'closed'}, headers=HEADERS).status_code == 200
    assert post(staff, f'/conversations/{cid}/abandon', {'expected_owner': owner}).status_code == 409
    assert staff.patch('/api/conversations/' + cid, json={'status': 'active'}, headers=HEADERS).status_code == 200
    assert post(admin, f'/conversations/{cid}/takeover', {'expected_owner': owner}).status_code == 200
    assert len(admin.get('/api/followups').json()) == 3
    assert [r['id'] for r in admin.get('/api/notifications').json()] == [items[0]['id']]
    assert staff.get('/api/notifications').json() == []
    assert cid in [c['id'] for c in staff.get('/api/conversations').json()]


def test_abandon_unclaimed_or_others_never_releases_their_owner(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    assert post(customer, f'/conversations/{cid}/abandon', {'expected_owner': None}).status_code == 403
    assert post(staff, f'/conversations/{cid}/abandon', {'expected_owner': None}).status_code == 200
    assert staff.get('/api/conversations').json() == []
    post(staff, '/auth/logout')
    post(staff, '/auth/login', {'username': 'staff_test', 'password': 'StrongTestPassword!'})
    assert staff.get('/api/conversations').json() == []
    assert post(admin, f'/conversations/{cid}/claim').status_code == 200
    owner = admin.get('/api/me').json()['user']['id']
    assert post(staff, f'/conversations/{cid}/abandon', {'expected_owner': None}).status_code == 409
    assert post(staff, f'/conversations/{cid}/abandon', {'expected_owner': owner}).status_code == 409
    with Session() as s:
        assert s.get(Conversation, cid).owner_id == owner
    assert post(staff, f'/conversations/{cid}/takeover', {'expected_owner': owner}).status_code == 200
    assert cid in [c['id'] for c in staff.get('/api/conversations').json()]


def test_takeover_and_customer_rejection_clear_old_reminders(clients):
    admin, staff, customer, _ = clients
    cid = guest(customer)
    items = plan(staff, cid)
    due = (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat()
    edit(staff, items[0]['id'], due_at=due)
    owner = staff.get('/api/me').json()['user']['id']
    post(admin, f'/conversations/{cid}/takeover', {'expected_owner': owner})
    assert staff.get('/api/notifications').json() == []
    assert len(admin.get('/api/notifications').json()) == 1
    admin.patch('/api/conversations/' + cid, json={'stage': '暂不购买'}, headers=HEADERS)
    assert admin.get('/api/notifications').json() == []


def test_future_deadline_becomes_due_without_a_new_plan(clients, monkeypatch):
    _, staff, customer, _ = clients
    cid = guest(customer)
    items = plan(staff, cid)
    due = datetime.now(timezone.utc) + timedelta(hours=1)
    edit(staff, items[0]['id'], due_at=due.isoformat())
    assert staff.get('/api/notifications').json() == []
    monkeypatch.setattr('backend.main.now', lambda: due.isoformat())
    assert [r['id'] for r in staff.get('/api/notifications').json()] == [items[0]['id']]
