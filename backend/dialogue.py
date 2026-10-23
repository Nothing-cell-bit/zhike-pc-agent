"""One persisted decision workflow for needs, dialogue, selection and quote preparation."""
import asyncio
import copy
import hashlib
import json
import re
import uuid
from typing import Literal
from datetime import datetime,timedelta,timezone
from pydantic import BaseModel,Field,ConfigDict,model_validator
from sqlalchemy import select,update
from .db import Session,Conversation,Message,DialogueState,DialogueRun,now
from .requirements import build_requirements,REQUIREMENT_FIELDS,_grounded,SCHEMA_VERSION
from .dialogue_catalog import catalog_index,load_options,load_information
from .dialogue_contract import Topic,Question,ReplyBlock,Review,NeedKey,NEED_KEYS,NEED_NAMES,NEEDS,UNDERSTAND,WRITE,CHECK,Continuation
from .quoting import prepare_quotes
from .llm_trace import sink

VERSION=4
PROMPT_VERSION='dialogue-2026-10-20-continuation'
Action=Literal['ask','recommend','compare','quote','inform','wait','pause']

class Evidence(BaseModel):
    message_id:str
    quote:str=Field(min_length=1,max_length=300)


class ConversationScope(BaseModel):
    mode:Literal['focused','open']
    duration:Literal['topic','conversation']='topic'
    evidence:Evidence

class FactQuote(Evidence):
    kind:Literal['fact','context']='fact'

class Fact(BaseModel):
    status:Literal['known','partial','unknown']='unknown'
    quotes:list[FactQuote]=Field(default_factory=list,max_length=6)
    confirmed_none:bool=False

class FactsDelta(BaseModel):
    model_config=ConfigDict(extra='forbid')
    user:Fact|None=None
    budget:Fact|None=None
    tasks:Fact|None=None
    software:Fact|None=None
    concerns:Fact|None=None
    next_step:Fact|None=None

class Resolution(BaseModel):
    question_id:str
    status:Literal['answered','partial','delegated','declined','uncertain']
    evidence:Evidence
    target:str=Field(default='',max_length=80)

class Selection(BaseModel):
    option_id:str
    evidence:Evidence

class ClearFact(BaseModel):
    field:str
    evidence:Evidence

class PurchaseIntent(BaseModel):
    mode:Literal['unknown','new','replace','additional','for_other','defer','undecided']='unknown'
    evidence:Evidence|None=None

class CustomerConstraint(BaseModel):
    field:str=Field(min_length=1,max_length=60)
    strength:Literal['hard','preference']
    statement:str=Field(min_length=1,max_length=160)
    evidence:Evidence

class StateReset(BaseModel):
    part:Literal['selection','delegation','goal']
    evidence:Evidence

class Decision(BaseModel):
    conversation_scope:ConversationScope|None=None
    continuation:Continuation|None=None
    acknowledged_message_id:str|None=None
    topic:Topic|None=None
    question:Question|None=None
    facts:FactsDelta=Field(default_factory=FactsDelta)
    customer_act:Literal['provide_information','request_information','request_recommendation','request_quote','confirm_option','change_requirements','decline_field','pause_consultation','decline_purchase','resume','acknowledge','other']
    customer_evidence:Evidence|None
    clear_fields:list[ClearFact]=Field(default_factory=list,max_length=7)
    goal:Literal['information','recommend','compare','quote','followup','none']='none'
    action:Action
    target:str=Field(default='',max_length=80)
    reply:str=Field(default='',max_length=600)
    reason:str=Field(default='',max_length=240)
    product_ids:list[str]=Field(default_factory=list,max_length=3)
    option_ids:list[str]=Field(default_factory=list,max_length=3)
    resolutions:list[Resolution]=Field(default_factory=list,max_length=6)
    selection:Selection|None=None
    delegation:Evidence|None=None
    quantity:int=Field(default=1,ge=1,le=1000)
    purchase_intent:PurchaseIntent=Field(default_factory=PurchaseIntent)
    constraints:list[CustomerConstraint]=Field(default_factory=list,max_length=10)
    resets:list[StateReset]=Field(default_factory=list,max_length=3)


class NeedChange(BaseModel):
    field:NeedKey
    operation:Literal['add','replace','confirm']
    fact:Fact


class NeedExtraction(BaseModel):
    changes:list[NeedChange]=Field(default_factory=list,max_length=6)
    purchase_intent:PurchaseIntent=Field(default_factory=PurchaseIntent)
    clear_fields:list[ClearFact]=Field(default_factory=list,max_length=7)
    constraints:list[CustomerConstraint]=Field(default_factory=list,max_length=10)


class Planning(BaseModel):
    """The planner cannot write any customer-profile field."""
    model_config=ConfigDict(extra='forbid')
    conversation_scope:ConversationScope|None=None
    continuation:Continuation
    acknowledged_message_id:str|None=None
    topic:Topic|None=None
    question:Question|None=None
    customer_act:Literal['provide_information','request_information','request_recommendation','request_quote','confirm_option','change_requirements','decline_field','pause_consultation','decline_purchase','resume','acknowledge','other']
    customer_evidence:Evidence|None
    goal:Literal['information','recommend','compare','quote','followup','none']='none'
    action:Action
    target:str=Field(default='',max_length=80)
    reply:str=Field(default='',max_length=600,pattern=r'^[^?？]*$',description='只写承接陈述，不含问句。阻塞问题放question，可选探索方向放continuation.next_information。')
    reason:str=Field(default='',max_length=240)
    product_ids:list[str]=Field(default_factory=list,max_length=3)
    option_ids:list[str]=Field(default_factory=list,max_length=3)
    resolutions:list[Resolution]=Field(default_factory=list,max_length=6)
    selection:Selection|None=None
    delegation:Evidence|None=None
    quantity:int=Field(default=1,ge=1,le=1000)
    resets:list[StateReset]=Field(default_factory=list,max_length=3)

class ConfigurationAttribute(BaseModel):
    key:str=Field(max_length=40)
    value:str=Field(max_length=80,description='一个明确的属性选项；不得把一组可选项或多个互斥值当成一个值')
    source_id:str
    quote:str=Field(min_length=1,max_length=300)

class ConfigurationProposal(BaseModel):
    product_id:str
    attributes:list[ConfigurationAttribute]=Field(min_length=1,max_length=5)

class Composition(BaseModel):
    model_config=ConfigDict(extra='forbid')
    blocks:list[ReplyBlock]=Field(default_factory=list,max_length=5)
    option_ids:list[str]=Field(default_factory=list,max_length=3)
    configuration_proposals:list[ConfigurationProposal]=Field(default_factory=list,max_length=3)

INTERPRET=UNDERSTAND
COMPOSE=WRITE


def initial_state(conv,messages):
    needs=build_requirements({},messages,json.loads(conv.locked),conv.stage)
    if 'progress' not in json.loads(conv.locked) and not needs['progress'].get('intent_mode'):
        needs['progress']=build_requirements({},messages)['progress']
    return {'version':VERSION,'revision':0,'message_seq':0,'needs':fact_view(needs),'goal':'none','questions':[],
            'delegation':None,'selection':{'status':'unconfirmed'},'options':[],'presentations':[],
            'quotes':[],'action':None,'topic':None,'conflicts':[],'source_warnings':[],'constraints':[]}


def fact_view(profile):
    return {**{field:profile[field] for field in REQUIREMENT_FIELDS},'schema_version':SCHEMA_VERSION,'summary':profile.get('summary','')}


