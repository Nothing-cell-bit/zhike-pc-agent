import asyncio
import copy
import json
import pytest
from datetime import datetime, timedelta, timezone

from backend import dialogue
from backend.db import Session, Conversation, DialogueState
from backend.service_tasks import sync_tasks
from .test_reply_choices import seed, q
from .test_service_workflow import turn, service_protocol,progress_result
from .test_dialogue_workflow import add
from .conftest import post


def pending_state(clients):
    cid, staff, state = seed(clients)
    with Session() as s:
        messages = dialogue.messages_for(s, cid)
        sync_tasks(state, [{'key':'verify:fit','kind':'verify','title':'核实软件实际适配性',
                           'evidence':{'message_id':messages[-1]['id'],'quote':messages[-1]['text']}}], messages, messages[-1]['seq'])
        state['workflow_version'] = 3
        row = s.get(DialogueState, cid)
        row.state = json.dumps(state, ensure_ascii=False)
        s.commit()
    return cid, staff, state


def test_pending_verification_owns_next_step_after_staff_send(clients):
    cid, staff, state = pending_state(clients)
    assert post(staff, f'/conversations/{cid}/messages', {'content':'具体表现还需要核实。','client_id':'pending-send'}).status_code == 200
    assert dialogue.view(cid)['next_owner'] == 'staff'


def test_acknowledgement_does_not_generate_repeated_wait_promises(clients):
    from backend.service_workflow import run
    cid, staff, state = pending_state(clients)
    sent = post(staff, f'/conversations/{cid}/messages', {'content':'具体表现还需要核实。','client_id':'receipt-send'}).json()
    add(cid, 'customer', 'ok')
    calls = []
    async def model(_, data, *args, **kwargs):
        name = kwargs['schema'].__name__
        calls.append(name)
        result = turn(data['current_turn'])
        result.update(unresolved=[], tasks=[], next_question=None)
        result['plan'].update(customer_act='acknowledge', acknowledged_message_id=sent['id'])
        if name == 'ServiceCustomerUpdate':return {'changes':[], 'resolutions':[]}, {}
        if name == 'ServicePlanning':return result, {}
        raise AssertionError('没有进展时不应调用话术生成与审核')
    result = asyncio.run(run(cid, service_protocol(model)))
    state = result['dialogue']
    assert state['action']['kind'] == 'wait'
    assert state['action']['reply'] == '' and state['action']['candidates'] == []
    assert state['next_owner'] == 'staff'
    assert calls == ['ServiceCustomerUpdate','ServicePlanning']


def test_execution_claim_is_blocked_even_if_semantic_auditor_passes():
    from backend.service_workflow import validate_choices
    state = {'needs':{},'questions':[],'tasks':[{'kind':'verify','status':'waiting_staff'}],
             'action':{'kind':'inform'},'continuation':{'mode':'answer'}}
    candidates = [{'answer':'我这边正在核实，有结果第一时间通知您。','question':None,'citations':[]}]
    errors = validate_choices(candidates, state, [], {'sources':[]})
    assert any('执行' in e or '通知' in e for e in errors)


@pytest.mark.parametrize('text',['有结果我第一时间同步您。','有结果后第一时间结合预算给您建议。'])
def test_immediate_sync_is_also_an_unsupported_customer_contact_promise(text):
    from backend.service_workflow import validate_choices
    state={'needs':{},'questions':[],'tasks':[],'action':{'kind':'inform'},'continuation':{'mode':'answer'}}
    errors=validate_choices([{'answer':text,'question':None,'citations':[]}],state,[],{'sources':[]})
    assert any('通知' in error for error in errors)


def test_service_planner_cannot_write_personal_facts_a_second_time():
    from backend.service_workflow import ServicePlanning
    from pydantic import ValidationError
    with pytest.raises(ValidationError):
        ServicePlanning.model_validate({'plan':turn({'id':'customer','text':'预算三万'})['plan'],'needs':{'changes':[]}})


