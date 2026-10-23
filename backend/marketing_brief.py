"""Prepare an editable marketing brief from a bound consultation, without model calls."""
import json
from types import SimpleNamespace
from sqlalchemy import select
from .db import Message, DialogueState
from .knowledge import knowledge
from .requirements import build_requirements
from .chat_materials import bound_conversation, message_preview

UNKNOWN = {'', '待确认', '待了解', '未提及', '未知', '尚未了解', '未明确', 'unknown'}


def prepare_chat_brief(session, cid, actor, selected_product=''):
    conversation = bound_conversation(session, cid, actor)
    messages = list(session.scalars(select(Message).where(Message.conversation_id == cid).order_by(Message.seq)))
    customer = [message for message in messages if message.role == 'customer']
    row = session.get(DialogueState, cid)
    state = json.loads(row.state) if row else {}
    locks = json.loads(conversation.locked)
    needs = state.get('needs') or build_requirements(json.loads(conversation.analysis),
        [{'id': m.id, 'role': m.role, 'content': m.content, 'seq': m.seq} for m in messages], locks, conversation.stage)
    needs = {**needs, **{key: {**value, 'status': 'known'} for key, value in locks.items()}}

    def clean(text):
        # Reuse the same privacy treatment as the material picker.
        excerpt=SimpleNamespace(id='',role='customer',seq=0,created_at='',content=text)
        return message_preview(session,excerpt,conversation)['content']

    def value(key):
        item = needs.get(key, {})
        text = str(item.get('value') or '').strip()
        return '' if item.get('status') == 'unknown' or text.lower() in UNKNOWN else clean(text)

    products = {product['id'] for product in knowledge.products()}
    if selected_product and selected_product not in products:
        raise ValueError('请选择有效的产品型号')
    product_id = selected_product
    if not product_id:
        selection = state.get('selection') or {}
        if selection.get('status') == 'confirmed':
            option = next((item for item in state.get('options', []) if item['id'] == selection.get('option_id')), {})
            product_id = option.get('product_id', '')
        topic_ids = list(dict.fromkeys((state.get('topic') or {}).get('product_ids', [])))
        if not product_id and len(topic_ids) == 1:
            product_id = topic_ids[0]
        if product_id not in products:
            product_id = ''

    evidence = set()
    for key in ['user', 'tasks', 'software', 'budget', 'concerns', 'progress', 'next_step']:
        if not value(key):continue
        item = needs.get(key, {})
        evidence.update(mid for mid in item.get('evidence', []) if isinstance(mid, str))
        evidence.update(quote['message_id'] for quote in item.get('quotes', []) if quote.get('message_id'))
    chosen = [message for message in customer if message.id in evidence or message.seq > conversation.analysis_seq]
    chosen = (chosen or customer)[-20:]
    ids = [message.id for message in chosen]
    scene = '；'.join(part for part in [value('tasks'), '必用软件：'+value('software') if value('software') else ''] if part)
    if not scene and chosen:
        scene = '客户描述：'+'；'.join(message_preview(session, message, conversation)['content'] for message in chosen[-5:])
    emphasis = '\n'.join(label+'：'+value(key) for key, label in
        [('budget', '购机预算'), ('concerns', '主要顾虑'), ('progress', '购机意向'), ('next_step', '下一步安排')] if value(key))
    brief = {'product_id': product_id, 'audience': value('user')[:500], 'scene': scene[:1000],
             'user_problem': value('concerns')[:1000], 'emphasis': emphasis[:1000], 'chat_message_ids': ids}
    brief['import_context'] = {'conversation_id': cid, 'message_count': len(ids), 'source_seq': conversation.seq,
                              'imported_fields': [key for key in ['product_id', 'audience', 'scene', 'user_problem', 'emphasis'] if brief[key]],
                              'missing_fields': [key for key in ['product_id', 'audience', 'scene'] if not brief[key]]}
    return brief