def model_state(state):
    """Align observation names with the decision protocol, not legacy UI field names."""
    observed=copy.deepcopy(state)
    observed.pop('action',None)  # Previous generated prose is not fresh evidence.
    observed.pop('reply_context',None)
    observed.pop('reply_history',None)
    purchase=observed['needs'].pop('progress',{})
    observed['purchase_intent']={'mode':purchase.get('intent_mode','unknown'),'value':purchase.get('value','尚未了解'),'quotes':purchase.get('quotes',[]),'manual':purchase.get('manual',False)}
    observed['quotes']=[{k:v for k,v in q.items() if k not in {'approval_id','rule_id','source_id'}} for q in observed.get('quotes',[])]
    return observed


def messages_for(s,cid):
    return [{'id':m.id,'role':m.role,'text':m.content,'seq':m.seq} for m in s.scalars(select(Message).where(Message.conversation_id==cid).order_by(Message.seq))]


def view(cid):
    with Session() as s:
        row=s.get(DialogueState,cid)
        return json.loads(row.state) if row else None


def valid_evidence(item,messages,role='customer'):
    if not item:return False
    msg=next((m for m in messages if m['id']==item.get('message_id') and m['role']==role),None)
    return bool(msg and _grounded(item.get('quote',''),msg['text'],'dialogue'))


def configuration_options(proposals,tools):
    sources={s['id']:s for s in tools.get('sources',[])};products={o['product_id']:o for o in tools['options']};output=[]
    for proposal in proposals[:3]:
        pid=proposal.get('product_id');product=products.get(pid);attributes=proposal.get('attributes',[])[:5]
        if not product or not attributes:continue
        valid=[]
        for attr in attributes:
            source=sources.get(attr.get('source_id'));quote=attr.get('quote','');value=attr.get('value','')
            if re.search(r'[/／|]|可选|或者',value):continue
            if source and source.get('product_id')==pid and quote and quote in source['excerpt'] and value and re.sub(r'\s','',value) in re.sub(r'\s','',quote):valid.append(attr)
        if len(valid)!=len(attributes):continue
        label=' / '.join(a['value'] for a in valid)
        identifier='proposal-'+hashlib.sha256((pid+'|'+label).encode()).hexdigest()[:24]
        output.append({'id':identifier,'product_id':pid,'name':product['name'],'variant':label+'（销售组合待核实）',
                       'attributes':valid,'sku_verified':False,'source_ids':list(dict.fromkeys(a['source_id'] for a in valid)),'price':None})
    return output


def admit_composition(decision,state,tools):
    if decision['action'] not in {'recommend','compare'}:
        decision['configuration_proposals']=[]
        return decision
    proposed=configuration_options(decision.get('configuration_proposals',[]),tools)
    if decision.get('configuration_proposals') and len(proposed)!=len(decision['configuration_proposals']):
        decision['_invalid_configuration']=True
        errors=[];sources={s['id']:s for s in tools.get('sources',[])}
        for index,p in enumerate(decision['configuration_proposals']):
            for attribute_index,a in enumerate(p.get('attributes',[])):
                source=sources.get(a.get('source_id'));quote=a.get('quote','');value=a.get('value','')
                reason=''
                if re.search(r'[/／|]|可选|或者',value):reason='属性值包含多个互斥选项，须选一个'
                elif not source or source.get('product_id')!=p.get('product_id'):reason='引用未属于该产品的当前工具来源'
                elif quote not in source['excerpt']:reason='引用不在给定原文中，须逐字摘录'
                elif re.sub(r'\s','',value) not in re.sub(r'\s','',quote):reason='属性值不是引用中的连续原文，不能把共享后缀拼接进值；可仅选择原文中的单个容量或标识'
                if reason:errors.append({'proposal_index':index,'attribute_index':attribute_index,'provided_value':value,'source_id':a.get('source_id'),'reason':reason})
        decision['_configuration_errors']=errors
    if proposed and decision['action'] in {'recommend','compare'}:
        state['options'].extend(o for o in proposed if o['id'] not in {x['id'] for x in state['options']})
        decision['option_ids']=[o['id'] for o in proposed]
    return decision


