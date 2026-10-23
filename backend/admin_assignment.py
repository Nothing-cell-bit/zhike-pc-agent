"""Administrator overview and atomic, owner-checked conversation allocation."""
import json
from collections import Counter
from fastapi import HTTPException
from pydantic import BaseModel,Field,field_validator
from sqlalchemy import select,update,func
from .db import User,Conversation,Message,Followup,ConversationDismissal,Audit,now


class AssignmentRow(BaseModel):
    id:str=Field(min_length=1,max_length=64)
    expected_owner:str|None=Field(...,min_length=1,max_length=64)


class AssignmentInput(BaseModel):
    owner_id:str|None=Field(...,min_length=1,max_length=64)
    conversations:list[AssignmentRow]=Field(min_length=1,max_length=50)

    @field_validator('conversations')
    @classmethod
    def unique_rows(cls,rows):
        if len({row.id for row in rows})!=len(rows):raise ValueError('请勿重复选择同一对话')
        return rows


def overview(session):
    users={user.id:user for user in session.scalars(select(User).where(User.role.in_(['staff','admin'])))}
    rows=list(session.scalars(select(Conversation).order_by(Conversation.updated_at.desc())))
    message_counts=dict(session.execute(select(Message.conversation_id,func.count()).group_by(Message.conversation_id)).all())
    pending=dict(session.execute(select(Followup.owner_id,func.count()).join(Conversation,Conversation.id==Followup.conversation_id)
        .where(Followup.status=='pending',Followup.owner_id==Conversation.owner_id,Conversation.status!='closed').group_by(Followup.owner_id)).all())
    active=Counter(row.owner_id for row in rows if row.status!='closed' and row.owner_id)
    return {'summary':{'total':len(rows),'unassigned':sum(not row.owner_id and row.status!='closed' for row in rows),
                        'active':sum(row.status=='active' for row in rows),'closed':sum(row.status=='closed' for row in rows)},
            'staff':[{'id':user.id,'username':user.username,'display_name':user.display_name,'active':user.active,
                      'active_count':active[user.id],'pending_followups':pending.get(user.id,0)} for user in users.values() if user.role=='staff'],
            'conversations':[{'id':row.id,'customer_name':row.customer_name,'owner_id':row.owner_id,
                'owner_name':users[row.owner_id].display_name if row.owner_id in users else '未分配' if not row.owner_id else '负责人不可用',
                'owner_active':bool(row.owner_id in users and users[row.owner_id].active),
                'status':row.status,'stage':row.stage,'updated_at':row.updated_at,'message_count':message_counts.get(row.id,0)} for row in rows]}


def assign(session,actor_id,body):
    target=body.owner_id
    if target:
        employee=session.get(User,target)
        if not employee or employee.role!='staff' or not employee.active:raise HTTPException(400,'只能分配给已启用的客服账号')
    for item in body.conversations:
        row=session.get(Conversation,item.id)
        if not row:raise HTTPException(404,'所选对话不存在，请刷新')
        if row.status=='closed':raise HTTPException(409,'已结束的对话不能分配，请刷新后重新选择')
        if row.owner_id!=item.expected_owner:raise HTTPException(409,'有对话的负责人已变化，请刷新后重新选择')
    for item in body.conversations:
        conditions=[Conversation.id==item.id,Conversation.owner_id==item.expected_owner,Conversation.status!='closed']
        if target:
            conditions.append(select(User.id).where(User.id==target,User.role=='staff',User.active==True).exists())
        changed=session.execute(update(Conversation).where(*conditions).values(owner_id=target,status='active' if target else 'waiting',updated_at=now()).execution_options(synchronize_session=False))
        if not changed.rowcount:raise HTTPException(409,'对话负责人或客服状态已变化，请刷新后重新选择')
        session.execute(update(Followup).where(Followup.conversation_id==item.id,Followup.status=='pending').values(owner_id=target or ''))
        if target:
            dismissed=session.get(ConversationDismissal,(target,item.id))
            if dismissed:session.delete(dismissed)
        session.add(Audit(actor_id=actor_id,action='assign_conversation',target=json.dumps(
            {'conversation_id':item.id,'previous_owner':item.expected_owner,'owner_id':target},ensure_ascii=False)))
    session.commit()
    return {'count':len(body.conversations),'owner_id':target}
