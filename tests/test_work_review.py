import asyncio
import json

import pytest
from sqlalchemy import select

from backend import ai
from backend.db import Audit, Job, Session, Work, WorkVersion
from .conftest import post
from .test_workflow import make_work, guest


def review_work(admin, *, blocked=False):
    wid, iid = make_work(admin)
    with Session() as s:
        w = s.get(Work, wid)
        c = json.loads(w.content)
        c['pending'] = ['请核对当日活动']
        w.content = json.dumps(c)
        w.report = json.dumps({'status': 'needs_review', 'blocked': blocked,
                               'issues': [{'type': '动态信息', 'text': '请确认门店价格'}],
                               'pending': ['请核对当日活动']})
        v = s.scalar(select(WorkVersion).where(WorkVersion.work_id == wid))
        v.content, v.report = w.content, w.report
        s.commit()
    return wid, iid


def test_manual_approval_records_reviewer_exports_and_expires_on_edit(clients):
    admin, staff, *_ = clients
    wid, iid = review_work(admin)
    response = post(staff, f'/works/{wid}/approve', {'expected_version': 1, 'note': '已向门店确认当日价格和活动'})
    assert response.status_code == 200
    work = staff.get(f'/api/works/{wid}').json()
    assert work['version'] == 2
    assert work['report']['status'] == 'manual_passed'
    approval = work['report']['approval']
    assert approval['actor_id'] == staff.get('/api/me').json()['user']['id']
    assert approval['note'] == '已向门店确认当日价格和活动'
    assert work['report']['issues'][0]['text'] == '请确认门店价格'
    assert work['versions'][1]['report']['status'] == 'needs_review'
    exported = staff.get(f'/api/works/{wid}/export?format=md')
    assert exported.status_code == 200
    assert '人工已通过' in exported.text and approval['note'] in exported.text
    assert '本次检查未发现问题' not in exported.text
    poster = post(staff, f'/works/{wid}/compose', {'image_id': iid, 'ratio': '3:4'})
    assert poster.status_code == 200
    assert poster.json()['metadata']['verification'] == 'manual_passed'
    assert post(staff, f'/works/{wid}/approve', {'expected_version': 1, 'note': '旧版本'}).status_code == 409
    edit = {'expected_version': 2, 'title': '修改后', 'body': '已修改正文', 'image_ids': [iid]}
    assert staff.patch(f'/api/works/{wid}', json=edit, headers={'X-Store-Request': '1'}).status_code == 200
    changed = staff.get(f'/api/works/{wid}').json()
    assert changed['report']['status'] == 'unchecked' and 'approval' not in changed['report']
    assert staff.get(f'/api/works/{wid}/export').status_code == 409
    with Session() as s:
        assert s.scalar(select(Audit).where(Audit.action == 'approve_work', Audit.target == wid))


def test_approval_validates_permissions_note_and_source_conflict(clients):
    admin, staff, customer, _ = clients
    wid, _ = review_work(admin, blocked=True)
    data = {'expected_version': 1, 'note': '确认'}
    assert post(customer, f'/works/{wid}/approve', data).status_code == 401
    guest(customer)
    assert post(customer, f'/works/{wid}/approve', data).status_code == 403
    assert staff.post(f'/api/works/{wid}/approve', json=data).status_code == 403
    assert post(staff, f'/works/{wid}/approve', {**data, 'note': '   '}).status_code == 422
    assert post(staff, f'/works/{wid}/approve', data).status_code == 409
    assert post(staff, '/works/missing/approve', data).status_code == 404


def repair_job(admin, wid, version=1):
    with Session() as s:
        j = Job(kind='repair', actor_id=admin.get('/api/me').json()['user']['id'], target_id=wid,
                payload=json.dumps({'expected_version': version}))
        s.add(j)
        s.commit()
        return j.id