def test_primary_reply_advances_a_normal_plan_without_an_extra_acknowledgement(clients):
    from backend.service_workflow import run
    cid,_,_=seed(clients)
    add(cid,'customer','主要用于设计')
    question=q('required_software','设计主要需要运行哪些具体应用？')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[],next_question=question)
        result['plan']['customer_act']='provide_information'
        result['candidates'][1]['question']=question
        return result,{}
    state=asyncio.run(run(cid,service_protocol(model)))['dialogue']
    assert state['action']['candidates'][0]['question']['target']=='required_software'


def test_local_fact_wait_does_not_suppress_independent_customer_context(clients):
    from backend.service_workflow import run
    cid,staff,_=pending_state(clients)
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'具体适配性需要门店核实。','client_id':'progress-receipt'}).json()
    add(cid,'customer','ok')
    question=q('required_software','您主要需要运行哪些具体应用？')
    review_calls=[]
    async def model(_,data,*args,**kwargs):
        name=kwargs['schema'].__name__
        if name=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[],next_question=None)
        result['plan'].update(customer_act='acknowledge',acknowledged_message_id=sent['id'])
        result['candidates'][1]['question']=question
        return result,{}
    delegate=service_protocol(model)
    async def reviewed(*args,**kwargs):
        if kwargs['schema'].__name__=='ProgressReview':
            review_calls.append(args[1])
            return progress_result(question,'具体应用会改变门店需要核查的兼容范围，客户尚未说明，可独立确认'),{}
        return await delegate(*args,**kwargs)
    result=asyncio.run(run(cid,reviewed))['dialogue']
    assert len(review_calls)==1
    assert result['continuation']['mode']=='bridge'
    assert result['action']['kind']=='inform'
    assert result['action']['candidates'][0]['question']['target']=='required_software'
    assert any(c.get('question',{}).get('target')=='required_software' for c in result['action']['candidates'] if c.get('question'))
    assert next(t for t in result['tasks'] if t['kind']=='verify')['status']=='waiting_staff'
    assert not result['questions']  # A suggested question has not been sent.


def test_progress_review_can_confirm_a_real_wait_without_inventing_questions(clients):
    from backend.service_workflow import run
    cid,staff,_=pending_state(clients)
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'具体适配性需要门店核实。','client_id':'real-wait-receipt'}).json()
    add(cid,'customer','收到')
    calls=[]
    async def model(_,data,*args,**kwargs):
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[])
        result['plan'].update(customer_act='acknowledge',acknowledged_message_id=sent['id'])
        return result,{}
    delegate=service_protocol(model)
    async def reviewed(*args,**kwargs):
        if kwargs['schema'].__name__=='ProgressReview':
            calls.append(1)
            return progress_result(reason='该场景的应用与负载已经明确，客户只待当前测试结论，没有独立决策缺口'),{}
        return await delegate(*args,**kwargs)
    state=asyncio.run(run(cid,reviewed))['dialogue']
    assert calls==[1] and state['action']['kind']=='wait' and state['action']['candidates']==[]


def test_progress_review_cannot_reask_a_manually_known_field(clients):
    from backend.service_workflow import run
    cid,staff,_=pending_state(clients)
    with Session() as s:
        c=s.get(Conversation,cid);c.locked=json.dumps({'budget':{'value':'7000以内','manual':True}});s.commit()
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'具体适配性需要门店核实。','client_id':'known-progress'}).json()
    add(cid,'customer','ok')
    async def model(_,data,*args,**kwargs):
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[])
        result['plan'].update(customer_act='acknowledge',acknowledged_message_id=sent['id'])
        return result,{}
    delegate=service_protocol(model)
    async def reviewed(*args,**kwargs):
        if kwargs['schema'].__name__=='ProgressReview':return progress_result(q('purchase_budget','预算是多少？'),'尝试确认预算'),{}
        return await delegate(*args,**kwargs)
    state=asyncio.run(run(cid,reviewed))['dialogue']
    assert state['action']['kind']=='wait'
    assert state['needs']['budget']['value']=='7000以内'