def apply_decision(state,decision,messages,locks,stage,reviewed_fact_fields=()):
    state=copy.deepcopy(state);before=copy.deepcopy(state['needs']);raw=copy.deepcopy(before);rejected=[];accepted=set()
    scope=decision.get('conversation_scope')
    if scope and valid_evidence(scope['evidence'],messages) and not (scope['mode']=='open' and decision.get('customer_act')=='acknowledge'):
        latest=next((m for m in reversed(messages) if m['role']=='customer'),{})
        if scope['mode']=='focused' or scope['evidence']['message_id']==latest.get('id'):
            state['conversation_scope']=scope
    acknowledgement=decision.get('acknowledged_message_id')
    current=messages[-1] if messages else {}
    staff=next((m for m in reversed(messages) if m['role']=='staff' and m['seq']<current.get('seq',0)),None)
    acknowledged=decision.get('customer_act')=='acknowledge' and valid_evidence(decision.get('customer_evidence'),messages) and staff and staff['id']==acknowledgement
    if acknowledged and (state.get('conversation_scope') or {}).get('mode')=='focused' and state['conversation_scope'].get('duration','conversation')=='topic':
        state['conversation_scope']=None
    state['continuation']=decision.get('continuation') or {'mode':'close' if decision.get('customer_act') in {'pause_consultation','decline_purchase'} else 'answer','reason':'按本轮客户诉求回应','next_information':'','pending_topic':''}
    if (state.get('conversation_scope') or {}).get('mode')=='focused' and state['continuation']['mode']=='bridge':
        state['continuation']={'mode':'answer','reason':'尊重客户尚未释放的沟通范围','next_information':'','pending_topic':state['continuation'].get('pending_topic','')}
    topic=decision.get('topic')
    if topic and valid_evidence(topic.get('evidence'),messages):state['topic']={**topic,'status':'open'}
    if acknowledged and state.get('topic'):state['topic']['status']='acknowledged'
    query_evidence=topic.get('evidence') if topic else None
    query_evidence=query_evidence or (decision.get('customer_evidence') if decision.get('customer_act')=='request_information' else None)
    for field,item in decision.get('facts',{}).items():
        if item is None:continue
        if item.get('status')=='unknown' and not item.get('quotes') and not item.get('confirmed_none'):continue
        if field not in REQUIREMENT_FIELDS:continue
        if field=='progress':rejected.append(field);continue
        if field not in reviewed_fact_fields and query_evidence and any(q.get('message_id')==query_evidence.get('message_id') and
                (q.get('quote','') in query_evidence.get('quote','')) for q in item.get('quotes',[]) if q.get('kind','fact')=='fact'):
            rejected.append(field);continue
        if field in locks:
            projected=build_requirements({field:item},messages)[field]
            if projected['status']!='unknown' and projected['value']!=locks[field].get('value'):
                state['conflicts'].append({'field':field,'locked_value':locks[field].get('value'),'customer_value':projected['value']})
            continue
        projected=build_requirements({field:item},messages)[field]
        if projected['status']=='unknown':rejected.append(field);continue
        raw[field]=projected
        accepted.add(field)
    for clear in decision.get('clear_fields',[]):
        field=clear['field']
        if field in REQUIREMENT_FIELDS and field not in locks and field not in accepted and valid_evidence(clear['evidence'],messages):raw[field]={}
    intent=decision.get('purchase_intent') or {}
    if intent.get('mode') not in {None,'unknown'} and (intent.get('mode')!='defer' or decision.get('customer_act')=='decline_purchase') and valid_evidence(intent.get('evidence'),messages) and 'progress' not in locks:
        raw['progress']={'status':'known','intent_mode':intent['mode'],'quotes':[{**intent['evidence'],'kind':'fact'}]}
    state['needs']=fact_view(build_requirements(raw,messages,locks,stage))
    updated_fields={f for f,v in decision.get('facts',{}).items() if v is not None}|{x['field'] for x in decision.get('clear_fields',[])}
    state['constraints']=[x for x in state.get('constraints',[]) if x['field'] not in updated_fields]
    for constraint in decision.get('constraints',[]):
        if valid_evidence(constraint['evidence'],messages) and constraint['field'] not in locks:
            state['constraints']=[x for x in state['constraints'] if x['field']!=constraint['field']]
            state['constraints'].append(constraint)
    state['conflicts']=state['conflicts'][-10:]
    if any(state['needs'][f].get('value')!=before.get(f,{}).get('value') for f in REQUIREMENT_FIELDS):
        for quote in state['quotes']:quote['state']='invalidated'
        # Preserve references and the customer's prior selection, but require revalidation.
        if state['selection'].get('option_id'):state['selection']['needs_revalidation']=True
    for resolution in decision.get('resolutions',[]):
        if not valid_evidence(resolution.get('evidence'),messages):continue
        question=next((q for q in state['questions'] if q['id']==resolution['question_id']),None)
        staff=next((m for m in messages if m['id']==resolution['question_id'] and m['role']=='staff'),None)
        answer=next(m for m in messages if m['id']==resolution['evidence']['message_id'])
        if not question and staff:
            question={'id':staff['id'],'text':staff['text'],'target':resolution.get('target',''),'seq':staff['seq']};state['questions'].append(question)
        if question and answer['seq']>question.get('seq',0):question.update({'status':resolution['status'],'answer':resolution['evidence'],'target':question.get('target') or resolution.get('target','')})
    delegation=decision.get('delegation')
    act=decision.get('customer_act','other');act_evidence=decision.get('customer_evidence')
    if valid_evidence(act_evidence,messages):
        state['customer_act']={'kind':act,'evidence':act_evidence}
    if valid_evidence(delegation,messages):state['delegation']=delegation
    selection=decision.get('selection')
    answer_seq=next((m['seq'] for m in messages if selection and m['id']==selection.get('evidence',{}).get('message_id')),0)
    delivered={oid for p in state['presentations'] if p['seq']<answer_seq for oid in p['option_ids']}
    same_as_delegation=bool(selection and delegation and selection.get('evidence')==delegation)
    if selection and act!='request_recommendation' and not same_as_delegation and selection['option_id'] in delivered and valid_evidence(selection.get('evidence'),messages):
        option=next((o for o in state['options'] if o['id']==selection['option_id']),{})
        state['selection']={**selection,'status':'confirmed','scope':'sku' if option.get('sku_verified') else 'preference','needs_revalidation':False}
    for reset in decision.get('resets',[]):
        message=next((m for m in messages if m['id']==reset['evidence']['message_id']),None)
        if message and message['seq']>state.get('message_seq',0) and valid_evidence(reset['evidence'],messages):
            if reset['part']=='selection':
                state['selection']={'status':'unconfirmed'}
                for quote in state['quotes']:quote['state']='invalidated'
            elif reset['part']=='delegation':
                state['delegation']=None
                for question in state['questions']:
                    if question.get('status')=='delegated':question['status']='reopened'
            else:state['goal']='none'
    goal=decision.get('goal')
    if goal:state['goal']=goal
    return state,rejected


def question_key(question):
    if question.get('scope','field')=='field':
        target=question.get('target','')
        if target=='purchase_intent':return 'progress'
        if target in NEED_KEYS or target in NEED_NAMES:return NEED_KEYS.get(target,target)
    key=question.get('topic_key') or question.get('target','')
    return NEED_KEYS.get(key,key)


def unverified_amounts(reply,state):
    from decimal import Decimal
    unverified=set()
    allowed_money=set()
    for q in state.get('quotes',[]):
        if q.get('state')=='invalidated':continue
        if q.get('total_minor') is not None:allowed_money.add(DecimalString(q['total_minor']))
        ref=q.get('reference') or {}
        if ref.get('amount_minor') is not None:allowed_money.add(DecimalString(ref['amount_minor']))
    # The only model-generated monetary claims admitted here must match tool amounts.
    amounts={Decimal(x) for x in allowed_money}
    budget=state['needs'].get('budget',{}).get('value','')
    for number,unit in re.findall(r'(\d+(?:\.\d+)?)\s*(万元|万|w|千元|千|k|元)?',budget,re.I):
        multiplier=10000 if unit.lower() in {'万元','万','w'} else 1000 if unit.lower() in {'千元','千','k'} else 1
        amounts.add(Decimal(number)*multiplier)
    for symbol,number,suffix in re.findall(r'(¥|￥)?\s*(\d[\d,]*(?:\.\d+)?)\s*(元)?',reply):
        if (symbol or suffix) and Decimal(number.replace(',','')) not in amounts:unverified.add(number.replace(',',''))
    return unverified


def checked_action(decision,state,option_map,messages):
    kind=decision['action'];reply=decision.get('reply','').strip();target=decision.get('target','');blocked=[]
    if decision.get('_invalid_configuration'):blocked.append('配置属性必须是有原文支持的单一选项，不能把多档可选规格合成一个已选值')
    question=decision.get('question')
    if kind=='ask' and not question:blocked.append('缺少明确的必要追问计划')
    if question:
        target=question['target']
        key=question_key(question)
        covered=[q for q in state['questions'] if key and question_key(q)==key and q.get('status') in {'answered','delegated','declined'}]
        if covered:blocked.append('所问的信息已经回答、委托选择或拒答')
        field=NEED_KEYS.get(key,{'identity':'user','usage':'tasks','purchase_intent':'progress'}.get(key,key))
        if question.get('scope')=='detail' and not question.get('topic_key'):blocked.append('细节追问需要独立的语义标识，不能重复询问整个字段')
        if field in REQUIREMENT_FIELDS and state['needs'][field].get('status')=='known' and question.get('scope','field')!='detail':blocked.append('所问字段已经明确')
        if target=='configuration' and state.get('delegation'):blocked.append('客户已委托推荐配置，应提供候选或解释具体取舍')
    if kind=='wait' and messages and messages[-1]['role']=='customer':blocked.append('客户已有新回复，必须处理本轮变化，不能继续等待同一条回复')
    selected=[oid for oid in decision.get('option_ids',[]) if oid in option_map]
    if kind in {'recommend','compare'} and not selected:blocked.append('没有有效的候选配置')
    if kind=='quote' and not selected:blocked.append('报价缺少有效的销售配置，不能生成空报价动作')
    if kind=='recommend' and any(option_map[x].get('budget_fit')=='exceeds' for x in selected):blocked.append('候选的有效报价已超过客户硬性预算，不能作为预算内推荐')
    if unverified_amounts(reply,state):blocked.append('回复中出现金额，但无报价或客户预算依据')
    if kind not in {'wait','pause'} and not reply:blocked.append('缺少可展示的建议')
    return {'id':uuid.uuid4().hex,'kind':'review' if blocked else kind,'target':target,
            'reply':'' if blocked else reply,'reason':decision.get('reason',''),'option_ids':selected,
            'blockers':list(dict.fromkeys(blocked)),'status':'needs_review' if blocked else 'proposed','question':question if not blocked else None}


