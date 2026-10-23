"""Adapt legacy deterministic domain fixtures to independently owned v4 model roles."""
import asyncio
from backend.dialogue_contract import NEED_NAMES

def reply_protocol_model(model):
    """Deterministic choice wording for tests of the upstream decision workflow."""
    async def wrapped(*args,**kwargs):
        name=getattr(kwargs.get('schema'),'__name__','');data=args[1]
        if name=='ReplyChoices':
            question=data.get('required_question')
            if question:question={**question,'scope':question.get('scope','field'),'topic_key':question.get('topic_key') or question['target']}
            answer=data['draft_outline'] or '已核对当前资料。'
            if question:answer=answer.replace(question['text'],'').strip() or '好的。'
            return {'candidates':[{'label':label,'answer':prefix+answer,'question':question} for label,prefix in [('简明',''),('说明','这边确认的信息是：'),('回应','您好，')]]},{}
        if name=='ChoicesReview':return {'verdicts':[{'index':i,'grounding':'测试给定的事实','errors':[]} for i in range(3)]},{}
        result,usage=await model(*args,**kwargs)
        if name=='Planning':result.setdefault('continuation',{'mode':'close' if result.get('customer_act') in {'pause_consultation','decline_purchase'} else 'answer','reason':'测试给定的接续策略','next_information':'','pending_topic':''})
        if name=='NeedExtraction':
            for change in result.get('changes',[]):change.setdefault('operation','replace')
        return result,usage
    return wrapped

def protocol_model(model):
    plans={};events={}
    async def wrapped(*args,**kwargs):
        name=getattr(kwargs.get('schema'),'__name__','')
        data=args[1];key=(data.get('current_turn') or {}).get('id','')
        if name=='Review':return {'valid_need_fields':[k for k,v in data['plan']['facts'].items() if v],'invalid_need_fields':[],'invalid_controls':[],'response_errors':[],'block_checks':[{'index':i,'supported':True,'reason':'测试给定内容'} for i,_ in enumerate(data.get('reply_blocks',[]))]},{}
        if name=='NeedExtraction':
            await events.setdefault(key,asyncio.Event()).wait()
            original=plans[key]
            return {'changes':[{'field':NEED_NAMES.get(k,k),'operation':'replace','fact':v} for k,v in original.get('facts',{}).items() if v],
                    **{k:original[k] for k in ('purchase_intent','clear_fields','constraints') if k in original}},{}
        result,usage=await model(*args,**kwargs)
        if name=='Composition':
            result={'blocks':[{'kind':'acknowledgement','text':result['reply'],'citations':[]}] if result.get('reply') else [],
                    'option_ids':result.get('option_ids',[]),'configuration_proposals':result.get('configuration_proposals',[])}
        if name in {'Planning','Decision'}:
            result=dict(result)
            if name=='Planning':
                plans[key]=dict(result);events.setdefault(key,asyncio.Event()).set()
                result={k:v for k,v in result.items() if k not in {'facts','purchase_intent','clear_fields','constraints'}}
            selection=result.get('selection');delegation=result.get('delegation')
            result.setdefault('customer_act','confirm_option' if selection else 'request_recommendation' if delegation else 'other')
            result.setdefault('customer_evidence',selection.get('evidence') if selection else delegation)
            if result.get('action')=='ask':
                result.setdefault('question',{'target':result.get('target','unspecified'),'text':result.get('reply','请说明需要什么'),
                    'missing_information':result.get('target','unspecified'),'why_needed':'测试中明确缺少影响选型的条件'})
                result['reply']=''
        return result,usage
    return reply_protocol_model(wrapped)


async def legacy_analysis(cid):
    """Keep v4 role-contract fixtures explicit; production uses service_workflow.

    These exercise the retained domain/compiler compatibility path. Production
    call budgets, task lifecycle and integrated turns live in test_service_workflow.
    """
    from backend import ai, dialogue
    return await dialogue.run(cid,ai.model_json,with_choices=True)