def test_progress_review_uses_another_path_when_the_first_is_already_known(clients):
    from backend.service_workflow import run
    cid,staff,_=pending_state(clients)
    with Session() as s:
        c=s.get(Conversation,cid);c.locked=json.dumps({'budget':{'value':'7000以内','manual':True}});s.commit()
    sent=post(staff,f'/conversations/{cid}/messages',{'content':'具体适配性需要门店核实。','client_id':'choose-valid-path'}).json()
    add(cid,'customer','ok')
    software=q('required_software','您需要运行哪些具体应用？')
    async def model(_,data,*args,**kwargs):
        if kwargs['schema'].__name__=='ServiceAudit':return {'errors':[],'invalid_need_fields':[]},{}
        result=turn(data['current_turn']);result.update(unresolved=[],tasks=[])
        result['plan'].update(customer_act='acknowledge',acknowledged_message_id=sent['id'])
        result['candidates'][1]['question']=software
        return result,{}
    delegate=service_protocol(model)
    async def reviewed(*args,**kwargs):
        if kwargs['schema'].__name__=='ProgressReview':
            result=progress_result(q('purchase_budget','预算是多少？'),'检查其他可执行路径')
            result['paths'][1].update(status='useful',question=software)
            return result,{}
        return await delegate(*args,**kwargs)
    state=asyncio.run(run(cid,reviewed))['dialogue']
    assert state['action']['candidates'][0]['question']['target']=='required_software'


def test_verification_can_start_and_reschedule_with_revision_guard(clients, monkeypatch):
    cid, staff, state = pending_state(clients)
    task = state['tasks'][0]
    due = (datetime.now(timezone.utc)+timedelta(hours=2)).isoformat()
    response = post(staff, f'/conversations/{cid}/service-tasks/{task["id"]}',
                    {'revision':state['revision'],'status':'in_progress','due_at':due})
    assert response.status_code == 200
    saved = dialogue.view(cid)
    task = saved['tasks'][0]
    assert task['status'] == 'in_progress' and task['started_by'] and task['due_at'] == due
    assert task['owner'] == 'staff'
    assert saved['action']['message_seq']==state['action']['message_seq']
    assert post(staff, f'/conversations/{cid}/service-tasks/{task["id"]}',
                {'revision':state['revision'],'status':'completed','result':'旧版本结果'}).status_code == 409


def test_verification_notifications_are_independent_of_marketing_followups(clients):
    cid, staff, state = pending_state(clients)
    with Session() as s:
        row=s.get(DialogueState,cid);state=json.loads(row.state)
        state['tasks'][0]['due_at']=(datetime.now(timezone.utc)-timedelta(minutes=1)).isoformat()
        row.state=json.dumps(state);s.commit()
    reminders=staff.get('/api/notifications').json()
    item=next((r for r in reminders if r['kind']=='verification'),None)
    assert item and item['conversation_id']==cid and item['task_id']==state['tasks'][0]['id']
    assert item['purpose']=='核实软件实际适配性'
    assert reminders==staff.get('/api/notifications').json()


def test_new_followup_schedule_uses_135_and_keeps_existing_dates(clients):
    cid, staff, _ = seed(clients)
    assert post(staff,'/followups/plan',{'conversation_id':cid}).status_code==200
    rows=staff.get('/api/followups').json()
    days=sorted(round((datetime.fromisoformat(r['due_at'])-datetime.now(timezone.utc)).total_seconds()/86400) for r in rows)
    assert days==[1,3,5]
    assert post(staff,'/followups/plan',{'conversation_id':cid,'days':[1,3,5]}).status_code==409


