import asyncio
import pytest
from backend import ai
from backend.requirements import build_requirements
from backend.db import Session,Conversation,Message
from .test_workflow import guest

def message(key,text,role='customer',seq=1):return {'id':key,'text':text,'role':role,'seq':seq}
def item(key,quote,status='known'):return {'status':status,'quotes':[{'message_id':key,'quote':quote}]}

@pytest.mark.parametrize('field,text',[
 ('user','档案修复员'),('user','实验室的轮值人员'),('tasks','记录仪器采样数据'),
 ('tasks','给社区活动整理照片'),('software','黑猴'),('software','星露谷物语'),
 ('software','Zed'),('software','单位自研的甲乙丙系统'),('software','App_9f7a_未收录'),
 ('concerns','不想每天带两个充电器'),('progress','等旧设备交接之后再决定'),
 ('next_step','周五把文件发给你'),
])
def test_reviewed_facts_do_not_require_any_domain_keyword(field,text):
    result=build_requirements({'schema_version':3,field:item('a',text)},[message('a',text)])
    assert result[field]['value']==text

def test_unfamiliar_name_cannot_come_from_staff_or_invented_quotes():
    result=build_requirements({'schema_version':3,'software':item('s','未收录应用'),'user':item('a','职业玩家')},[message('s','未收录应用','staff'),message('a','我想看看')])
    assert result['software']['value']==result['user']['value']=='尚未了解'

def test_quoted_negation_and_budget_limits_cannot_be_dropped():
    result=build_requirements({'schema_version':3,'tasks':item('a','玩游戏'),'budget':item('b','6000元')},[message('a','不玩游戏'),message('b','6000元以内')])
    assert result['tasks']['value']==result['budget']['value']=='尚未了解'

def test_partial_information_is_preserved_but_can_be_clarified():
    result=build_requirements({'schema_version':3,'next_step':item('a','可能周末来','partial'),'next_question':{'field':'next_step','purpose':'clarify','text':'等时间确定后再安排到店，可以吗？'}},[message('a','可能周末来')])
    assert result['next_step']['status']=='partial'
    assert '可能' in result['next_step']['value']

def test_next_question_does_not_recollect_an_already_known_answer():
    raw={'schema_version':3,'tasks':item('a','游戏'),'budget':item('b','1w以内'),'software':item('c','黑猴'),'next_question':{'field':'software','purpose':'collect','text':'玩哪些游戏？'}}
    result=build_requirements(raw,[message('a','游戏'),message('b','1w以内'),message('c','黑猴')])
    assert result['software']['value']=='黑猴'
    assert result['next_question']['field']!='software'

def test_review_repairs_missing_and_misclassified_draft_facts(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer)
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=3
        for seq,(key,text,role) in enumerate([('a','我是档案修复员','customer'),('s','具体需要运行哪些应用？','staff'),('b','单位自研的甲乙丙系统','customer')],1):
            s.add(Message(id=key,conversation_id=cid,sender_id=c.customer_id,role=role,content=text,client_id='generalization-message-'+key,seq=seq))
        s.commit()
    calls=[]
    async def model(instruction,data,*args,**kwargs):
        calls.append(data)
        if len(calls)==1:return {'tasks':item('a','档案修复员')},{}
        assert 'draft' in data
        return {'user':item('a','档案修复员'),'software':item('b','单位自研的甲乙丙系统')},{}
    monkeypatch.setattr(ai,'model_json',model)
    result=asyncio.run(ai.analysis(cid))['analysis']
    assert len(calls)==2
    assert result['user']['value']=='档案修复员'
    assert result['tasks']['value']=='尚未了解'
    assert result['software']['value']=='单位自研的甲乙丙系统'

def test_human_correction_survives_model_review():
    result=build_requirements({'schema_version':3,'budget':item('a','6000元以内')},[message('a','6000元以内')],{'budget':{'value':'已确认8000元以内','manual':True}})
    assert result['budget']['value']=='已确认8000元以内'

def test_contradictory_fact_status_is_rejected_before_display():
    from pydantic import ValidationError
    with pytest.raises(ValidationError):ai.Insight.model_validate(item('a','某个名称','unknown'))

def test_staff_question_during_analysis_does_not_discard_customer_facts(clients,monkeypatch):
    _,_,customer,_=clients;cid=guest(customer)
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=1
        s.add(Message(id='actual',conversation_id=cid,sender_id=c.customer_id,role='customer',content='单位自研应用',client_id='customer-during-review',seq=1));s.commit()
    calls=0
    async def model(*args,**kwargs):
        nonlocal calls
        calls+=1
        if calls==2:
            with Session() as s:
                c=s.get(Conversation,cid);c.seq=2
                s.add(Message(conversation_id=cid,sender_id='staff',role='staff',content='预算是多少？',client_id='staff-during-review',seq=2));s.commit()
        return {'software':item('actual','单位自研应用')},{}
    monkeypatch.setattr(ai,'model_json',model)
    result=asyncio.run(ai.analysis(cid))
    assert result.get('stale') is not True
    assert result['analysis']['software']['value']=='单位自研应用'
    assert result['analysis']['next_question']['state']=='waiting'
