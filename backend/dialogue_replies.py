"""Contextual reply choices. This layer has no authority to change customer facts."""
import copy
import json
import re
import uuid
from typing import Literal
from pydantic import BaseModel,ConfigDict,Field
from sqlalchemy import update,exists
from .db import Session,Conversation,DialogueState,DialogueRun,now
from .dialogue_contract import Question,NEED_KEYS
from .llm_trace import sink


class ReplyQuestion(Question):
    scope:Literal['field','detail']
    topic_key:str=Field(min_length=1,max_length=80)


class ReplyChoice(BaseModel):
    model_config=ConfigDict(extra='forbid')
    label:str=Field(min_length=1,max_length=18)
    answer:str=Field(min_length=1,max_length=300,pattern=r'^[^?？]+$',description='只写回答正文，不能包含问句。向客户提出的问题只能放在question.text。')
    question:ReplyQuestion|None=None


class ReplyChoices(BaseModel):
    model_config=ConfigDict(extra='forbid')
    candidates:list[ReplyChoice]=Field(min_length=3,max_length=3)


class ChoiceVerdict(BaseModel):
    index:int=Field(ge=0,le=2)
    grounding:str=Field(min_length=1,max_length=350)
    errors:list[str]=Field(max_length=6)
    question_errors:list[str]=Field(default_factory=list,max_length=4)


class ChoicesReview(BaseModel):
    model_config=ConfigDict(extra='forbid')
    verdicts:list[ChoiceVerdict]=Field(min_length=3,max_length=3)


PROPOSE='''你为当前门店客服拟三个回复候选，客服只选一条发送。以客服第一人称直接对客户说话，口吻自然、简洁，不写审核报告，也不让客户再去找门店或另一个客服完成本店的工作。
unresolved_facts是本轮已经核实仍缺证据的事项，改写时必须保留未知，不能改成支持、不支持、存在或不存在。资料缺口不能靠追问客户的其他需求解决。可简短说还需核实，不必照抄长解释。
continuation是唯一规划层已作出的接话决策，候选层没有结束或改变策略的字段。mode=answer时回应当前问题；mode=bridge时至少一条候选自然承接并询问next_information所指的未知信息，其他候选可直接回应；mode=close才收尾。没有continuation的旧记录不能把确认收到当成明确结束。三个候选的表达角度可以不同，不套固定三种套路。
客户确认收到上一条说明后，可以顺势了解下一项有价值的信息，不必反复重述待核实事项。pending_topic只表示事项仍未核实，不等于已有回访约定或自动跟踪任务；没有已确认的跟进约定时，不擅自承诺之后联系、持续监控或第一时间通知。conversation_scope为当前有效边界，topic级限制在客户确认该话题答复后已释放，不能按旧纠正语句再次锁死话题。
围绕客户最新一句话回应，通常一两句话即可。客户补充信息后自然接住新信息，不重新做产品介绍，不复述整段参数。先回答再提问；没有必要就不问。产品事实以sources为准，draft_outline只是任务提示，不是事实依据。参数不能证明具体软件一定兼容、运行流畅、续航有保障或主观舒适；选型建议要保留适用条件，未知简短说明需核实，不虚构已经核实或亲身体验。
输出answer仅含陈述句，所有追问放question。question最多问一个具体点，text是实际问句，missing_information和why_needed说明真正未知之处与本轮价值。完整问一个需求字段时scope=field，target/topic_key取对应语义字段名；深入已知需求的未知细节时scope=detail，topic_key是该细节稳定英文标识。不得把已知信息换个标识再问。未采用的previous_candidates不是已问历史。
required_question非空时必须澄清其缺口；否则至少一条不追问。explore时应有一个有用的主动问题供客服选用。已答、拒答、委托和尚未得到回答的问题不重复。候选不能修改需求、选型或报价；报价金额和正式方案由程序附加，不在answer重写。operation=regenerate时给不同于previous_candidates的新表达，事实不变。只输出schema规定的JSON。'''


