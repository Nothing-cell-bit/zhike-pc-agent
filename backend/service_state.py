"""Project one grounded answer ledger into requirement and work progress."""
import copy
import re
from . import dialogue as d
from .dialogue_contract import NEED_KEYS
from .requirements import REQUIREMENT_FIELDS,_display
from .service_tasks import refresh_tasks,task_key


def separate_fact_clauses(changes):
    """Resolve nested spans at source punctuation; never invent field vocabulary."""
    result=copy.deepcopy(changes)
    for change in result:
        quotes=[]
        for quote in change['fact'].get('quotes',[]):
            if quote.get('kind','fact')!='fact':
                quotes.append(quote);continue
            other=[q['quote'] for item in changes if item['field']!=change['field'] for q in item['fact'].get('quotes',[])
                   if q.get('kind','fact')=='fact' and q['message_id']==quote['message_id'] and q['quote']!=quote['quote'] and q['quote'] in quote['quote']]
            clauses=[part.strip() for part in re.split(r'[，,。；;！？?!\n]+',quote['quote']) if part.strip()]
            remaining=[part for part in clauses if not any(span in part for span in other)]
            if other and remaining and len(remaining)<len(clauses):
                quotes.extend({**quote,'quote':part} for part in remaining)
            else:quotes.append(quote)
        change['fact']['quotes']=quotes[-6:]
    return result


def question_field(question,tasks):
    key=d.question_key(question)
    if question.get('scope','field')=='field' and key in REQUIREMENT_FIELDS:return key
    task=next((t for t in tasks if t['kind']=='discover' and task_key(t)==key),None)
    return NEED_KEYS.get(task.get('target'),task.get('target')) if task else None


def synchronize_progress(state,messages):
    """No model inference: only admitted facts and explicit grounded resolutions."""
    messages_by_id={m['id']:m for m in messages}
    tasks=state.get('tasks',[])
    for question in state.get('questions',[]):
        field=question_field(question,tasks)
        need=state.get('needs',{}).get(field,{})
        if question.get('status') not in {'asked','partial'} or question.get('scope','field')!='field':continue
        if need.get('manual') or need.get('status') not in {'known','partial'}:continue
        answers=[quote for quote in need.get('quotes',[]) if quote.get('kind','fact')=='fact'
                 and d.valid_evidence(quote,messages)
                 and messages_by_id[quote['message_id']]['seq']>question.get('seq',0)]
        if answers:
            quote=max(answers,key=lambda q:messages_by_id[q['message_id']]['seq'])
            question.update(status='answered',answer={k:quote[k] for k in ('message_id','quote')})
    # Keep the question with its elliptical answer. Never infer a unit, software
    # identity or preference from a number or a bare yes/no in isolation.
    for field,need in state.get('needs',{}).items():
        if not isinstance(need,dict) or need.get('manual'):continue
        details=[]
        for question in state.get('questions',[]):
            answer=question.get('answer')
            if question.get('scope')!='detail' or question.get('status') not in {'answered','partial'}:continue
            if question_field(question,tasks)!=field or not d.valid_evidence(answer,messages):continue
            if not any(q['message_id']==answer['message_id'] and q['quote']==answer['quote'] for q in need.get('quotes',[])):continue
            details.append({'question_id':question['id'],'question':question.get('text',''),
                            'label':question.get('target') or question.get('text',''),'answer':answer['quote'],'message_id':answer['message_id']})
        if details:
            contextual={(x['message_id'],x['answer']) for x in details}
            facts=[q for q in need.get('quotes',[]) if (q['message_id'],q['quote']) not in contextual]
            base=_display(field,facts) if facts else ''
            need['value']='；'.join(([base] if base else [])+[x['label']+'：'+x['answer'] for x in details])
            need['details']=details
    if 'summary' in state.get('needs',{}):
        state['needs']['summary']='；'.join(label+'：'+state['needs'][field]['value'] for field,label in REQUIREMENT_FIELDS.items()
                                            if state['needs'].get(field,{}).get('status') in {'known','partial'})
    refresh_tasks(state)
