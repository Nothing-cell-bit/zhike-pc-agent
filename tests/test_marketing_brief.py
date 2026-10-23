import json

from backend.db import Session, Conversation, Message, DialogueState
from backend.knowledge import knowledge
from .test_chat_materials import bound_chat


def analyzed_chat(admin, customer):
    cid, ids = bound_chat(admin, customer)
    product = knowledge.products()[0]
    with Session() as session:
        session.get(Message, ids[0]).content = '我是林同学，大学新生，预算6000元以内，学习和写代码，需要Codex，准备换机，周末到店。电话13812345678。'
        values = {'user': '大学新生', 'tasks': '学习和写代码', 'software': 'Codex',
                  'budget': '6000元以内', 'progress': '准备换机', 'next_step': '周末到店', 'concerns': '尚未了解'}
        needs = {key: {'value': value, 'status': 'unknown' if key == 'concerns' else 'known',
                      'evidence': [] if key == 'concerns' else [ids[0]], 'quotes': []} for key, value in values.items()}
        needs['tasks']['evidence'].append(ids[2])
        state = {'needs': needs, 'topic': {'product_ids': [product['id']]}, 'selection': {'status': 'unconfirmed'}}
        row = session.get(DialogueState, cid)
        if row: row.state = json.dumps(state)
        else: session.add(DialogueState(conversation_id=cid, message_seq=3, state=json.dumps(state)))
        session.get(Conversation, cid).analysis_seq = 3
        session.commit()
    return cid, ids, product


def test_transfer_fills_confirmed_needs_product_and_related_materials(clients):
    admin, _, customer, _ = clients
    cid, ids, product = analyzed_chat(admin, customer)
    response = admin.get(f'/api/conversations/{cid}/marketing-brief')
    assert response.status_code == 200
    brief = response.json()
    assert brief['product_id'] == product['id']
    assert brief['audience'] == '大学新生'
    assert '学习和写代码' in brief['scene'] and 'Codex' in brief['scene']
    assert all(value in brief['emphasis'] for value in ['6000元以内', '准备换机', '周末到店'])
    assert '尚未了解' not in json.dumps(brief, ensure_ascii=False)
    assert brief['user_problem'] == ''
    assert brief['chat_message_ids'] == [ids[0], ids[2]]
    assert brief['import_context']['message_count'] == 2
    assert brief['import_context']['conversation_id'] == cid
    assert not any(value in json.dumps(brief, ensure_ascii=False) for value in ['林同学', '13812345678'])


def test_transfer_preserves_manual_overrides_and_explicit_product_choice(clients):
    admin, _, customer, _ = clients
    cid, _, product = analyzed_chat(admin, customer)
    chosen = next(item for item in knowledge.products() if item['id'] != product['id'])
    with Session() as session:
        session.get(Conversation, cid).locked = json.dumps({'budget': {'value': '5000元以内', 'manual': True}})
        session.commit()
    brief = admin.get(f'/api/conversations/{cid}/marketing-brief?product_id={chosen["id"]}').json()
    assert brief['product_id'] == chosen['id']
    assert '5000元以内' in brief['emphasis'] and '6000元以内' not in brief['emphasis']
    assert admin.get(f'/api/conversations/{cid}/marketing-brief?product_id=missing').status_code == 400


def test_transfer_does_not_guess_ambiguous_product_or_unknown_audience(clients):
    admin, _, customer, _ = clients
    cid, _, _ = analyzed_chat(admin, customer)
    with Session() as session:
        row = session.get(DialogueState, cid); state = json.loads(row.state)
        state['topic']['product_ids'] = [p['id'] for p in knowledge.products()[:2]]
        state['needs']['user'] = {'status': 'unknown', 'value': '尚未了解'}
        row.state = json.dumps(state); session.commit()
    brief = admin.get(f'/api/conversations/{cid}/marketing-brief').json()
    assert brief['product_id'] == brief['audience'] == ''
    assert 'product_id' in brief['import_context']['missing_fields'] and 'audience' in brief['import_context']['missing_fields']


def test_transfer_without_analysis_uses_redacted_customer_materials_and_checks_binding(clients):
    admin, staff, customer, _ = clients
    cid, ids = bound_chat(admin, customer)
    response = admin.get(f'/api/conversations/{cid}/marketing-brief')
    assert response.status_code == 200
    brief = response.json()
    assert '写代码' in brief['scene'] and brief['chat_message_ids'] == ids
    assert not any(value in json.dumps(brief, ensure_ascii=False) for value in ['林同学', '13812345678', 'student@example.com'])
    assert staff.get(f'/api/conversations/{cid}/marketing-brief').status_code == 403
    assert customer.get(f'/api/conversations/{cid}/marketing-brief').status_code == 403