def DecimalString(minor):
    from decimal import Decimal
    return format(Decimal(minor)/100,'f')


def verified_budget_fit(state,options,quotes):
    """Only compare authoritative payable amounts; historical prices never prove fit."""
    from decimal import Decimal
    text=state['needs'].get('budget',{}).get('value','')
    hard=any(c.get('field')=='budget' and c.get('strength')=='hard' for c in state.get('constraints',[]))
    hard=hard or bool(re.search(r'以内|不超过|上限|最多',text))
    amounts=[]
    if hard:
        for number,unit in re.findall(r'(\d+(?:\.\d+)?)\s*(万元|万|w|千元|千|k|元)?',text,re.I):
            multiplier=10000 if unit.lower() in {'万元','万','w'} else 1000 if unit.lower() in {'千元','千','k'} else 1
            amounts.append(int(Decimal(number)*multiplier*100))
    limit=max(amounts) if amounts else None
    for option in options:
        totals=[q['total_minor'] for q in quotes if q['option_id']==option['id'] and q['state']=='ready_for_review']
        option['price_verified']=bool(totals)
        option['budget_fit']='unknown' if limit is None or not totals else 'fits' if min(totals)<=limit else 'exceeds'


def profile_projection(state):
    needs=copy.deepcopy(state['needs']);action=state.get('action') or {}
    status='waiting' if action.get('kind')=='wait' else 'paused' if action.get('kind')=='pause' else 'ready' if action.get('reply') else 'review'
    question=action.get('question')
    needs['next_question']={'state':'ready' if question else 'waiting','field':question['target'] if question else '', 'text':question['text'] if question else ''}
    needs['questions']=[question['text']] if question else []
    needs['dialogue_version']=VERSION
    return needs


def check_blocks(blocks,tools):
    sources={item['id']:item for item in tools.get('sources',[])};errors=[]
    for index,block in enumerate(blocks):
        citations=block.get('citations',[])
        if block['kind']=='fact' and not citations:errors.append(f'blocks[{index}]的事实缺少来源')
        for citation in citations:
            source=sources.get(citation['source_id'])
            if not source:errors.append(f'blocks[{index}]引用了本轮不存在的资料')
        if re.search(r'[?？]',block['text']):errors.append(f'blocks[{index}]包含表达器无权新增的问句')
    return errors


def materialize_facts(blocks,tools):
    """Compile product facts from source excerpts; generated prose cannot extend them."""
    sources={item['id']:item for item in tools.get('sources',[])};errors=[]
    for index,block in enumerate(blocks):
        if block['kind']!='fact':continue
        block['text']=''
        citations=block.get('citations',[])
        if len(citations)!=1:
            errors.append(f'blocks[{index}]事实须引用一个原文片段，多个事实请拆开');continue
        citation=citations[0];source=sources.get(citation['source_id']);excerpt=citation.get('excerpt','').strip()
        if not source or not excerpt or excerpt not in source['excerpt']:
            errors.append(f'blocks[{index}]摘录不是对应来源中的连续原文');continue
        # Include adjacent footnotes; never turn a conditional specification into an unconditional one.
        tail=source['excerpt'][source['excerpt'].index(excerpt)+len(excerpt):].lstrip()
        notes=[]
        for paragraph in re.split(r'\n\s*\n',tail):
            if not paragraph.startswith('*'):break
            notes.append(paragraph.lstrip('*').strip())
        lines=source['excerpt'].splitlines();heading=lines[0].lstrip('# ').strip() if lines and lines[0].startswith('##') else ''
        text=re.sub(r'(?m)^#{1,6}\s*','',excerpt).strip()
        parts=[re.sub(r'\s+',' ',part).lstrip('*').strip() for part in re.split(r'\n\s*\n',text) if part.strip()]
        if parts and parts[0]==heading:parts.pop(0)
        compact=[];position=0
        while position<len(parts):
            part=parts[position]
            if re.fullmatch(r'[\u4e00-\u9fff]{1,8}',part) and position+1<len(parts):
                compact.append(part+' '+parts[position+1]);position+=2
            else:compact.append(part);position+=1
        text='；'.join(compact)
        if heading and len(heading)<40:text=heading+'：'+text
        block['text']='\n'.join([text,*notes])
    return errors


def reconcile_receipt(plan,messages):
    """A grounded receipt cannot carry a contradictory session-ending action."""
    if plan.get('customer_act')!='acknowledge' or not messages:return plan
    current=messages[-1]
    staff=next((m for m in reversed(messages) if m['role']=='staff' and m['seq']<current['seq']),None)
    if not staff or plan.get('acknowledged_message_id')!=staff['id'] or not valid_evidence(plan.get('customer_evidence'),messages):return plan
    plan=copy.deepcopy(plan)
    if (plan.get('continuation') or {}).get('mode')=='close':
        plan['continuation'].update(mode='answer',reason='仅确认收到上一条说明，未明确结束整场咨询',next_information='')
    if plan['action']=='pause':plan.update(action='inform',question=None)
    return plan


def current_turn_errors(plan,current,messages=()):
    if not current or current['role']!='customer':return []
    errors=[]
    if plan['action']=='wait':errors.append('current_turn是尚未处理的客户消息，不能选择wait；应回应当前诉求或确认已收到本轮指令')
    if plan['action']=='ask' and not plan.get('question'):errors.append('ask必须有明确的必要追问计划question')
    if plan.get('goal')=='information' and plan['action'] in {'quote','recommend','compare'}:errors.append('信息咨询不能触发选型或报价动作')
    evidence=plan.get('customer_evidence')
    if evidence and evidence.get('message_id')!=current['id']:errors.append('customer_evidence必须对应current_turn，不能把早先客户消息当成本轮请求')
    topic=plan.get('topic')
    if topic and plan.get('customer_act')=='request_information' and topic['evidence']['message_id']!=current['id']:
        errors.append('本轮信息咨询的topic必须承接current_turn；历史仅用于解析产品和指代')
    continuation=plan.get('continuation') or {}
    if continuation.get('mode')=='close' and plan.get('customer_act') not in {'pause_consultation','decline_purchase'}:
        errors.append('close需要客户明确结束整场咨询的行为；确认收到上一条答复不是结束咨询')
    if continuation.get('mode')=='bridge' and not continuation.get('next_information'):
        errors.append('bridge必须指出有实际价值且未知的下一步信息，不能只是泛泛推进')
    if continuation.get('mode')=='bridge' and (plan['action']=='ask' or plan.get('question')):
        errors.append('bridge是可选的自然推进，不是阻塞式ask；使用inform承接、question=null，探索方向写next_information，保留不追问的候选')
    if plan.get('customer_act')=='acknowledge':
        staff=next((m for m in reversed(messages) if m['role']=='staff' and m['seq']<current['seq']),None)
        if not staff or plan.get('acknowledged_message_id')!=staff['id']:errors.append('acknowledge必须关联客户正在确认的真实客服答复')
        if plan['action']=='pause':errors.append('局部确认不能暂停整场咨询')
    return errors