def test_uncertain_answer_cannot_become_confirmed_need(clients):
    from backend.service_workflow import fresh_mutations
    cid, _, state=seed(clients)
    staff_message=add(cid,'staff','是只做实时调整，还是做离线渲染？会使用加速吗？')
    add(cid,'customer','不用')
    with Session() as s:messages=dialogue.messages_for(s,cid)
    evidence={'message_id':messages[-1]['id'],'quote':'不用'}
    proposal=turn(messages[-1])
    proposal['needs']['changes']=[{'field':'usage_tasks','operation':'add','fact':{'status':'known','quotes':[{**evidence,'kind':'fact'}]}}]
    proposal['plan']['resolutions']=[{'question_id':messages[-2]['id'],'status':'uncertain','evidence':evidence}]
    admitted=fresh_mutations(proposal,state,messages)
    assert admitted['needs']['changes']==[]


def test_followup_draft_tracks_current_work_but_preserves_staff_edits(clients):
    cid,staff,state=pending_state(clients)
    assert post(staff,'/followups/plan',{'conversation_id':cid}).status_code==200
    items=staff.get('/api/followups').json()
    assert all('客服处理提示' in f['script'] for f in items)
    with Session() as s:
        row=s.get(DialogueState,cid);current=json.loads(row.state)
        current['tasks'][0].update(status='completed',result='核实完成')
        current['goal']='quote';row.state=json.dumps(current);s.commit()
    items=staff.get('/api/followups').json()
    assert all('客服处理提示' not in f['script'] for f in items)
    item=next(f for f in items if '配置和报价' in f['script'])
    response=staff.patch('/api/followups/'+item['id'],json={'script':'客户约定周五联系'},headers={'X-Store-Request':'1'})
    assert response.status_code==200
    assert next(f for f in staff.get('/api/followups').json() if f['id']==item['id'])['script']=='客户约定周五联系'


def test_purchase_completed_cancels_future_marketing_reminders(clients):
    cid,staff,_=seed(clients)
    assert post(staff,'/followups/plan',{'conversation_id':cid}).status_code==200
    response=staff.patch('/api/conversations/'+cid,json={'stage':'已成交'},headers={'X-Store-Request':'1'})
    assert response.status_code==200
    assert all(f['status']=='cancelled' for f in staff.get('/api/followups').json())


def test_task_mutations_require_staff_and_timezone_aware_deadline(clients):
    cid,staff,state=pending_state(clients);task=state['tasks'][0]
    body={'revision':state['revision'],'status':'in_progress'}
    assert post(clients[2],f'/conversations/{cid}/service-tasks/{task["id"]}',body).status_code==403
    assert post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',{**body,'due_at':'2099-01-01T12:00:00'}).status_code==400
    assert dialogue.view(cid)['tasks'][0]['status']=='waiting_staff'


def test_followup_migration_is_additive_and_idempotent(tmp_path,monkeypatch):
    from backend import db
    from sqlalchemy import create_engine
    engine=create_engine('sqlite:///'+(tmp_path/'legacy.db').as_posix())
    with engine.begin() as connection:
        connection.exec_driver_sql('CREATE TABLE followups (id TEXT PRIMARY KEY, conversation_id TEXT, owner_id TEXT, due_at TEXT, purpose TEXT, script TEXT, status TEXT, feedback TEXT, created_at TEXT)')
        connection.exec_driver_sql("INSERT INTO followups VALUES ('old','c','s','2026-12-01T00:00:00+00:00','原安排','人工改过的内容','pending','','2026-10-01')")
    monkeypatch.setattr(db,'engine',engine)
    db.init_db();db.init_db()
    with engine.connect() as connection:
        row=connection.exec_driver_sql('SELECT due_at,script,generated,offset_days FROM followups').one()
    assert tuple(row)==('2026-12-01T00:00:00+00:00','人工改过的内容',0,0)
    engine.dispose()
