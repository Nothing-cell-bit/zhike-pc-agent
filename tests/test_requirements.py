import asyncio
import json
import pytest
from backend import ai
from backend.db import Session,Conversation,Message
from backend.requirements import build_requirements,REQUIREMENT_FIELDS,SCHEMA_VERSION
from .conftest import post
from .test_workflow import guest

def msg(identifier,text,role='customer',seq=1):return {'id':identifier,'text':text,'role':role,'seq':seq}
def fact(identifier,quote,value=''):return {'status':'known','value':value,'evidence':[identifier],'quotes':[{'message_id':identifier,'quote':quote}]}

def test_separates_screenshot_dialogue_without_guessing_usage():
    messages=[msg('a','这个Mate怎么卖啊，我是大二学生，想换一个新电脑'),msg('s','你的预算多少？','staff',2),msg('b','1w以内',seq=3)]
    legacy={'user':{'value':'大二学生，想换一台新电脑','evidence':['a']},'tasks':{'value':'待确认'},'progress':{'value':'已明确预算范围，正在咨询Mate系列价格'},'budget':{'value':'1万元以内','evidence':['b']}}
    result=build_requirements({'schema_version':3,'user':fact('a','大二学生'),'progress':fact('a','想换一个新电脑'),'budget':fact('b','1w以内')},messages)
    assert result['user']['value']=='大二学生'
    assert '换' in result['progress']['value'] and '学生' not in result['progress']['value']
    assert result['budget']['value']=='1万元以内'
    for key in ['tasks','software','concerns','next_step']:assert result[key]['value']=='尚未了解'
    assert result['next_question']['field']=='tasks'
    assert '软件' in result['next_question']['text']

def test_valid_message_id_does_not_allow_fabricated_facts():
    messages=[msg('a','我是大二学生'),msg('b','会使用CAD吗？','staff',2)]
    raw={'schema_version':3,'user':fact('a','大二学生','大学生，准备换电脑'),'tasks':fact('a','学习办公'),'software':fact('b','CAD'),'next_step':fact('a','周末到店')}
    result=build_requirements(raw,messages)
    assert result['user']['value']=='大二学生'
    assert all(result[k]['value']=='尚未了解' for k in ['tasks','software','next_step'])

def test_does_not_remove_negation_or_uncertainty_from_customer_quotes():
    messages=[msg('a','不玩游戏，主要写代码；可能周末去店里看看')]
    raw={'schema_version':3,'tasks':fact('a','玩游戏'),'next_step':fact('a','周末去店里看看')}
    result=build_requirements(raw,messages)
    assert result['tasks']['value']=='尚未了解'
    assert result['next_step']['value']=='尚未了解'

def test_explicit_use_and_software_are_kept_separate():
    messages=[msg('a','主要剪辑视频，需要用Premiere，预算8000元，担心散热不好')]
    raw={'schema_version':3,'tasks':fact('a','主要剪辑视频'),'software':fact('a','Premiere'),'budget':fact('a','预算8000元'),'concerns':fact('a','担心散热不好')}
    result=build_requirements(raw,messages)
    assert result['tasks']['value']=='主要剪辑视频'
    assert result['software']['value']=='Premiere'
    assert '8000' in result['budget']['value']
    assert result['next_question']['field'] not in {'tasks','budget','software'}

def test_waits_for_customer_response_and_respects_stop_stage():
    messages=[msg('a','预算一万元'),msg('s','主要用电脑做什么？','staff',2)]
    assert build_requirements({},messages)['next_question']['state']=='waiting'
    assert build_requirements({},messages,stage='暂不购买')['next_question']['state']=='paused'

def test_manual_fields_win_and_next_question_changes_immediately():
    messages=[msg('a','我是学生，预算1万以内')]
    locks={'tasks':{'value':'剪辑视频','evidence':[],'manual':True}}
    result=build_requirements({'schema_version':3,'budget':fact('a','预算1万以内')},messages,locks)
    assert result['tasks']['value']=='剪辑视频' and result['tasks']['manual']
    assert result['next_question']['field']=='software'
    assert len(result['questions'])==1

