from .dialogue_fakes import legacy_analysis
import asyncio,copy,json
import pytest
from backend import ai,dialogue
from backend.db import Session,Conversation,DialogueState
from backend.dialogue_replies import choice_errors,generate_choices,ReplyChoices,numeric_evidence_errors
from .conftest import post
from .test_workflow import guest
from .test_dialogue_workflow import add


def q(target='usage_tasks',text='平时主要用来做什么？'):
    return {'target':target,'scope':'field','topic_key':target,'text':text,'missing_information':'实际用途','why_needed':'帮助判断是否适合'}


def seed(clients):
    _,staff,customer,_=clients;cid=guest(customer);post(staff,f'/conversations/{cid}/claim');add(cid,'customer','设备甲内存多大？')
    with Session() as s:
        conv=s.get(Conversation,cid);state=dialogue.initial_state(conv,dialogue.messages_for(s,cid))
        state.update(revision=1,message_seq=conv.seq,goal='information',topic={'subject':'设备甲内存'})
        state['action']={'id':'old','kind':'inform','reply':'内存32GB','intro':'内存32GB','question':None,'option_ids':[],'message_seq':conv.seq,'revision':1,'status':'proposed'}
        state['continuation']={'mode':'answer','reason':'本轮参数咨询','next_information':'','pending_topic':''}
        state['reply_context']={'answer':'内存32GB','sources':[{'id':'s','excerpt':'内存32GB'}],'suffix':''}
        state['needs']['budget']={'value':'7000以内','status':'known','manual':True}
        conv.analysis=json.dumps({'unchanged':'profile'});conv.analysis_seq=conv.seq
        s.add(DialogueState(conversation_id=cid,revision=1,message_seq=conv.seq,state=json.dumps(state)));s.commit()
    return cid,staff,state


def output():
    return {'candidates':[{'label':'简明答复','answer':'这款是32GB内存。','question':None},
        {'label':'聊聊用途','answer':'它配的是32GB内存。','question':q()},
        {'label':'确认规格','answer':'您看的这款，内存容量为32GB。','question':None}]}


async def fake(*args,**kwargs):
    if kwargs['schema'] is ReplyChoices:return output(),{}
    return {'verdicts':[{'index':i,'grounding':'测试给定事实','errors':[]} for i in range(3)]},{}


def test_regenerate_only_changes_choices_and_tracks_only_sent_question(clients,monkeypatch):
    cid,staff,before=seed(clients);calls=[]
    async def model(*args,**kwargs):calls.append(args[1]['phase']);return await fake(*args,**kwargs)
    monkeypatch.setattr(ai,'model_json',model)
    result=asyncio.run(ai.suggestions(cid,{}));state=result['dialogue'];choices=state['action']['candidates']
    assert calls==['reply_choices','review_choices'] and len(choices)==3
    for field in ('needs','topic','selection','quotes','questions','message_seq'):assert state[field]==before[field]
    with Session() as s:assert json.loads(s.get(Conversation,cid).analysis)=={'unchanged':'profile'}
    assert state['questions']==[]
    r=post(staff,f'/conversations/{cid}/messages',{'content':choices[1]['reply'],'action_id':choices[1]['id'],'client_id':'choice-send'})
    assert r.status_code==200
    saved=dialogue.view(cid)
    assert len(saved['questions'])==1 and saved['questions'][0]['target']=='usage_tasks'
    assert saved['needs']==before['needs']
    assert saved['action']['kind']=='wait'


def test_edited_out_question_is_not_registered(clients,monkeypatch):
    cid,staff,_=seed(clients);monkeypatch.setattr(ai,'model_json',fake)
    choices=asyncio.run(ai.suggestions(cid,{}))['dialogue']['action']['candidates']
    assert post(staff,f'/conversations/{cid}/messages',{'content':choices[1]['answer'],'action_id':choices[1]['id'],'client_id':'edited-choice'}).status_code==200
    assert dialogue.view(cid)['questions']==[]


@pytest.mark.parametrize('status',['answered','declined','delegated','asked'])
def test_question_guard_covers_history_and_known_fields(status):
    state={'needs':{'tasks':{'status':'unknown'},'budget':{'value':'7000以内','status':'known'}},'questions':[{'target':'usage_tasks','status':status}],'quotes':[]}
    assert choice_errors(output()['candidates'],state,[],None,[])
    candidates=output()['candidates'];candidates[1]['question']=q('purchase_budget','预算多少？')
    assert any('明确' in e for e in choice_errors(candidates,state,[],None,[]))


def test_semantic_rejection_is_bounded_and_preserves_previous_result(clients,monkeypatch):
    cid,_,before=seed(clients);calls=[]
    async def reject(*args,**kwargs):
        calls.append(args[1]['phase'])
        if kwargs['schema'] is ReplyChoices:return output(),{}
        return {'verdicts':[{'index':i,'grounding':'测试给定事实','errors':['客户已经拒绝讨论用途'] if i==1 else []} for i in range(3)]},{}
    monkeypatch.setattr(ai,'model_json',reject)
    with pytest.raises(ValueError,match='核验'):asyncio.run(ai.suggestions(cid,{}))
    assert calls==['reply_choices','review_choices']*3
    assert dialogue.view(cid)==before


def test_stale_generation_cannot_override_new_customer_message(clients,monkeypatch):
    cid,_,before=seed(clients)
    async def concurrent(*args,**kwargs):
        if args[1]['phase']=='review_choices':add(cid,'customer','先别聊内存，屏幕多大？')
        return await fake(*args,**kwargs)
    monkeypatch.setattr(ai,'model_json',concurrent)
    assert asyncio.run(ai.suggestions(cid,{}))['stale']
    assert dialogue.view(cid)==before