ASSESS='''只读审核三个客服草稿。对index 0、1、2各给一条grounding和errors。grounding简述与原始messages和sources的核对；合格errors为空。不要重写话术，也不要修改客户需求。
回答正文的问题放errors；question里的重复、不当、已答/拒答或时机错误放question_errors，不能因为可选追问有问题就否定正确的回答正文。
优先检查unresolved_facts：这些是已核验但尚缺证据的事项，候选必须保留未知，不能升级成肯定或否定；这是事实状态，不是以前的审核意见。
先核对每条是否回应客户最新问题；不能仅复述上一轮已知规格来代替本轮结论。资料不足以回答时应明确保留未知，而不是回避问题或猜答案。
只拦截明确问题：具体产品事实无依据或与资料矛盾（可选配置不能写成客户已选配置，特定版本不能写成全系均有）；无依据金额、优惠、库存、已执行操作或预算内承诺；无条件的性能/续航/兼容/健康保证；重复已答、已拒绝、已委托或仍待回答的问题；客户限定话题却转移；answer藏有未登记的追问；把本店需核实的工作推回客户。
原文只列出一种配置不证明不存在其他配置；未说明支持某功能不等于不支持。不能把资料缺失改写成“没有更大版本”“不支持升级”等确定的否定结论。
务必区分事实保证与合理建议：可以基于明确系统、配置与已知常见用途给出有条件的一般选型建议，不要求每个普通用途均有独立实测；不能保证所有软件版本或具体负载表现。可以表达“需要核实价格是否符合客户预算”，这是保留未知，不是价格承诺；客户原话中的预算不是销售报价。不要因为没有价格资料而拒绝“尚需核价”的表述。
question根据原始对话按语义核对。已知宽泛用途不代表具体软件、外设、负载等细节都已了解。尚未问过且有实际价值的细节可主动了解；不是所有追问都必须阻塞流程。没有发送的候选不属于历史问题。
continuation已由规划层判断整场会话是否继续；bridge允许自然转题，不得把已被确认的局部话题限制当成永久禁问。pending_topic不等于已约定回访，客户确认收到不等于明确结束；没有真实已约定的跟进，不应承诺后续自动联系或持续监控。
不因风格偏好、句子长短或是否列足所有参数判错。错误必须指出当前候选中的具体问题，不能依据之前审核意见或其他候选推测。只输出JSON。'''


def normalized(text):
    return re.sub(r'[\W_]+','',text).lower()


def numeric_evidence_errors(candidates,context,messages,state,check_literal_numbers=True):
    """Do not admit new specifications, contact numbers, or links from wording."""
    evidence=json.dumps({'sources':context.get('sources',[]),'messages':messages,'needs':state['needs']},ensure_ascii=False)
    numbers=set(re.findall(r'\d+(?:\.\d+)?',evidence.replace(',','')))
    errors=[]
    for i,c in enumerate(candidates):
        text=c['answer']+' '+(c.get('question') or {}).get('text','')
        extra=set(re.findall(r'\d+(?:\.\d+)?',text.replace(',','')))-numbers
        if check_literal_numbers and extra:errors.append(f'候选{i}包含没有原始资料或客户原话依据的数字：'+','.join(sorted(extra)))
        if any(url not in evidence for url in re.findall(r'https?://[^\s，。]+',text)):errors.append(f'候选{i}包含未经核实的链接')
    return errors


def choice_errors(candidates,state,messages,required_question,previous,group_complete=True):
    from .dialogue import checked_action,question_key
    errors=[];seen=set();old={normalized(c.get('intro',c['reply'])) for c in previous}
    for i,c in enumerate(candidates):
        reply=(c['answer']+'\n'+c['question']['text']).strip() if c.get('question') else c['answer']
        key=normalized(reply)
        if key in seen:errors.append(f'候选{i}与本组其他候选重复，请换一种完整表达')
        seen.add(key)
        if re.search('[?？]',c['answer']):errors.append(f'候选{i}的追问必须放在question内')
        q=c.get('question')
        if q and state.get('action',{}).get('kind')=='pause':errors.append('客户已结束当前交流，只需自然回应，不再主动追问')
        if required_question and (not q or NEED_KEYS.get(q['target'],q['target'])!=NEED_KEYS.get(required_question['target'],required_question['target'])):errors.append(f'候选{i}遗漏本轮必须澄清的条件')
        decision={'action':'inform','reply':reply,'question':q}
        errors.extend(f'候选{i}：{e}' for e in checked_action(decision,state,{},messages)['blockers'])
        if q and any(question_key(x)==question_key(q) and x.get('status')=='asked' for x in state['questions']):
            errors.append(f'候选{i}重复了尚待客户回答的问题')
    if group_complete:
        if not required_question and all(c.get('question') for c in candidates):errors.append('至少保留一个不追问的完整回答')
        if (state.get('continuation') or {}).get('mode')=='bridge' and not any(c.get('question') for c in candidates):errors.append('规划已确定自然了解下一项信息，至少保留一个有用且不重复的主动问题，不能整组收尾')
        if previous and not seen-old:errors.append('这一组与此前完全重复，必须提供新的完整表达，事实仍须一致')
    return errors