def independent_identity(facts):
    """Identity needs its own evidence; it cannot borrow the same span used as a task/app/budget."""
    facts=dict(facts)
    tasks=facts.get('tasks');software=facts.get('software')
    if tasks and software:
        overlaps=any(q['message_id']==other['message_id'] and (q['quote'] in other['quote'] or other['quote'] in q['quote'])
                     for q in tasks.get('quotes',[]) if q.get('kind','fact')=='fact'
                     for other in software.get('quotes',[]) if other.get('kind','fact')=='fact')
        if overlaps:facts.pop('tasks')
    identity=facts.get('user')
    if not identity:return facts
    others=[quote for field,item in facts.items() if field!='user' and item for quote in item.get('quotes',[]) if quote.get('kind','fact')=='fact']
    reused=any(q['message_id']==other['message_id'] and (q['quote'] in other['quote'] or other['quote'] in q['quote'])
               for q in identity.get('quotes',[]) if q.get('kind','fact')=='fact' for other in others)
    return {key:value for key,value in facts.items() if key!='user'} if reused else facts


def quote_signature(quotes):
    keys=('option_id','level','state','total_minor','rule_id','valid_until','quantity','required_qualifications','sku_ref','configuration_label','is_demo')
    return json.dumps([{k:q.get(k) for k in keys} for q in sorted(quotes,key=lambda q:(q['option_id'],q.get('level','')))],sort_keys=True,ensure_ascii=False)


def waiting_owner(state):
    if any(t.get('kind')=='verify' and t.get('status') not in {'completed','cancelled'} for t in state.get('tasks',[])):
        return 'staff'
    if state.get('goal')=='quote' and any(q.get('state')=='ready_for_review' and q.get('delivery_status')=='sent' and q.get('sent_message_id') for q in state.get('quotes',[])):
        return 'customer'
    blocked={'needs_price','needs_configuration','needs_approval','needs_qualification','invalidated'}
    return 'staff' if state.get('goal')=='quote' and any(q.get('state') in blocked for q in state.get('quotes',[])) else 'customer'