def test_old_choices_expire_after_regeneration_and_unknown_state_requires_analysis(clients,monkeypatch):
    cid,staff,_=seed(clients);monkeypatch.setattr(ai,'model_json',fake)
    first=asyncio.run(ai.suggestions(cid,{}))['dialogue']['action']['candidates']
    async def different(*args,**kwargs):
        result,usage=await fake(*args,**kwargs)
        if kwargs['schema'] is ReplyChoices:
            for c in result['candidates']:c['answer']='您问的这台电脑，'+c['answer']
        return result,usage
    monkeypatch.setattr(ai,'model_json',different)
    asyncio.run(ai.suggestions(cid,{}))
    with Session() as s:
        with pytest.raises(ValueError,match='失效'):dialogue.check_send_action(s,s.get(Conversation,cid),first[0]['id'],first[0]['reply'])
    add(cid,'customer','再看看屏幕')
    with pytest.raises(ValueError,match='更新分析'):asyncio.run(ai.suggestions(cid,{}))


def test_draft_choices_are_not_in_planner_memory(clients):
    _,_,state=seed(clients);state['reply_history']=[{'reply':'您是不是学生？'}]
    observed=dialogue.model_state(state)
    assert 'reply_history' not in observed and 'reply_context' not in observed and 'action' not in observed


def test_wording_cannot_invent_contact_numbers():
    candidates=[{'answer':'可以联系123456789确认','question':None}]
    assert numeric_evidence_errors(candidates,{'sources':[{'excerpt':'内存32GB'}]},[],{'needs':{}})
    candidates[0]['answer']='内存是32GB。'
    assert not numeric_evidence_errors(candidates,{'sources':[{'excerpt':'内存32GB'}]},[],{'needs':{}})


def test_known_field_can_have_unknown_detail_but_same_detail_cannot_be_reasked():
    state={'needs':{'tasks':{'status':'known','value':'办公'}},'questions':[],'quotes':[]}
    question={**q(),'scope':'detail','topic_key':'multitasking','text':'会同时运行很多程序吗？'}
    decision={'action':'inform','reply':question['text'],'question':question}
    assert not dialogue.checked_action(decision,state,{},[])['blockers']
    state['questions']=[{**question,'status':'answered'}]
    assert dialogue.checked_action(decision,state,{},[])['blockers']


def test_software_evidence_cannot_replace_usage():
    quote={'message_id':'m','quote':'使用团队工具甲','kind':'fact'}
    facts={'tasks':{'quotes':[quote]},'software':{'quotes':[quote]}}
    admitted=dialogue.independent_identity(facts)
    assert 'tasks' not in admitted and 'software' in admitted


def test_customer_focus_boundary_persists_across_new_parameter_questions(clients):
    _,_,state=seed(clients)
    messages=[{'id':'focus','role':'customer','text':'只问参数','seq':1}]
    decision=dialogue.Decision(action='inform',customer_act='request_information',customer_evidence=None,
        conversation_scope={'mode':'focused','evidence':{'message_id':'focus','quote':'只问参数'}}).model_dump()
    state,_=dialogue.apply_decision(state,decision,messages,{},'新咨询')
    messages.append({'id':'next','role':'customer','text':'屏幕多大','seq':2})
    decision['conversation_scope']=None
    updated,_=dialogue.apply_decision(state,decision,messages,{},'新咨询')
    assert updated['conversation_scope']['mode']=='focused'
    assert updated['needs']==state['needs']


def test_focused_conversation_drops_optional_probing_not_the_answer(clients):
    _,_,state=seed(clients);state['conversation_scope']={'mode':'focused'}
    candidates,_,trace=asyncio.run(generate_choices(fake,state,[],state['reply_context']))
    assert len(candidates)==3 and all(not c['question'] for c in candidates)
    assert trace[0]['controls']


def test_confirm_operation_preserves_existing_usage(clients,monkeypatch):
    from backend.db import Message
    from .dialogue_fakes import reply_protocol_model
    cid,_,state=seed(clients)
    with Session() as s:
        conv=s.get(Conversation,cid)
        messages=dialogue.messages_for(s,cid);mid=messages[0]['id']
        s.get(Message,mid).content='主要办公'
        state['needs']['tasks']={'value':'主要办公','status':'known','confirmed_none':False,'quotes':[{'message_id':mid,'quote':'主要办公','kind':'fact'}],'evidence':[]}
        s.get(DialogueState,cid).state=json.dumps(state);s.commit()
    add(cid,'customer','其他的就不补充了')
    async def model(instruction,data,*args,**kwargs):
        name=kwargs['schema'].__name__
        if name=='NeedExtraction':return {'changes':[{'field':'usage_tasks','operation':'confirm','fact':{'quotes':[]}}]},{}
        if name=='Planning':return {'goal':'none','action':'pause','reply':'好的。','customer_act':'pause_consultation','customer_evidence':{'message_id':data['current_turn']['id'],'quote':'其他的就不补充了'}},{}
        if name=='Review':return {'valid_need_fields':[],'invalid_need_fields':[],'invalid_controls':[],'response_errors':[],'block_checks':[{'index':i,'supported':True,'reason':'确认回应'} for i,_ in enumerate(data['reply_blocks'])]},{}
        raise AssertionError(name)
    monkeypatch.setattr(ai,'model_json',reply_protocol_model(model))
    saved=asyncio.run(legacy_analysis(cid))['dialogue']
    assert saved['needs']['tasks']['value']=='主要办公'
