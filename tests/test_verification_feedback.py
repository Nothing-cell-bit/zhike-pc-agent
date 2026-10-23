from backend import dialogue
from backend.db import PriceRule,Session
from sqlalchemy import select,func
from backend.service_workflow import finish_candidates
from backend.service_tasks import observe_delivery
from .test_reception_plan import pending_state
from .conftest import post


def test_verified_answer_tracks_only_actual_matching_delivery():
    task={'id':'v1','key':'verify:fit','kind':'verify','status':'completed','result':'指定环境运行通过'}
    state={'tasks':[task]}
    candidate=finish_candidates([{'answer':'指定环境运行通过，其他负载仍需确认。','question':None,'citations':[{'source_id':'task:v1','excerpt':task['result']}]}],'')[0]
    assert candidate['verification_ids']==['v1']
    observe_delivery(state,candidate,'好的，稍后告知。','m1',4)
    assert task.get('feedback_status')!='sent'
    observe_delivery(state,candidate,candidate['reply'],'m2',5)
    assert task['feedback_status']=='sent' and task['feedback_message_id']=='m2'


def test_structured_result_is_pending_feedback_and_not_a_price_rule(clients,monkeypatch):
    monkeypatch.setattr('backend.main.spawn_job',lambda *args:'verification-job')
    cid,staff,state=pending_state(clients);task=state['tasks'][0]
    record={'kind':'compatibility','conclusion':'conditional','summary':'Blender 4.2 指定演示场景可运行',
            'conditions':'Windows 11，中等建模场景；不包含高负载渲染', 'source':'门店样机测试记录 TEST-001'}
    r=post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',{'revision':state['revision'],'status':'completed','verification':record})
    assert r.status_code==200 and r.json()['job_id']=='verification-job'
    saved=dialogue.view(cid)['tasks'][0]
    assert saved['verification']==record
    assert saved['feedback_status']=='pending' and saved['status']=='completed'
    assert record['source'] in saved['result'] and record['conditions'] in saved['result']
    reminders=staff.get('/api/notifications').json()
    assert any(x.get('task_id')==task['id'] and x['status']=='awaiting_feedback' for x in reminders)


def test_unconfirmed_result_must_remain_open_with_next_deadline(clients,monkeypatch):
    monkeypatch.setattr('backend.main.spawn_job',lambda *args:'unexpected-job')
    cid,staff,state=pending_state(clients);task=state['tasks'][0]
    record={'kind':'compatibility','conclusion':'unconfirmed','summary':'门店样机缺少该插件，需补测', 'conditions':'', 'source':'门店同事反馈'}
    path=f'/conversations/{cid}/service-tasks/{task["id"]}'
    assert post(staff,path,{'revision':state['revision'],'status':'completed','verification':record}).status_code==400
    assert post(staff,path,{'revision':state['revision'],'status':'waiting_staff','verification':record}).status_code==400
    r=post(staff,path,{'revision':state['revision'],'status':'waiting_staff','verification':record,'due_at':'2099-01-01T12:00:00+08:00'})
    assert r.status_code==200 and r.json()['job_id'] is None
    saved=dialogue.view(cid)['tasks'][0]
    assert saved['status']=='waiting_staff' and not saved['result']
    assert saved['last_attempt']['summary']==record['summary']


def test_structured_result_requires_source_and_limitations_for_conditional(clients):
    cid,staff,state=pending_state(clients);task=state['tasks'][0]
    r=post(staff,f'/conversations/{cid}/service-tasks/{task["id"]}',{'revision':state['revision'],'status':'completed',
        'verification':{'kind':'compatibility','conclusion':'conditional','summary':'可以用','conditions':'','source':''}})
    assert r.status_code in {400,422}


def test_price_verification_needs_configuration_and_expiry_without_creating_quote_rules(clients,monkeypatch):
    monkeypatch.setattr('backend.main.spawn_job',lambda *args:'price-feedback-job')
    cid,staff,state=pending_state(clients);task=state['tasks'][0]
    path=f'/conversations/{cid}/service-tasks/{task["id"]}'
    record={'kind':'price','conclusion':'confirmed','summary':'演示门店核价记录','conditions':'仅限该演示配置','source':'DEMO-PRICE-001'}
    body={'revision':state['revision'],'status':'completed','verification':record}
    assert post(staff,path,body).status_code==400
    record.update(configuration='演示型号 / 16GB / 1TB',price_text='5999元（演示）',valid_until='2099-01-01T12:00:00+08:00')
    assert post(staff,path,body).status_code==200
    with Session() as s:assert s.scalar(select(func.count()).select_from(PriceRule))==0
    assert '非正式报价' in dialogue.view(cid)['tasks'][0]['result']