def test_customer_correction_replaces_old_budget_in_legacy_view():
    result=build_requirements({'schema_version':3,'budget':{'status':'known','quotes':[{'message_id':'a','quote':'预算5000元'},{'message_id':'b','quote':'预算改到8000元'}]}},[msg('a','预算5000元'),msg('b','预算改到8000元',seq=2)])
    assert '8000' in result['budget']['value'] and '5000' not in result['budget']['value']

def test_api_exposes_reviewed_analysis_and_updates_manual_question(clients,monkeypatch):
    admin,staff,customer,_=clients;cid=guest(customer)
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=2;c.analysis_seq=2;c.analysis=json.dumps({'schema_version':SCHEMA_VERSION,'user':fact('m1','大二学生'),'budget':fact('m2','预算1w以内')})
        s.add_all([Message(id='m1',conversation_id=cid,sender_id=c.customer_id,role='customer',content='我是大二学生，想换一个新电脑',client_id='requirement-message-1',seq=1),Message(id='m2',conversation_id=cid,sender_id=c.customer_id,role='customer',content='预算1w以内',client_id='requirement-message-2',seq=2)]);s.commit()
    result=staff.get('/api/conversations/'+cid).json()
    assert result['analysis']['user']['value']=='大二学生'
    assert result['analysis']['next_question']['field']=='tasks'
    post(staff,f'/conversations/{cid}/claim')
    response=staff.patch(f'/api/conversations/{cid}/analysis',json={'field':'tasks','value':'剪辑视频','locked':True},headers={'X-Store-Request':'1'})
    assert response.status_code==200
    assert staff.get('/api/conversations/'+cid).json()['analysis']['next_question']['field']=='software'
    response=staff.patch(f'/api/conversations/{cid}/analysis',json={'field':'software','value':'Premiere','locked':True},headers={'X-Store-Request':'1'})
    assert response.status_code==200
    assert 'analysis' not in customer.get('/api/conversations/'+cid).json()

def test_incomplete_requirements_suggest_one_question_without_product_guesses(clients,monkeypatch):
    admin,staff,customer,_=clients;cid=guest(customer)
    async def no_model(*args,**kwargs):raise AssertionError('A missing-information question does not need product inference')
    monkeypatch.setattr(ai,'model_json',no_model)
    result=asyncio.run(ai.suggestions(cid,{}))
    assert result['recommendations']==[]
    assert result['reply']==result['questions'][0]

def test_analysis_sends_field_boundaries_and_verbatim_quote_contract(clients,monkeypatch):
    admin,staff,customer,_=clients;cid=guest(customer)
    with Session() as s:
        c=s.get(Conversation,cid);c.seq=1
        s.add(Message(id='m',conversation_id=cid,sender_id=c.customer_id,role='customer',content='我是大二学生，预算1w以内',client_id='model-requirement-message',seq=1));s.commit()
    seen=[]
    async def model(instruction,data,*args,**kwargs):
        seen.append((instruction,data))
        return {'user':fact('m','大二学生'),'budget':fact('m','预算1w以内')},{}
    monkeypatch.setattr(ai,'model_json',model)
    result=asyncio.run(ai.analysis(cid))['analysis']
    assert result['tasks']['value']=='尚未了解'
    assert result['user']['value']=='大二学生'
    assert result['next_question']['field']=='tasks'
    assert 'quotes' in seen[0][0] and '客服' in seen[0][0]

def test_short_numeric_budget_requires_budget_question_context():
    messages=[msg('s','你这次准备多少预算？','staff'),msg('a','6000',seq=2)]
    result=build_requirements({'schema_version':3,'budget':fact('a','6000')},messages)
    assert result['budget']['value']=='6000元'
    assert build_requirements({},[msg('a','6000')])['budget']['value']=='尚未了解'

