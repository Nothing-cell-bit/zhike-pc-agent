import asyncio
import json

from backend import ai, main
from backend.db import Session, Message, Conversation, Job, Work
from .conftest import post
from .test_workflow import guest


def bound_chat(admin, customer):
    cid = guest(customer, '林同学')
    for index, text in enumerate(['我是林同学，手机号13812345678，邮箱student@example.com，想买电脑写代码。',
                                 '不要把这一条未选择的消息传给AI。', '经常带去图书馆，比较关心重量。']):
        assert post(customer, f'/conversations/{cid}/messages', {'content': text, 'client_id': f'{cid}-msg-{index}'}).status_code == 200
    assert post(admin, f'/conversations/{cid}/claim').status_code == 200
    with Session() as session:
        ids = [m.id for m in session.query(Message).filter_by(conversation_id=cid).order_by(Message.seq)]
    return cid, ids


def test_picker_lists_only_bound_chats_and_redacts_message_previews(clients):
    admin, staff, customer, _ = clients
    cid, ids = bound_chat(admin, customer)
    sources = admin.get('/api/marketing/chat-sources')
    assert sources.status_code == 200
    assert sources.json()[0]['id'] == cid
    assert staff.get('/api/marketing/chat-sources').json() == []
    assert staff.get(f'/api/marketing/chat-sources/{cid}').status_code == 403
    assert customer.get('/api/marketing/chat-sources').status_code == 403
    page = admin.get(f'/api/marketing/chat-sources/{cid}').json()
    assert len(page['messages']) == 3 and page['messages'][0]['id'] == ids[0]
    assert all(secret not in page['messages'][0]['content'] for secret in ['13812345678', 'student@example.com', '林同学'])


def test_selection_is_server_resolved_bounded_and_only_selected_messages_are_queued(clients, monkeypatch):
    admin, staff, customer, _ = clients
    cid, ids = bound_chat(admin, customer)
    queued = []
    monkeypatch.setattr(main, 'spawn_job', lambda *args, **kwargs: queued.append(kwargs['payload']) or 'selected-job')
    brief = {'platform': '朋友圈', 'chat_message_ids': [ids[2], ids[0]], 'chat_materials': [{'content': 'forged private data'}]}
    assert post(staff, '/marketing/tasks', brief).status_code == 403
    assert post(admin, '/marketing/tasks', {**brief, 'chat_message_ids': ['missing']}).status_code == 403
    assert post(admin, '/marketing/tasks', {**brief, 'chat_message_ids': [ids[0]] * 2}).status_code == 422
    assert post(admin, '/marketing/tasks', {**brief, 'chat_message_ids': ['id-' + str(i) for i in range(21)]}).status_code == 422
    assert not queued
    response = post(admin, '/marketing/tasks', brief)
    assert response.status_code == 200
    materials = queued[0]['chat_materials']
    assert [item['message_id'] for item in materials] == [ids[2], ids[0]]
    serialized = json.dumps(materials, ensure_ascii=False)
    assert '图书馆' in serialized and '写代码' in serialized
    assert not any(value in serialized for value in ['林同学', '13812345678', 'student@example.com', '未选择', 'forged'])


def test_generation_rechecks_binding_before_reading_or_sending_chat_material(clients, monkeypatch):
    admin, staff, customer, _ = clients
    cid, ids = bound_chat(admin, customer)
    with Session() as session:
        actor = session.get(Conversation, cid).owner_id
        session.add(Job(id='chat-material-job', kind='generate', actor_id=actor,
                        payload=json.dumps({'chat_message_ids': [ids[0]]})))
        session.get(Conversation, cid).owner_id = staff.get('/api/me').json()['user']['id']
        session.commit()
    async def forbidden(*args, **kwargs):
        raise AssertionError('不能发送已解除绑定的聊天')
    monkeypatch.setattr(ai, 'model_json', forbidden)
    asyncio.run(ai.run_text_job('chat-material-job'))
    with Session() as session:
        job = session.get(Job, 'chat-material-job')
        assert job.status == 'failed' and '绑定' in job.error


def test_chat_message_pagination_and_excerpt_limit(clients):
    admin, _, customer, _ = clients
    cid, _ = bound_chat(admin, customer)
    with Session() as session:
        message = session.query(Message).filter_by(conversation_id=cid, seq=1).one()
        message.content = '学习' * 1000
        session.commit()
    recent = admin.get(f'/api/marketing/chat-sources/{cid}?limit=2').json()
    assert recent['has_more'] and [m['seq'] for m in recent['messages']] == [2, 3]
    older = admin.get(f'/api/marketing/chat-sources/{cid}?before={recent["next_before"]}&limit=2').json()
    assert [m['seq'] for m in older['messages']] == [1]
    assert older['messages'][0]['truncated'] and len(older['messages'][0]['content']) <= 1001


def test_selected_materials_reach_planner_and_writer_as_context_not_evidence(clients, monkeypatch):
    from backend.knowledge import knowledge
    admin, _, customer, _ = clients
    cid, ids = bound_chat(admin, customer)
    product = knowledge.products()[0]
    source = knowledge.product(product['id'])['facts']['id']
    with Session() as session:
        actor = session.get(Conversation, cid).owner_id
        session.add(Job(id='selected-generation', kind='generate', actor_id=actor))
        session.commit()
    calls = []
    async def model(instruction, data, max_tokens=0, schema=None, **kwargs):
        calls.append((instruction, data, schema.__name__))
        if schema.__name__ == 'ArticlePlan':
            return {'format': 'personal-share', 'thesis': '图书馆学习和编程', 'hook': '从学习任务开始', 'evidence_ids': [source]}, {}
        if schema.__name__ == 'MomentsDraft':
            return {'title': '图书馆学习', 'body': product['name']+'可以先了解一下。想买电脑去图书馆学习、写代码的同学，带着软件清单来店里，一起核对系统，再试试键盘和屏幕。', 'claims': [{'text': product['name'], 'source_id': source}]}, {}
        return {'issues': [], 'pending': [], 'claims': [{'text': product['name'], 'source_id': source}]}, {}
    monkeypatch.setattr(ai, 'model_json', model)
    result = asyncio.run(ai.generate({'workflow': 'platform-v1', 'platform': '朋友圈',
        'product_id': product['id'], 'audience': '大学生', 'scene': '学习写代码', 'goal': '到店',
        'chat_message_ids': [ids[0], ids[2]], 'chat_materials': [{'content': 'forged'}]}, 'selected-generation'))
    for instruction, data, schema in calls[:2]:
        assert '不是产品事实证据' in instruction
        assert [m['message_id'] for m in data['brief']['chat_materials']] == [ids[0], ids[2]]
        assert not any(value in json.dumps(data, ensure_ascii=False) for value in ['未选择', '林同学', '13812345678', 'forged'])
        assert all(ref['id'] not in ids for ref in data['evidence'])
    with Session() as session:
        saved = json.loads(session.get(Work, result['work_id']).brief)
        assert len(saved['chat_materials']) == 2