async def generate_choices(model,state,messages,context,previous=()):
    action=state['action'];required=action.get('question') if action['kind']=='ask' else None
    payload={'phase':'reply_choices','messages':messages[-20:],'current_topic':state.get('topic'),
             'needs':state['needs'],'questions':state['questions'],'delegation':state.get('delegation'),'conversation_scope':state.get('conversation_scope'),
             'continuation':state.get('continuation'),
             'draft_outline':context['answer'] if not context.get('sources') or state.get('goal')=='quote' else '',
             'unresolved_facts':context.get('unresolved_facts',[]),
             'current_action':action['kind'],'goal':state.get('goal'),'sources':context.get('sources',[]),
             'required_question':required,'operation':'regenerate' if previous else 'initial',
             'previous_candidates':[{'answer':c['answer'],'question':c.get('question')} for c in previous]}
    usage={};trace=[];errors=[];accepted=[]
    def collect(u):
        for k,v in u.items():
            if isinstance(v,(int,float)):usage[k]=usage.get(k,0)+v
            elif k=='model':usage[k]=v
    for attempt in range(3):
        instruction=PROPOSE+('\n本次是换一组：不要重新输出previous_candidates，至少两条使用此前没有展示过的完整说法。保持事实相同不代表逐字相同。' if previous else '')
        if errors:instruction+='\n上轮没有通过，必须改正以下错误再输出。尤其answer内不能留有问句；可选问题必须独立登记，没必要就删去问题保留回答。审查意见不是新的产品资料：'+json.dumps(errors,ensure_ascii=False)
        if accepted:instruction+='\naccepted_candidates已核验并保留，本次优先提供不同于它们的表述，以补齐缺少的候选。'
        result,u=await model(instruction,payload,3200,schema=ReplyChoices,system_prompt='',temperature=0.7 if previous else 0.4);collect(u)
        parsed=ReplyChoices.model_validate(result).model_dump();candidates=parsed['candidates']
        # Wording and optional follow-up are independent. A rejected optional
        # question must not discard an otherwise usable, grounded answer.
        from .dialogue import checked_action,question_key
        controls=[]
        for i,c in enumerate(candidates):
            question=c.get('question')
            if question and c['answer'].endswith(question['text']):
                c['answer']=c['answer'][:-len(question['text'])].strip()
            if question and not required:
                reasons=checked_action({'action':'inform','reply':c['answer'],'question':question},state,{},messages)['blockers']
                if (state.get('conversation_scope') or {}).get('mode')=='focused':reasons.append('客户已限定沟通范围，不增加可选追问')
                if state.get('goal')=='information' and context.get('unresolved_facts') and (state.get('continuation') or {}).get('mode')!='bridge':reasons.append('本轮仍缺产品资料，应先核实，不能用可选追问替代回答')
                if state['action']['kind']=='pause' or (state.get('continuation') or {}).get('mode')=='close' or any(question_key(q)==question_key(question) and q.get('status')=='asked' for q in state['questions']):reasons.append('当前不应再次追问')
                if reasons:
                    controls.append({'index':i,'removed_question':question,'reasons':reasons});c['question']=None;c['label']='直接回复'
        if not required and all(c.get('question') for c in candidates):
            controls.append({'index':0,'removed_question':candidates[0]['question'],'reasons':['保留不追问的回答供客服选择']})
            candidates[0]['question']=None;candidates[0]['label']='直接回复'
        review_payload={k:v for k,v in payload.items() if k!='validation_errors'}
        review,u=await model(ASSESS,{**review_payload,'phase':'review_choices','candidates':candidates},2600,schema=ChoicesReview,system_prompt='');collect(u)
        verdicts=ChoicesReview.model_validate(review).verdicts
        for verdict in verdicts:
            if verdict.question_errors and not required:
                candidate=candidates[verdict.index]
                controls.append({'index':verdict.index,'removed_question':candidate.get('question'),'reasons':verdict.question_errors})
                candidate['question']=None;candidate['label']='直接回复'
        errors=choice_errors(candidates,state,messages,required,previous)+numeric_evidence_errors(candidates,context,messages,state)
        if {v.index for v in verdicts}!={0,1,2}:errors.append('候选审查结果不完整')
        errors.extend(f'候选{v.index}：{e}' for v in verdicts for e in v.errors)
        if required:errors.extend(f'候选{v.index}：{e}' for v in verdicts for e in v.question_errors)
        trace.append({'continuation':copy.deepcopy(state.get('continuation')),'candidates':copy.deepcopy(candidates),'controls':controls,'review':review,'errors':errors})
        valid_indexes={v.index for v in verdicts if not v.errors and not (required and v.question_errors)}
        def key(c):return normalized(c['answer']+' '+(c.get('question') or {}).get('text',''))
        for i,c in enumerate(candidates):
            if i in valid_indexes and not any(e.startswith(f'候选{i}') for e in errors) and key(c) not in {key(x) for x in accepted}:
                accepted.append(c)
        proposed=accepted[:3]
        if len(proposed)==3 and not choice_errors(proposed,state,messages,required,previous):
            candidates=proposed
            suffix=context.get('suffix','')
            for c in candidates:
                c['id']=uuid.uuid4().hex
                c['intro']=(c['answer']+'\n'+c['question']['text']).strip() if c.get('question') else c['answer']
                c['reply']=c['intro']+suffix
            if previous:
                old={normalized(c.get('intro',c['reply'])) for c in previous}
                candidates.sort(key=lambda c:normalized(c['intro']) in old)
            return candidates,usage,trace
        # Keep reviewed candidates; do not repeatedly rewrite good drafts while
        # replacing a single bad or duplicate alternative.
        if len(accepted)>=3:accepted=[]
        payload.update(validation_errors=errors,accepted_candidates=copy.deepcopy(accepted))
    error=ValueError('候选回复未通过核验，已保留原记录；请重试或由客服处理')
    error.choice_trace=trace
    raise error


