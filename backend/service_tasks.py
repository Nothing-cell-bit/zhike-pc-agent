"""Business work ledger. Draft generation never completes customer-facing work."""
import hashlib
from datetime import datetime,timedelta,timezone
from typing import Literal
from pydantic import BaseModel, Field, ConfigDict
from .dialogue import Evidence, valid_evidence, question_key
from .dialogue_contract import NEED_KEYS
from .db import now


class TaskProposal(BaseModel):
    # Observed task snapshots may be echoed by the planner. Server-owned status,
    # IDs, results and owners are ignored and recomputed, never model writable.
    model_config = ConfigDict(extra='ignore')
    key: str = Field(min_length=1, max_length=100)
    kind: Literal['answer', 'discover', 'recommend', 'compare', 'quote', 'verify']
    title: str = Field(min_length=1, max_length=60)
    target: str = Field(default='', max_length=80)
    scope:Literal['field','detail']='field'
    topic_key:str=Field(default='',max_length=100)
    product_ids: list[str] = Field(default_factory=list, max_length=3)
    depends_on: list[str] = Field(default_factory=list, max_length=4)
    evidence: Evidence
    required_facets:list[str]=Field(default_factory=list,max_length=6)


COMPLETION = {'answer':'客服发送对应答复', 'discover':'客户明确回答、拒答或委托',
              'recommend':'客服发送有效推荐方案', 'compare':'客服发送有效比较方案',
              'quote':'客服发送已核价报价卡', 'verify':'门店登记核实结果'}
TERMINAL = {'completed', 'cancelled'}


def verification_deadline(task):
    if task.get('due_at'):return task['due_at']
    if task.get('created_at'):
        try:return (datetime.fromisoformat(task['created_at'])+timedelta(hours=4)).isoformat()
        except (ValueError,TypeError):pass
    return (datetime.now(timezone.utc)+timedelta(hours=4)).isoformat()


def proposal_errors(state,proposals):
    existing={t['key']:t for t in state.get('tasks',[])};items={**existing};errors=[]
    for proposal in proposals:
        key=proposal['key'];old=existing.get(key)
        if old and (old['kind']!=proposal['kind'] or sorted(old.get('product_ids',[]))!=sorted(proposal.get('product_ids',[]))):
            errors.append('任务key已用于不同工作或产品：'+key)
        items[key]=proposal
    for key,item in items.items():
        if any(dep not in items for dep in item.get('depends_on',[])):errors.append('任务依赖不存在：'+key)
    def visit(key,path):
        if key in path:return True
        return any(visit(dep,path|{key}) for dep in items.get(key,{}).get('depends_on',[]) if dep in items)
    if any(visit(key,set()) for key in items):errors.append('任务依赖不能成环')
    return errors


def refresh_tasks(state):
    tasks=state.get('tasks',[]);by_key={t['key']:t for t in tasks}
    for task in tasks:
        if task['status'] in TERMINAL:continue
        if task['kind']=='verify':task.setdefault('due_at',verification_deadline(task))
        if task['kind']=='discover':
            key=task_key(task)
            needs=state.get('needs',{}).get(key,{})
            resolved=next((q for q in reversed(state.get('questions',[])) if question_key(q)==key
                           and q.get('status') in {'answered','declined','delegated'}),None)
            if task.get('scope','field')=='field' and needs.get('status') in {'known','partial'} or resolved:
                task.update(status='completed',result=needs.get('value') if needs.get('status') in {'known','partial'} else resolved['status'],completed_at=now())
                continue
        missing=[key for key in task.get('depends_on',[]) if key not in by_key or by_key[key]['status']!='completed']
        task['blockers']=missing
        if missing:task['status']='blocked'
        elif task['status']=='blocked':task['status']='waiting_staff' if task['kind']=='verify' else 'ready'