async def run(cid,model,requested_product='',*,with_choices=False):
    with Session() as s:
        conv=s.get(Conversation,cid)
        if not conv:raise ValueError('会话不存在')
        messages=messages_for(s,cid);seq=conv.seq;locks=json.loads(conv.locked);locked_snapshot=conv.locked;stage=conv.stage
        row=s.get(DialogueState,cid);revision=row.revision if row else 0
        state=json.loads(row.state) if row else initial_state(conv,messages)
        upgraded=state.get('version',0)<VERSION
        if upgraded:
            state['version']=VERSION
            state['needs']=fact_view(build_requirements({},messages,locks,stage))
            state['topic']=None
            state['message_seq']=0
        state['needs']=fact_view(state['needs'])
        latest_customer=max((m['seq'] for m in messages if m['role']=='customer'),default=0)
        quote_work=False
        if row and not upgraded and state.get('continuation') and latest_customer<=state.get('message_seq',0) and (state.get('action') or {}).get('kind') in {'wait','pause'}:
            if state['action']['kind']=='wait' and state.get('goal')=='quote' and state.get('quotes'):
                ids={q['option_id'] for q in state['quotes']}
                known=[o for o in state['options'] if o['id'] in ids]
                refreshed=prepare_quotes(known,state['quotes'][0].get('quantity',1),conv.customer_id)
                quote_work=bool(known and quote_signature(refreshed)!=quote_signature(state['quotes']))
            if not quote_work:
                return {'analysis':profile_projection(state),'dialogue':state,'usage':{},'seq':seq,'reply':'','questions':[],'recommendations':[]}
        runrow=DialogueRun(conversation_id=cid,input_revision=revision,input_seq=seq);s.add(runrow);s.commit();run_id=runrow.id
    trace={'prompt_version':PROMPT_VERSION,'decisions':[],'tools':{},'rejected':[],'model_responses':[]};usage={}
    trace_token=sink.set(trace['model_responses'])
    def collect(value):
        for k,v in value.items():
            if isinstance(v,(int,float)):usage[k]=usage.get(k,0)+v
            elif k=='model':usage[k]=v
    try:
        recent=[m for m in messages if m['seq']>state.get('message_seq',0)]
        # Stable state retains facts; the context tail provides conversational links.
        tail=messages if upgraded or not row else messages[-max(12,len(recent)):]
        base_state=copy.deepcopy(state)
        model_locks={('purchase_intent' if field=='progress' else field):value for field,value in locks.items()}
        current_turn=messages[-1] if messages else None
        context={'phase':'interpret','state':model_state(state),'manual_locks':model_locks,'messages':tail,'current_turn':current_turn,'catalog':catalog_index(),'requested_product_id':requested_product,'rebuild_needs_from_history':upgraded or not row}
        if quote_work:
            ids=list(dict.fromkeys(q['option_id'] for q in state['quotes']))
            raw={'customer_act':'other','customer_evidence':None,'goal':'quote','action':'quote','option_ids':ids[:3],
                 'product_ids':list(dict.fromkeys(o['product_id'] for o in state['options'] if o['id'] in ids))[:3],
                 'quantity':state['quotes'][0].get('quantity',1),'reason':'门店报价数据变化，继续处理已经明确的报价任务，不重复向客户采集信息'}
            trace['plan_source']='quote_source_update'
        else:
            need_context={'phase':'needs','previous_needs':{NEED_NAMES.get(k,k):v for k,v in base_state['needs'].items()},'manual_locks':{NEED_NAMES.get(k,k):v for k,v in model_locks.items()},
                          'messages':tail,'current_turn':current_turn,'rebuild_needs_from_history':upgraded or not row}
            (raw,u),(extracted,need_usage)=await asyncio.gather(
                model(INTERPRET,context,2600,schema=Planning,system_prompt=''),
                model(NEEDS,need_context,2600,schema=NeedExtraction,system_prompt=''))
            collect(u);collect(need_usage)
            personal=NeedExtraction.model_validate(extracted).model_dump();trace['need_extraction']=copy.deepcopy(personal)
            for key in ('constraints','clear_fields'):
                for item in personal[key]:item['field']=NEED_KEYS.get(item['field'],item['field'])
            delta={}
            for change in personal['changes']:
                if change['operation']=='confirm':continue
                field=NEED_KEYS[change['field']];fact=change['fact']
                if change['operation']=='add' and field in {'tasks','software','concerns'}:
                    old=base_state['needs'].get(field,{}).get('quotes',[])
                    fact['quotes']=list({(q['message_id'],q['quote']):q for q in [*old,*fact['quotes']]}.values())[-6:]
                delta[field]=fact
            raw={**Planning.model_validate(raw).model_dump(),**{k:v for k,v in personal.items() if k!='changes'},
                 'facts':independent_identity(delta)}
        plan=Decision.model_validate(raw).model_dump()
        reconciled=reconcile_receipt(plan,messages)
        if reconciled!=plan:trace['reconciled_receipt']=copy.deepcopy(plan)
        plan=reconciled
        if not quote_work:
            plan_errors=current_turn_errors(plan,current_turn,messages)
            if plan_errors:
                trace['rejected_plan']=copy.deepcopy(plan)
                corrected,u=await model(INTERPRET,{**context,'validation_errors':plan_errors},1800,schema=Planning,system_prompt='');collect(u)
                plan=reconcile_receipt(Decision.model_validate({**plan,**Planning.model_validate(corrected).model_dump()}).model_dump(),messages)
                if current_turn_errors(plan,current_turn,messages):raise ValueError('未能识别本轮客户请求，请重新整理')
        trace['decisions'].append(copy.deepcopy(plan))
        state,rejected=apply_decision(state,plan,messages,locks,stage)
        trace['rejected']=rejected
        if messages and messages[-1]['role']=='staff' and not quote_work:
            plan.update(action='wait',reply='',question=None,option_ids=[],product_ids=[])
        elif plan['customer_act'] in {'decline_purchase','pause_consultation'} and valid_evidence(plan.get('customer_evidence'),messages):
            plan.update(action='pause',question=None,option_ids=[],product_ids=[])
        information=plan['goal']=='information' and plan['action']=='inform'
        tool_action=plan['action'] in {'recommend','compare','quote','inform'} and plan['goal']!='none'
        if plan['customer_act']=='acknowledge' and (state.get('continuation') or {}).get('mode')=='bridge':
            tool_action=False
        tools={'sources':[]}
        if tool_action:
            requested=(plan.get('topic') or {}).get('product_ids') or plan.get('product_ids') or ([requested_product] if requested_product else [])
            if not requested:requested=(state.get('topic') or {}).get('product_ids',[])
            if information:
                tools=await load_information(requested)
            else:
                if not requested and state['selection'].get('option_id'):
                    selected=next((o for o in state['options'] if o['id']==state['selection']['option_id']),None)
                    if selected:requested=[selected['product_id']]
                tools=await load_options(requested)
                relevant=[o for o in state['options'] if not requested or o['product_id'] in requested]
                tools['options']=list({o['id']:o for o in [*tools['options'],*relevant]}.values())
                quote_checks=prepare_quotes(tools['options'],plan.get('quantity',1),conv.customer_id)
                verified_budget_fit(state,tools['options'],quote_checks)
                tools['quote_checks']=[{k:q.get(k) for k in ('option_id','level','state','total_minor','blockers')} for q in quote_checks]
                all_options={o['id']:o for o in [*state['options'],*tools['options']]}
                state['options']=list(all_options.values())
                if plan['action']=='quote' or (plan['goal']=='quote' and plan['action']=='inform' and state['selection'].get('option_id')):
                    ids=plan.get('option_ids') or ([state['selection']['option_id']] if state['selection'].get('option_id') else [])
                    quote_options=[all_options[x] for x in ids if x in all_options] or tools['options'][:3]
                    state['quotes']=prepare_quotes(quote_options,plan.get('quantity',1),conv.customer_id)
                verified_ids={q['option_id'] for q in quote_checks if q['state']=='ready_for_review'}
                tools['options']=[{**{k:v for k,v in o.items() if k!='price'},
                    **({'sku_verified':True,'configuration_status':'verified'} if o['id'] in verified_ids else {})} for o in tools['options']]
                tools['quotes']=[{k:v for k,v in q.items() if k not in {'reference','total_minor','unit_minor','fees_minor','approval_id','rule_id','source_id'}} for q in state['quotes']]
            state['source_warnings']=tools.get('warnings',[])
        trace['tools']=copy.deepcopy(tools)
        errors=[];trace['reviews']=[];previous_output=None;previous_rendered=''
        for attempt in range(2):
            observed=model_state(state)
            if information:
                observed={k:observed[k] for k in ('needs','topic','goal','questions','customer_act','purchase_intent') if k in observed}
            compose_payload={'phase':'compose','state':observed,'plan':plan,'messages':tail,'current_turn':current_turn,'tools':tools}
            if errors:compose_payload.update(validation_errors=errors,previous_output=previous_output,previous_rendered_reply=previous_rendered)
            if tool_action:
                result,u=await model(COMPOSE,compose_payload,3600,schema=Composition,system_prompt='');collect(u)
                composition=Composition.model_validate(result).model_dump()
            else:
                composition={'blocks':[{'kind':'acknowledgement','text':plan['reply'],'citations':[]}] if plan.get('reply') and plan['action']!='ask' else [],
                             'option_ids':[],'configuration_proposals':[]}
            trace['decisions'].append(copy.deepcopy(composition))
            decision={**plan,**{k:v for k,v in composition.items() if k!='blocks'}}
            if information:decision.update(option_ids=[],configuration_proposals=[])
            elif tool_action:decision=admit_composition(decision,state,tools)
            # A search that yields no verified option is still answerable: explain
            # the knowledge gap instead of presenting a fabricated recommendation.
            if decision['action'] in {'recommend','compare'} and not decision.get('option_ids') and not decision.get('_configuration_errors'):
                decision['action']='inform'
                trace['tool_outcome']='no_verified_options'
            blocks=composition['blocks']
            structural_errors=materialize_facts(blocks,tools)
            if with_choices and plan['goal']!='quote':
                # Price claims have a separate program-owned authority. Reject an
                # unrelated, ungrounded price aside without discarding the valid
                # answer or the customer's newly confirmed requirements.
                admitted=[block for block in blocks if not unverified_amounts(block['text'],state)]
                if admitted and len(admitted)!=len(blocks):
                    trace.setdefault('rejected_financial_blocks',[]).extend(copy.deepcopy(block) for block in blocks if block not in admitted)
                    blocks=admitted
            structural_errors+=check_blocks(blocks,tools)
            if information and not with_choices:
                fact_sources={citation['source_id'] for block in blocks if block['kind']=='fact' for citation in block.get('citations',[])}
                if any(block['kind']=='explanation' and (not block.get('citations') or any(citation['source_id'] not in fact_sources for citation in block['citations'])) for block in blocks):
                    structural_errors.append('信息咨询的解释只能重述本次已列事实，须引用相同资料；缺证据的结论应使用limitation保留未知')
            if decision.get('_configuration_errors'):structural_errors.append(json.dumps(decision['_configuration_errors'],ensure_ascii=False))
            errors=list(structural_errors)
            options={o['id']:o for o in state['options']}
            decision['reply']='\n'.join(block['text'] for block in blocks)
            if plan.get('question'):
                decision['reply']=(decision['reply']+'\n'+plan['question']['text']).strip()
            action=checked_action(decision,state,options,messages)
            errors.extend(action['blockers'])
            if blocks or plan.get('question') or any(plan['facts'].values()):
                review_payload={'phase':'review','messages':tail,'current_turn':current_turn,'previous_needs':{NEED_NAMES.get(k,k):v for k,v in base_state['needs'].items()},
                    'plan':{**plan,'facts':{NEED_NAMES.get(k,k):v for k,v in plan['facts'].items()}},
                    'proposed_needs':{NEED_NAMES.get(k,k):v for k,v in state['needs'].items()},'reply_blocks':blocks,'question':plan.get('question'),'tools':tools}
                evidence_index={source['id']:source for source in tools.get('sources',[])}
                review_payload['block_evidence']=[{'index':index,'text':block['text'],
                    'sources':[evidence_index[c['source_id']] for c in block.get('citations',[]) if c['source_id'] in evidence_index]} for index,block in enumerate(blocks)]
                reviewed,u=await model(CHECK,review_payload,2600,schema=Review,system_prompt='');collect(u)
                review=Review.model_validate(reviewed).model_dump();trace['reviews'].append(copy.deepcopy(review))
                for key in ('valid_need_fields','invalid_need_fields'):review[key]=[NEED_KEYS[field] for field in review[key]]
                # The reviewer can veto, never manufacture a replacement fact or strategy.
                denied={field for field,item in plan['facts'].items() if item and (field in review['invalid_need_fields'] or field not in review['valid_need_fields'])}
                for field in denied:
                    plan['facts'][field]=None
                    plan['clear_fields']=[item for item in plan['clear_fields'] if item['field']!=field]
                    plan['constraints']=[item for item in plan['constraints'] if item['field']!=field]
                for control in review['invalid_controls']:
                    if control in {'question','selection','delegation'}:plan[control]=None
                    elif control=='purchase_intent':plan[control]={'mode':'unknown','evidence':None}
                    else:plan[control]=[]
                admitted,_=apply_decision(base_state,plan,messages,locks,stage,reviewed_fact_fields=review['valid_need_fields'])
                for key in ('needs','constraints','conflicts','selection','delegation'):
                    state[key]=admitted[key]
                decision['question']=plan.get('question')
                decision['reply']='\n'.join(block['text'] for block in blocks)
                if plan.get('question'):decision['reply']=(decision['reply']+'\n'+plan['question']['text']).strip()
                action=checked_action(decision,state,options,messages)
                verdicts={item['index']:item for item in review['block_checks']}
                unsupported=[f"blocks[{index}]："+(verdicts[index]['reason'] if index in verdicts else '缺少语义核验结果')
                             for index in range(len(blocks)) if index not in verdicts or not verdicts[index]['supported']]
                errors=structural_errors+review['response_errors']+unsupported+action['blockers']
            if not errors:break
            previous_output=trace['decisions'][-1];previous_rendered=decision['reply']
            if not tool_action or attempt==1:
                action.update(kind='review',reply='',question=None,status='needs_review',blockers=list(dict.fromkeys(errors)))
                break
        trace['response_validation_errors']=list(dict.fromkeys(errors))
        state['data_quality_issues']=[{'field':field,'message_seq':seq} for field in rejected]
        action['intro']=action['reply']
        if not information and action['option_ids'] and action['kind'] not in {'review','wait','pause'}:
            lines=[]
            for index,oid in enumerate(action['option_ids'],1):
                option=options[oid]
                sale=next((q for q in state['quotes'] if q['option_id']==oid and q.get('sku_ref') and q['state']=='ready_for_review'),None)
                variant=option['variant'].replace('（销售组合待核实）','') if sale else option['variant']
                lines.append(f"方案{index}：{option['name']}，{variant}")
                for quote in (q for q in state['quotes'] if q['option_id']==oid and q['state']!='invalidated'):
                    label={'L1':'单机标准','L2':'资格优惠','L3':'套装方案','L4':'审批专项'}.get(quote.get('level'),'报价')
                    if quote['total_minor'] is not None:lines.append(f"销售SKU：{quote['sku_ref']}；{label}含税报价 ¥{DecimalString(quote['total_minor'])}，数量 {quote['quantity']}，有效至 {datetime.fromisoformat(quote['valid_until']).astimezone(timezone(timedelta(hours=8))).strftime('%Y-%m-%d %H:%M')}（北京时间）")
                    else:
                        ref=quote.get('reference') or {}
                        if ref.get('amount_minor'):lines.append(f"历史参考快照 ¥{DecimalString(ref['amount_minor'])}（{ref.get('checked_at','')}，{ref.get('kind','')}），实际门店价待核验。")
                        else:lines.append(label+'价格及适用条件待核验。')
            if lines:action['reply']+='\n\n'+'\n'.join(lines)
        retained=set(action['option_ids'])|{x for p in state['presentations'] for x in p['option_ids']}
        if state['selection'].get('option_id'):retained.add(state['selection']['option_id'])
        state['options']=[o for o in state['options'] if o['id'] in retained]
        if conv.status=='closed':action.update(kind='pause',reply='',status='paused')
        state['stage_revisit_required']=stage in {'已成交','暂不购买'} and action['kind'] not in {'pause','wait','review'}
        state['action']=action
        state['next_owner']='none' if action['kind']=='pause' else waiting_owner(state) if action['kind']=='wait' else 'staff'
        if with_choices and action['reply'] and conv.status!='closed' and action['kind'] not in {'review','wait'}:
            from .dialogue_replies import generate_choices
            cited={c['source_id'] for b in blocks for c in b.get('citations',[])}
            primary=[source for source in tools.get('sources',[]) if '产品事实' in source.get('title','')]
            guidance=[{**source,'role':'selection_guidance'} for source in tools.get('sources',[]) if '卖点与限制' in source.get('title','')]
            state['reply_context']={'answer':action['intro'],
                'sources':(primary+guidance if not information else primary) or [source for source in tools.get('sources',[]) if source['id'] in cited],
                'unresolved_facts':[block['text'] for block in blocks if block['kind']=='limitation'],
                'suffix':action['reply'][len(action['intro']):]}
            candidates,u,choice_trace=await generate_choices(model,state,messages,state['reply_context']);collect(u)
            action['candidates']=candidates
            state['reply_history']=[]
            trace['choices']=choice_trace
        with Session() as s:
            current=s.get(Conversation,cid);stored=s.get(DialogueState,cid)
            latest_revision=stored.revision if stored else 0
            if current.seq!=seq or latest_revision!=revision or json.loads(current.locked)!=locks:
                trace['outcome']='superseded';s.get(DialogueRun,run_id).status='superseded';s.get(DialogueRun,run_id).trace=json.dumps(trace,ensure_ascii=False);s.commit()
                return {'stale':True,'usage':usage,'message':'对话或人工修正已变化，旧建议未覆盖'}
            state.update({'revision':revision+1,'message_seq':seq,'updated_at':now()})
            action['revision']=revision+1;action['message_seq']=seq
            trace['final_action']=copy.deepcopy(action)
            if stored:
                changed=s.execute(update(DialogueState).where(DialogueState.conversation_id==cid,DialogueState.revision==revision).values(revision=revision+1,message_seq=seq,state=json.dumps(state,ensure_ascii=False),updated_at=now()))
                if not changed.rowcount:
                    s.rollback()
                    return {'stale':True,'usage':usage,'message':'会话状态已更新，本次建议未覆盖'}
            else:s.add(DialogueState(conversation_id=cid,revision=revision+1,message_seq=seq,state=json.dumps(state,ensure_ascii=False)))
            profile=profile_projection(state)
            updated=s.execute(update(Conversation).where(Conversation.id==cid,Conversation.seq==seq,Conversation.locked==locked_snapshot,Conversation.status==conv.status,Conversation.stage==stage).values(analysis=json.dumps(profile,ensure_ascii=False),analysis_seq=seq))
            if not updated.rowcount:
                s.rollback()
                return {'stale':True,'usage':usage,'message':'对话或人工修正已变化，本次建议未覆盖'}
            saved=s.get(DialogueRun,run_id);saved.status='completed';saved.trace=json.dumps(trace,ensure_ascii=False);s.commit()
        return {'analysis':profile,'dialogue':state,'usage':usage,'seq':seq,'reply':action['reply'],'questions':profile['questions'],'recommendations':[o for o in state['options'] if o['id'] in action['option_ids']]}
    except Exception as error:
        if hasattr(error,'choice_trace'):trace['choices']=error.choice_trace
        with Session() as s:
            saved=s.get(DialogueRun,run_id)
            if saved:saved.status='failed';saved.trace=json.dumps({**trace,'error_type':type(error).__name__},ensure_ascii=False);s.commit()
        raise
    finally:sink.reset(trace_token)