def fixture_model(monkeypatch, during=None, fail=False, unresolved=False):
    calls = []
    async def model(instruction, data, max_tokens=2400, schema=None):
        calls.append((schema, data))
        if fail:
            raise ValueError('测试连接失败')
        if schema is ai.GeneratedArticle:
            if during:
                during()
            return {'title': '调整后的标题', 'body': '请根据使用场景核对产品配置。', 'pending': []}, {}
        return {'issues': [], 'pending': ['软件适配仍需确认'] if unresolved else [],
                'claims': [{'text': '产品配置', 'source_id': data['evidence'][0]['id']}]}, {}
    monkeypatch.setattr(ai, 'model_json', model)
    return calls


def test_auto_repair_uses_review_rechecks_and_saves_new_version(clients, monkeypatch):
    admin = clients[0]
    wid, _ = review_work(admin)
    calls = fixture_model(monkeypatch)
    jid = repair_job(admin, wid)
    asyncio.run(ai.run_text_job(jid))
    with Session() as s:
        j, w = s.get(Job, jid), s.get(Work, wid)
        assert j.status == 'completed', j.error
        assert w.version == 2
        c, r = json.loads(w.content), json.loads(w.report)
        assert c['title'] == '调整后的标题' and c['pending'] == []
        assert r['status'] == 'passed'
        assert len(c['images']) >= 1
        assert s.scalar(select(WorkVersion).where(WorkVersion.work_id == wid, WorkVersion.version == 1))
    assert [c[0] for c in calls] == [ai.GeneratedArticle, ai.VerificationResult]
    assert calls[0][1]['report']['issues'][0]['text'] == '请确认门店价格'


@pytest.mark.parametrize('change', ['edit', 'approve', 'cancel', 'failure', 'unresolved'])
def test_auto_repair_never_overwrites_new_decisions_or_hides_failure(clients, monkeypatch, change):
    admin = clients[0]
    wid, _ = review_work(admin)
    jid = repair_job(admin, wid)
    def during():
        with Session() as s:
            if change == 'cancel':
                s.get(Job, jid).status = 'cancelled'
            if change in {'edit', 'approve'}:
                w = s.get(Work, wid)
                w.version = 2
                w.report = json.dumps({'status': 'manual_passed' if change == 'approve' else 'unchecked'})
            s.commit()
    fixture_model(monkeypatch, during=during, fail=change == 'failure', unresolved=change == 'unresolved')
    asyncio.run(ai.run_text_job(jid))
    with Session() as s:
        w, j = s.get(Work, wid), s.get(Job, jid)
        if change == 'unresolved':
            assert j.status == 'completed', j.error
            assert w.version == 2 and json.loads(w.report)['status'] == 'needs_review'
            assert '软件适配仍需确认' in json.loads(w.report)['pending']
        else:
            assert json.loads(w.content)['title'] != '调整后的标题'
            assert j.status == ('cancelled' if change == 'cancel' else 'failed')


def test_repair_endpoint_captures_version_and_rejects_stale_request(clients, monkeypatch):
    admin, staff, customer, _ = clients
    wid, _ = review_work(admin)
    calls = []
    monkeypatch.setattr('backend.main.spawn_job', lambda *args: calls.append(args) or 'test-job')
    assert post(customer, f'/works/{wid}/repair', {'expected_version': 1}).status_code == 401
    assert post(staff, f'/works/{wid}/repair', {'expected_version': 0}).status_code in {409, 422}
    response = post(staff, f'/works/{wid}/repair', {'expected_version': 1})
    assert response.status_code == 200
    assert calls[0][0] == 'repair' and calls[0][-1]['expected_version'] == 1


def test_queued_verification_cannot_replace_manual_approval(clients, monkeypatch):
    admin = clients[0]
    wid, _ = review_work(admin)
    calls = fixture_model(monkeypatch)
    with Session() as s:
        j = Job(kind='verify', actor_id=admin.get('/api/me').json()['user']['id'], target_id=wid,
                payload=json.dumps({'expected_version': 1}))
        s.add(j)
        s.commit()
        jid = j.id
    assert post(admin, f'/works/{wid}/approve', {'expected_version': 1, 'note': '人工核对完成'}).status_code == 200
    asyncio.run(ai.run_text_job(jid))
    assert not calls
    assert admin.get(f'/api/works/{wid}').json()['report']['status'] == 'manual_passed'