def sync_tasks(state, proposals, messages, seq):
    tasks=state.setdefault('tasks',[])
    for raw in proposals:
        item=TaskProposal.model_validate(raw).model_dump()
        if item['kind']=='compare' and not item['required_facets']:
            from .service_delivery import requested_facets
            item['required_facets']=requested_facets(item['title']) or ['weight','resolution','gamut','os']
        if not valid_evidence(item['evidence'],messages):continue
        # Stable keys are scoped to product/kind; revisiting a topic is not a new work item.
        key=item['key'];existing=next((t for t in tasks if t['key']==key),None)
        if existing:continue
        identifier=hashlib.sha256((key+'|'+item['kind']+'|'+'|'.join(sorted(item['product_ids']))).encode()).hexdigest()[:24]
        tasks.append({**item,'id':identifier,'status':'waiting_staff' if item['kind']=='verify' else 'ready',
            'owner':'staff' if item['kind']=='verify' else 'assistant','completion':COMPLETION[item['kind']],
            'created_seq':seq,'created_at':now(),'blockers':[],'result':'',
            **({'due_at':(datetime.now(timezone.utc)+timedelta(hours=4)).isoformat()} if item['kind']=='verify' else {})})
    refresh_tasks(state)


def observe_delivery(state, action, content, message_id, seq):
    """Called only after a real staff message is stored; edited-away questions do not count."""
    for task in state.get('tasks',[]):
        if task['kind']=='verify' and task['status']=='completed' and task['id'] in action.get('verification_ids',[]):
            # A generated draft or an edited-away conclusion is not customer feedback.
            answer=action.get('answer','').strip()
            if answer and answer in content and task.get('feedback_status')!='sent':
                task.update(feedback_status='sent',feedback_message_id=message_id,feedback_at=now())
        if task['status'] in TERMINAL or task['status']=='blocked':continue
        question=action.get('question')
        if task['kind']=='discover' and question and question['text'] in content:
            if question_key(question)==task_key(task):
                task.update(status='waiting_customer',owner='customer',sent_message_id=message_id)
        if task['id'] not in action.get('task_ids',[]):continue
        if task['kind']=='verify' or task['kind']=='discover':continue
        if task['kind'] in {'recommend','compare'} and not action.get('option_ids'):continue
        if task['kind']=='quote' and not any(q.get('delivery_status')=='sent' and q.get('sent_message_id')==message_id for q in state.get('quotes',[])):continue
        if task['kind']=='compare' or task['kind']=='answer' and task.get('required_facets'):
            required=task.get('required_facets') or ['weight','resolution','gamut','os']
            delivery=next((x for x in reversed(state.get('deliverables',[])) if set(task.get('product_ids',[]))<=set(x['product_ids'])
                and set(required)<=set(x['facets']) and x['text'].strip() in content),None)
            if not delivery:continue
            task.update(delivery_id=delivery['id'],sent_message_id=message_id)
            delivery.update(sent_message_id=message_id,status='sent' if delivery['complete'] else 'partial')
            covered=[cell for cell in delivery['cells'] if cell['product_id'] in task.get('product_ids',delivery['product_ids']) and cell['facet'] in required]
            if not covered or any(cell['status']!='sourced' for cell in covered):
                task.update(status='waiting_staff',owner='staff',result='已交付部分参数，缺失字段待核实');continue
        # An edited answer may omit the work result; leave it open for staff review.
        delivered=next((p for p in state.get('presentations',[]) if p['message_id']==message_id),{})
        verified_delivery=task['kind']=='quote' or task['kind'] in {'recommend','compare'} and bool(delivered.get('option_ids'))
        if content!=action.get('reply',content) and not verified_delivery:continue
        task.update(status='completed',result=content[:1000],sent_message_id=message_id,completed_seq=seq,completed_at=now())
    refresh_tasks(state)


def task_key(task):
    if task.get('scope')=='detail':return task.get('topic_key') or task.get('target','')
    if task.get('target')=='purchase_intent':return 'progress'
    return NEED_KEYS.get(task.get('target'),task.get('target'))
