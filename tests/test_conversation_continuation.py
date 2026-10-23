from .dialogue_fakes import legacy_analysis
import asyncio,copy,json
import pytest
from backend import dialogue
from backend import ai
from backend.db import Session,DialogueState
from backend.dialogue_replies import generate_choices,ReplyChoices
from .test_reply_choices import seed,output,fake


def turns():
    return [{'id':'focus','seq':1,'role':'customer','text':'先回答这个问题'},
            {'id':'answer','seq':2,'role':'staff','text':'这个规格还需要核实'},
            {'id':'receipt','seq':3,'role':'customer','text':'收到了'}]


def acknowledgement():
    return dialogue.Decision(customer_act='acknowledge',customer_evidence={'message_id':'receipt','quote':'收到了'},
        acknowledged_message_id='answer',action='inform',goal='none',reply='收到。',
        continuation={'mode':'bridge','reason':'本轮已确认收到，可了解尚未讨论的用途',
            'next_information':'使用电脑完成的实际任务','pending_topic':'规格仍需门店核实'}).model_dump()


@pytest.mark.parametrize('duration,expected',[('topic',None),('conversation','focused')])
def test_receipt_only_releases_local_focus(clients,duration,expected):
    _,_,state=seed(clients);state['needs']=dialogue.fact_view(dialogue.build_requirements({},turns()));before=copy.deepcopy(state['needs'])
    state['conversation_scope']={'mode':'focused','duration':duration,'evidence':{'message_id':'focus','quote':'先回答这个问题'}}
    saved,_=dialogue.apply_decision(state,acknowledgement(),turns(),{},'新咨询')
    assert (saved.get('conversation_scope') or {}).get('mode')==expected
    assert saved['continuation']['mode']==('bridge' if duration=='topic' else 'answer')
    assert saved['needs']==before and saved['needs']['next_step']['status']=='unknown'


def test_receipt_requires_actual_last_staff_answer(clients):
    _,_,state=seed(clients);state['conversation_scope']={'mode':'focused','duration':'topic'}
    plan=acknowledgement();plan['acknowledged_message_id']='unsent-draft'
    assert dialogue.current_turn_errors(plan,turns()[-1],turns())
    saved,_=dialogue.apply_decision(state,plan,turns(),{},'新咨询')
    assert saved['conversation_scope']['mode']=='focused'


def test_receipt_cannot_be_treated_as_withdrawal_of_global_boundary(clients):
    _,_,state=seed(clients);state['conversation_scope']={'mode':'focused','duration':'conversation'}
    plan=acknowledgement();plan['conversation_scope']={'mode':'open','duration':'topic','evidence':plan['customer_evidence']}
    saved,_=dialogue.apply_decision(state,plan,turns(),{},'新咨询')
    assert saved['conversation_scope']['mode']=='focused'
    assert saved['continuation']['mode']=='answer'


def test_receipt_cannot_close_session_and_bridge_is_optional():
    plan=acknowledgement();plan['continuation']['mode']='close'
    assert dialogue.current_turn_errors(plan,turns()[-1],turns())
    plan=acknowledgement();plan['action']='ask';plan['question']={'target':'tasks','text':'做什么？'}
    assert any('可选' in e for e in dialogue.current_turn_errors(plan,turns()[-1],turns()))
    plan=acknowledgement();plan['customer_act']='pause_consultation';plan['continuation']['mode']='close';plan['action']='pause'
    assert not dialogue.current_turn_errors(plan,turns()[-1],turns())


def test_inconsistent_receipt_is_safely_acknowledged_without_ending_or_forcing_a_question():
    plan=acknowledgement();plan['continuation']['mode']='close';plan['action']='pause'
    safe=dialogue.reconcile_receipt(plan,turns())
    assert safe['continuation']['mode']=='answer' and safe['action']=='inform'
    assert safe['question'] is None
    assert plan['action']=='pause'


def test_choices_must_offer_planned_bridge_and_keep_a_non_question_choice(clients):
    _,_,state=seed(clients);state['continuation']=acknowledgement()['continuation'];calls=[]
    async def model(*args,**kwargs):
        if kwargs['schema'] is ReplyChoices:
            result=output();calls.append(args[1]['phase'])
            if len(calls)==1:
                for c in result['candidates']:c['question']=None
            return result,{}
        return await fake(*args,**kwargs)
    candidates,_,trace=asyncio.run(generate_choices(model,state,[],state['reply_context']))
    assert len(trace)==2
    assert any(c['question'] for c in candidates) and any(not c['question'] for c in candidates)
    assert state['questions']==[]


def test_candidate_layer_cannot_independently_end_the_session(clients):
    _,_,state=seed(clients);state['continuation']=acknowledgement()['continuation']
    async def model(*args,**kwargs):
        if kwargs['schema'] is ReplyChoices:
            result=output();result['engagement']='close';return result,{}
        return await fake(*args,**kwargs)
    with pytest.raises(ValueError,match='engagement'):asyncio.run(generate_choices(model,state,[],state['reply_context']))


def test_legacy_cached_pause_is_reanalyzed_instead_of_reused(clients,monkeypatch):
    cid,_,state=seed(clients);state.pop('continuation');state['action']['kind']='pause'
    with Session() as s:s.get(DialogueState,cid).state=json.dumps(state);s.commit()
    async def model(*args,**kwargs):
        if kwargs['schema'].__name__=='Planning':raise ValueError('legacy pause reached planning')
        return {'changes':[]},{}
    monkeypatch.setattr(ai,'model_json',model)
    with pytest.raises(ValueError,match='reached planning'):asyncio.run(legacy_analysis(cid))