def observe_sent(s,conv,message,action_id=''):
    row=s.get(DialogueState,conv.id)
    if not row:return
    state=json.loads(row.state);action=state.get('action') or {}
    candidate=next((c for c in action.get('candidates',[]) if c['id']==action_id),None)
    if candidate:action={**action,**candidate}
    if action_id and action_id==action.get('id') and action.get('message_seq')==message.seq-1:
        edited=message.content!=action.get('reply')
        question=action.get('question')
        if question and question['text'] in message.content:
            state['questions'].append({'id':message.id,'text':question['text'],'target':question['target'],'scope':question.get('scope','field'),'topic_key':question.get('topic_key',''),'seq':message.seq,'status':'asked'})
        if state.get('topic') and not question:state['topic']['status']='answered'
        normalized=re.sub(r'\s','',message.content);positions=[]
        card=json.loads(message.card or '{}')
        card_ids=[q['option_id'] for q in card.get('quotes',[])] if card.get('type')=='quote' else []
        card_skus={q['sku_ref'] for q in card.get('quotes',[])} if card.get('type')=='quote' else set()
        for task in state.get('tasks',[]):
            required=set(action.get('price_feedback',{}).get(task['id'],[]))
            if task.get('kind')=='verify' and task.get('status')=='completed' and task.get('verification',{}).get('kind')=='price' and required and required<=card_skus:
                task.update(feedback_status='sent',feedback_message_id=message.id,feedback_at=now())
        for oid in action.get('option_ids',[]):
            if oid in card_ids:
                positions.append((card_ids.index(oid),oid));continue
            option=next((o for o in state['options'] if o['id']==oid),None)
            marker=re.sub(r'\s','',option['name']+'，'+option['variant']) if option else ''
            if marker and marker in normalized:positions.append((normalized.index(marker),oid))
            elif option and any(q['option_id']==oid and q.get('sku_ref') and q['state']=='ready_for_review' for q in state['quotes']):
                sale_marker=re.sub(r'\s','',option['name']+'，'+option['variant'].replace('（销售组合待核实）',''))
                if sale_marker in normalized:positions.append((normalized.index(sale_marker),oid))
        if positions:
            delivered_ids=[oid for _,oid in sorted(positions)]
            state['presentations'].append({'message_id':message.id,'option_ids':delivered_ids,'seq':message.seq})
            card_levels={(q['option_id'],q.get('level','L1')) for q in card.get('quotes',[])}
            for quote in state['quotes']:
                if quote['state']=='ready_for_review' and (quote['option_id'],quote.get('level','L1')) in card_levels:
                    quote['delivery_status']='sent';quote['sent_message_id']=message.id
        from .service_tasks import observe_delivery
        observe_delivery(state,action,message.content,message.id,message.seq)
        state['sent_actions']=[*state.get('sent_actions',[]),{'action_id':action_id,'message_id':message.id,'edited':edited}][-50:]
        action['status']='sent';action['sent_message_id']=message.id
    # A real staff send, including an edited draft, supersedes the old proposed reply.
    state['action']={'id':uuid.uuid4().hex,'kind':'wait','reply':'','status':'waiting','message_seq':message.seq,'revision':row.revision+1}
    state['next_owner']=waiting_owner(state)
    state['revision']=row.revision+1;row.revision+=1;row.state=json.dumps(state,ensure_ascii=False);row.updated_at=now()