def test_software_and_usage_are_not_extracted_from_a_customer_question():
    result=build_requirements({},[msg('a','这个支持CAD吗？能玩游戏吗？')])
    assert result['software']['value']=='尚未了解'
    assert result['tasks']['value']=='尚未了解'

def test_negative_only_usage_still_asks_for_actual_use():
    result=build_requirements({'schema_version':3,'tasks':{**fact('a','不玩游戏'),'status':'partial'},'budget':fact('a','预算6000元')},[msg('a','不玩游戏，预算6000元')])
    assert result['tasks']['value']=='不玩游戏'
    assert result['next_question']['field']=='tasks'

def test_budget_quote_cannot_drop_upper_limit():
    messages=[msg('a','预算6000元以内')]
    result=build_requirements({'schema_version':3,'budget':fact('a','6000元')},messages)
    assert result['budget']['value']=='尚未了解'

def test_explicit_refusal_does_not_recommend_more_sales_questions():
    assert build_requirements({'schema_version':3,'followup_allowed':False},[msg('a','我暂时不买了')])['next_question']['state']=='paused'

def test_short_game_type_answer_uses_question_context_without_guessing_title():
    messages=[msg('a','游戏'),msg('s','具体想玩什么类型的游戏？','staff',2),msg('b','3A',seq=3),msg('c','预算1w以内',seq=4)]
    result=build_requirements({'schema_version':3,'tasks':{'status':'known','quotes':[{'message_id':'a','quote':'游戏'},{'message_id':'b','quote':'3A'}]},'budget':fact('c','预算1w以内')},messages)
    assert '3A' in result['tasks']['value'] and '游戏' in result['tasks']['value']
    assert result['software']['value']=='尚未了解'
    assert result['next_question']['field']=='software'

def test_refresh_retains_game_type_and_customer_game_nickname():
    messages=[msg('u','我是大二学生'),msg('budget','预算1w以内',seq=2),msg('use','游戏',seq=3),msg('s1','具体想玩什么类型的游戏？','staff',4),msg('type','3A',seq=5),msg('s2','具体想玩哪几款3A游戏？还有其他必须运行的软件吗？','staff',6),msg('name','黑猴',seq=7)]
    # Reviewed evidence is preserved identically when projected again for display.
    raw={'schema_version':3,'user':fact('u','大二学生'),'budget':fact('budget','预算1w以内'),'tasks':{'status':'known','quotes':[{'message_id':'use','quote':'游戏'},{'message_id':'type','quote':'3A'}]},'software':fact('name','黑猴')}
    result=build_requirements(raw,messages)
    assert '3A' in result['tasks']['value'] and '游戏' in result['tasks']['value']
    assert result['software']['value']=='黑猴'
    assert result['software']['quotes']==[{'message_id':'name','quote':'黑猴'}]
    assert result['next_question']['field']!='software'
    assert build_requirements(result,messages)['software']['value']=='黑猴'

@pytest.mark.parametrize('name',['我的世界','星露谷物语','Zed','门店自用ERP'])
def test_unknown_app_names_are_not_rejected_by_a_fixed_dictionary(name):
    messages=[msg('s','需要用哪些软件或游戏？','staff'),msg('a',name,seq=2)]
    assert build_requirements({'schema_version':3,'software':fact('a',name)},messages)['software']['value']==name

@pytest.mark.parametrize('answer',['是的','不知道','3A','游戏','不用了','不玩黑猴','这个多少钱','黑猴能玩吗？'])
def test_generic_or_negative_replies_do_not_become_app_names(answer):
    messages=[msg('s','具体玩哪些游戏？','staff'),msg('a',answer,seq=2)]
    assert build_requirements({'schema_version':3},messages)['software']['value']=='尚未了解'

def test_unrelated_question_does_not_classify_a_nickname_as_software():
    assert build_requirements({'schema_version':3},[msg('s','怎么称呼你？','staff'),msg('a','黑猴',seq=2)])['software']['value']=='尚未了解'
