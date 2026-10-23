"""Opt-in full multi-turn LLM acceptance in an isolated DB; never sends real messages."""
import argparse
import asyncio
import json
import os
import sys
import tempfile
import time
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
os.environ['STORE_DATA_DIR']=tempfile.mkdtemp(prefix='dialogue-live-')
from backend import knowledge as kb,dialogue_catalog
kb.INDEX=ROOT/'data'/'knowledge'/'index.db'
dialogue_catalog.CACHE_ROOT=ROOT/'data'/'ima'
from backend.db import init_db,Session,Conversation,Message,DialogueRun
from backend import ai
from backend.dialogue import observe_sent
init_db()


def append(cid,role,text,action_id=''):
    with Session() as s:
        c=s.get(Conversation,cid);c.seq+=1
        m=Message(conversation_id=cid,sender_id='synthetic-'+role,role=role,content=text,client_id=cid+'-'+str(c.seq),seq=c.seq)
        s.add(m);s.flush()
        if role=='staff':observe_sent(s,c,m,action_id)
        s.commit()


async def turn(cid,text,history):
    append(cid,'customer',text);started=time.monotonic()
    result=await ai.analysis(cid)
    state=result['dialogue'];action=state['action']
    history.append({'customer':text,'seconds':round(time.monotonic()-started,2),'action':action,'needs':state['needs'],'options':state['options'],'selection':state['selection'],'questions':state['questions'],'quotes':state['quotes'],'usage':result['usage']})
    print(json.dumps({'turn':len(history),'action':action['kind'],'reply':action['reply'],'blockers':action.get('blockers'),'seconds':history[-1]['seconds']},ensure_ascii=False),flush=True)
    if action['reply']:append(cid,'staff',action['reply'],action['id'])
    return state


async def run(case_name='all'):
    results=[]
    cases=['delegated_selection','delegated_best','unfamiliar_software','correction_and_pause'] if case_name=='all' else [case_name]
    for name in cases:
        with Session() as s:
            c=Conversation(customer_id='synthetic-customer',customer_name='多轮验收（隔离）',owner_id='synthetic-staff');s.add(c);s.commit();cid=c.id
        history=[];checks={}
        try:
            if name in {'delegated_selection','delegated_best'}:
                initial=await turn(cid,'我想了解HUAWEI MateBook 14 酷睿 Ultra，主要学习、写代码，用Codex这类工具，预算1万元以内。',history)
                checks['no_inquiry_in_purchase_intent']=initial['needs']['progress']['status']=='unknown'
                state=await turn(cid,'给我最好的' if name=='delegated_best' else '配置我不太懂，你按我的用途和预算帮我选吧。',history)
                checks['delegation_advances']=state['action']['kind'] in {'recommend','compare','inform'} and bool(state['action']['option_ids']) and bool(state['delegation'])
                checks['not_prematurely_confirmed']=state['selection']['status']=='unconfirmed'
                count=len(state['action']['option_ids'])
                state=await turn(cid,'就第二套，帮我报价吧。' if count>=2 else '就你推荐的这一套，帮我报价吧。',history)
                checks['selection_resolved']=state['selection']['status']=='confirmed'
                checks['quote_prepared']=bool(state['quotes']) and state['goal']=='quote' and state['action']['kind'] in {'quote','inform'}
                checks['no_invented_store_price']=all(q['total_minor'] is None for q in state['quotes'])
            elif name=='unfamiliar_software':
                initial=await turn(cid,'我做档案修复，需要运行单位自研的曜石终端，主要整理影像资料。',history)
                checks['software_not_purchase_plan']=initial['needs']['progress']['status']=='unknown'
                state=await turn(cid,'预算八千以内，职业身份我就不再细说了，配置你给我推荐。',history)
                checks['unknown_name_preserved']='曜石' in state['needs']['software']['value']
                checks['does_not_require_full_profile']=state['action']['kind'] in {'recommend','compare','inform'}
                state=await turn(cid,'预算改到6000元以内，其他需求不变。',history)
                checks['budget_corrected']='6000' in state['needs']['budget']['value']
                checks['software_retained']='曜石' in state['needs']['software']['value']
                checks['continues_after_budget_change']=state['action']['kind'] in {'recommend','compare','inform'} and bool(state['action']['reply'])
            else:
                await turn(cid,'我帮家里人买电脑，主要写文档，不玩游戏，预算7000元以内。',history)
                state=await turn(cid,'不是帮别人了，是我自己用，预算还是7000元以内。',history)
                checks['latest_intention_used']=state['needs']['progress'].get('intent_mode')!='for_other'
                state=await turn(cid,'我暂时不买了，不用继续推荐。',history)
                checks['pause_respected']=state['action']['kind']=='pause'
                checks['purchase_deferred']=state['needs']['progress'].get('intent_mode')=='defer'
            results.append({'name':name,'passed':all(checks.values()),'checks':checks,'turns':history})
        except Exception as error:results.append({'name':name,'passed':False,'error':type(error).__name__+': '+str(error),'turns':history})
        folder=ROOT/'tmp'/'dialogue-acceptance';folder.mkdir(parents=True,exist_ok=True)
        (folder/'live-results.json').write_text(json.dumps(results,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'case':name,'passed':results[-1]['passed'],'checks':checks,'error':results[-1].get('error')},ensure_ascii=False),flush=True)
    return all(x['passed'] for x in results)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');parser.add_argument('--case',default='all');args=parser.parse_args()
    if not args.live:parser.error('真实调用需显式指定 --live；仅使用虚构对话和隔离数据库。')
    sys.stdout.reconfigure(encoding='utf-8');sys.exit(0 if asyncio.run(run(args.case)) else 1)