def check_send_action(s,conv,action_id,content=None):
    if not action_id:return {}
    row=s.get(DialogueState,conv.id)
    if not row:raise ValueError('建议已失效，请重新整理后发送')
    state=json.loads(row.state);action=state.get('action') or {}
    candidate_ids={c['id'] for c in action.get('candidates',[])}
    if action_id not in candidate_ids|{action.get('id')} or action.get('message_seq')!=conv.seq or action.get('kind') in {'review','wait'} or (action.get('kind')=='pause' and action_id not in candidate_ids):
        raise ValueError('对话已经更新，这条建议已失效，请重新整理')
    if state.get('goal')!='quote' or action.get('kind')!='quote':return {}
    active=[q for q in state.get('quotes',[]) if q['state']=='ready_for_review' and q['option_id'] in action.get('option_ids',[])]
    if active:
        if content is not None:
            from decimal import Decimal
            presented={Decimal(n.replace(',','')) for n in re.findall(r'[¥￥]\s*(\d[\d,]*(?:\.\d+)?)',content)}
            presented.update(Decimal(n.replace(',','')) for n in re.findall(r'(\d[\d,]*(?:\.\d+)?)\s*元',content))
            if not presented<={Decimal(q['total_minor'])/100 for q in active}:raise ValueError('报价金额已被改动，请先更新并复核价格规则')
        ids={q['option_id'] for q in active};options=[o for o in state['options'] if o['id'] in ids]
        current=prepare_quotes(options,active[0]['quantity'],conv.customer_id)
        by_level={(q['option_id'],q['level']):q for q in current}
        if any(not by_level.get((q['option_id'],q['level'])) or quote_signature([by_level[q['option_id'],q['level']]])!=quote_signature([q]) for q in active):
            raise ValueError('报价规则或有效期已变化，请重新核价')
        # Public, immutable quote snapshot. Private approvals and source records stay server-side.
        snapshots=[]
        for quote in active:
            option=next(o for o in options if o['id']==quote['option_id'])
            snapshot={k:quote[k] for k in ('option_id','level','sku_ref','quantity','unit_minor','fees_minor','total_minor','currency','valid_until')}
            snapshot.update(name=option['name'],variant=quote.get('variant',option['variant']).replace('（销售组合待核实）',''),tax_included=True,
                            deduction_minor=sum(step['deduction_minor'] for step in quote.get('steps',[])))
            if quote.get('components'):snapshot['components']=quote['components']
            if quote.get('is_demo'):snapshot['is_demo']=True
            snapshots.append(snapshot)
        return {'type':'quote','quotes':snapshots}
    return {}


def manual_change(s,conv):
    row=s.get(DialogueState,conv.id)
    if not row:return
    state=json.loads(row.state)
    state['needs']=fact_view(build_requirements(state['needs'],messages_for(s,conv.id),json.loads(conv.locked),conv.stage))
    state['constraints']=[x for x in state.get('constraints',[]) if x['field'] not in json.loads(conv.locked)]
    for quote in state['quotes']:quote['state']='invalidated'
    state['action']={'id':uuid.uuid4().hex,'kind':'review','reply':'','status':'needs_review','blockers':['人工修正后需要重新整理建议']}
    state['revision']=row.revision+1;row.revision+=1;row.state=json.dumps(state,ensure_ascii=False);row.updated_at=now()
    conv.analysis=json.dumps(profile_projection(state),ensure_ascii=False)


def status_change(s,conv):
    row=s.get(DialogueState,conv.id)
    if not row:return
    state=json.loads(row.state);terminal=conv.status=='closed' or conv.stage in {'已成交','暂不购买'}
    state['action']={'id':uuid.uuid4().hex,'kind':'pause' if terminal else 'review','reply':'','status':'paused' if terminal else 'needs_review'}
    state['revision']=row.revision+1;row.revision+=1;row.state=json.dumps(state,ensure_ascii=False);row.updated_at=now()
    conv.analysis=json.dumps(profile_projection(state),ensure_ascii=False)
