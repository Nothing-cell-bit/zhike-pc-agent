"""Persistent reception reminders; no scheduler or automatic customer messages."""
import json
from datetime import datetime,timezone
from sqlalchemy import select
from .db import Conversation,DialogueState
from .service_tasks import verification_deadline


def verification_notifications(session,owner_id):
    rows=session.execute(select(Conversation,DialogueState).join(DialogueState,Conversation.id==DialogueState.conversation_id)
                         .where(Conversation.owner_id==owner_id,Conversation.status!='closed'))
    result=[];current=datetime.now(timezone.utc)
    for conversation,row in rows:
        state=json.loads(row.state)
        for task in state.get('tasks',[]):
            if task.get('kind')!='verify' or task.get('status')=='cancelled' or task.get('feedback_status')=='sent':continue
            awaiting=task.get('status')=='completed'
            due=(task.get('completed_at') or row.updated_at) if awaiting else verification_deadline(task)
            try:deadline=datetime.fromisoformat(due)
            except (ValueError,TypeError):continue
            if deadline.tzinfo is None or deadline>current:continue
            result.append({'id':'verify:'+conversation.id+':'+task['id'],'task_id':task['id'],
                'kind':'verification','conversation_id':conversation.id,'customer_name':conversation.customer_name,
                'purpose':task['title'],'due_at':due,'status':'awaiting_feedback' if awaiting else task['status'],
                'conversation_ref':conversation.id[-6:]})
    return sorted(result,key=lambda item:item['due_at'])


def followup_content(session,conversation,goals,scripts):
    row=session.get(DialogueState,conversation.id)
    state=json.loads(row.state) if row else {}
    pending=[t for t in state.get('tasks',[]) if t.get('kind')=='verify' and t.get('status') not in {'completed','cancelled'}]
    if pending:
        titles='、'.join(t['title'] for t in pending[:3])
        for day in goals:
            goals[day]='先处理门店待办，再确认客户后续安排'
            scripts[day]='客服处理提示（未发送）：请先处理“'+titles+'”，登记结果后再准备客户回复；没有新结果时不重复承诺，也不催促客户。'
    elif state.get('goal')=='quote' or state.get('quotes'):
        scripts[3]='您好，上次的配置和报价方案看过了吗？您对配置、价格或购买安排还有哪些顾虑？'
    return goals,scripts


def followup_draft(session,followup):
    if followup.status!='pending' or not followup.generated or followup.offset_days not in {1,3,5}:
        return {'purpose':followup.purpose,'script':followup.script}
    conversation=session.get(Conversation,followup.conversation_id)
    if not conversation:return {'purpose':followup.purpose,'script':followup.script}
    goals={1:'补齐关键需求与遗留疑问',3:'方案反馈与购买顾虑',5:'购买、到店与后续安排'}
    scripts={1:'您好，上次咨询还有哪些问题需要补充？',3:'您好，上次讨论的方案看过了吗？还有哪些顾虑需要我们一起核对？',5:'您好，想了解一下您的购机或到店安排。如暂时不需要，我会停止后续跟进。'}
    goals,scripts=followup_content(session,conversation,goals,scripts)
    return {'purpose':goals[followup.offset_days],'script':scripts[followup.offset_days]}