async def regenerate(cid,model):
    """Only replace draft choices. No extraction, planning, retrieval or profile writes."""
    from .dialogue import messages_for,profile_projection
    with Session() as s:
        conv=s.get(Conversation,cid);row=s.get(DialogueState,cid)
        if not conv or not row:raise ValueError('请先更新分析，再生成候选回复')
        state=json.loads(row.state);action=state.get('action',{});revision=row.revision;seq=conv.seq;locked=conv.locked
        if conv.status=='closed' or action.get('message_seq')!=seq or action.get('kind') in {'review','wait'} or not state.get('reply_context') or not state.get('continuation'):
            raise ValueError('对话已变化或当前无需回复，请先更新分析')
        messages=messages_for(s,cid)
    previous=state.get('reply_history',[])+action.get('candidates',[])
    responses=[];token=sink.set(responses)
    try:
        candidates,usage,trace=await generate_choices(model,state,messages,state['reply_context'],previous[-9:])
    except Exception as error:
        with Session() as s:
            s.add(DialogueRun(conversation_id=cid,input_revision=revision,input_seq=seq,status='failed',trace=json.dumps({'operation':'regenerate_replies','choices':getattr(error,'choice_trace',[]),'error_type':type(error).__name__,'model_responses':responses},ensure_ascii=False)));s.commit()
        raise
    finally:sink.reset(token)
    state['reply_history']=previous[-6:]
    action.update(id=uuid.uuid4().hex,candidates=candidates,revision=revision+1)
    state.update(revision=revision+1,updated_at=now())
    with Session() as s:
        # Revision and message checks also protect staff edits and concurrent sends.
        current=s.get(Conversation,cid)
        if not current or current.seq!=seq or current.locked!=locked or current.status=='closed':return {'stale':True,'message':'对话已变化，未覆盖候选','usage':usage}
        unchanged=exists().where(Conversation.id==cid,Conversation.seq==seq,Conversation.locked==locked,Conversation.status!='closed')
        result=s.execute(update(DialogueState).where(DialogueState.conversation_id==cid,DialogueState.revision==revision,unchanged).values(state=json.dumps(state,ensure_ascii=False),revision=revision+1,updated_at=now()))
        if not result.rowcount:s.rollback();return {'stale':True,'message':'分析已更新，未覆盖候选','usage':usage}
        s.add(DialogueRun(conversation_id=cid,input_revision=revision,input_seq=seq,status='completed',trace=json.dumps({'operation':'regenerate_replies','choices':trace,'model_responses':responses},ensure_ascii=False)))
        s.commit()
    return {'dialogue':state,'analysis':profile_projection(state),'reply':candidates[0]['reply'],'usage':usage,'seq':seq}
