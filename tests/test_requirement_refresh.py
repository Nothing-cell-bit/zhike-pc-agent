from .dialogue_fakes import protocol_model
import asyncio
import json
import pytest
from sqlalchemy import select
from backend import ai
from backend.db import Session, Conversation, Message, Job
from backend.requirements import build_requirements
from .test_workflow import guest


@pytest.mark.parametrize('field,value,answer', [
    ('software', '黑猴', '没有了'),
    ('software', '单位自研的云栈', '就这一款'),
    ('tasks', '整理档案', '对，仅此而已'),
    ('concerns', '太重', '其他没有特别在意的'),
    ('budget', '8000元以内', '是的'),
])
def test_confirmation_evidence_is_not_a_new_requirement(field, value, answer):
    messages = [dict(id='a', role='customer', text=value, seq=1),
                dict(id='b', role='customer', text=answer, seq=3)]
    raw = {field: {'status': 'known', 'quotes': [
        {'message_id': 'a', 'quote': value, 'kind': 'fact'},
        {'message_id': 'b', 'quote': answer, 'kind': 'context'}]}}
    result = build_requirements(raw, messages)
    assert result[field]['value'] == value
    assert len(result[field]['quotes']) == 2
    assert build_requirements(result, messages)[field]['value'] == value


def test_explicit_absence_differs_from_unknown_and_does_not_repeat_question():
    messages = [dict(id='a', role='customer', text='不需要特定软件', seq=1)]
    raw = {'software': {'status': 'known', 'confirmed_none': True,
                       'quotes': [{'message_id': 'a', 'quote': '不需要特定软件', 'kind': 'context'}]}}
    result = build_requirements(raw, messages)
    assert result['software']['value'] == '无指定软件或游戏'
    assert result['software']['status'] == 'known'
    assert build_requirements({}, messages)['software']['status'] == 'unknown'


def test_confirmation_alone_cannot_be_displayed_as_a_fact():
    messages = [dict(id='a', role='customer', text='对', seq=1)]
    result = build_requirements({'software': {'status': 'known', 'quotes': [
        {'message_id': 'a', 'quote': '对', 'kind': 'context'}]}}, messages)
    assert result['software']['status'] == 'unknown'


def test_analysis_uses_one_call_and_no_marketing_system_prompt(monkeypatch):
    calls = []
    async def model(*args, **kwargs):
        calls.append((args, kwargs))
        return {}, {'total_tokens': 100}
    monkeypatch.setattr(ai, 'model_json', model)
    _, usage = asyncio.run(ai.extract_requirement_facts([]))
    assert len(calls) == 1
    assert calls[0][1]['system_prompt'] == ''
    assert usage['total_tokens'] == 100


def test_auto_and_manual_refresh_share_job_but_new_customer_reply_gets_new_job(clients, monkeypatch):
    _, _, customer, _ = clients
    cid = guest(customer)
    async def hold(_):
        await asyncio.sleep(60)
    monkeypatch.setattr(ai, 'run_text_job', hold)
    async def scenario():
        await ai.delayed_analysis(cid, 'customer')
        timer = ai.analysis_timers[cid]
        first = ai.spawn_job('analysis', 'staff', cid)
        second = ai.spawn_job('analysis', 'customer', cid)
        assert first == second
        await asyncio.sleep(0)
        assert timer.cancelled()
        with Session() as s:
            j = s.get(Job, first);j.status = 'running'
            c = s.get(Conversation, cid);c.seq = 1
            s.add(Message(id='new-customer', conversation_id=cid, sender_id=c.customer_id,
                          role='customer', content='补充一个新要求', client_id='refresh-new', seq=1))
            s.commit()
        third = ai.spawn_job('analysis', 'staff', cid)
        assert third != first
        assert ai.spawn_job('analysis', 'staff', cid) == third
        with Session() as s:
            assert len(list(s.scalars(select(Job).where(Job.kind == 'analysis')))) == 2
    asyncio.run(scenario())
