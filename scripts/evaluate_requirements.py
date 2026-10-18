"""Opt-in live evaluation with synthetic conversations; no production DB writes."""
import argparse
import asyncio
import json
import sys
import time
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.ai import extract_requirement_facts
from backend.requirements import build_requirements

CASES=[
 {'name':'rare_role_and_private_app','turns':[('customer','我做运输调度，主要录入运单和核对异常记录。预算6500元以内，必须运行公司自研的云栈客户端。担心天天背着太重。')],'contains':{'user':'运输调度','tasks':'运单','software':'云栈','budget':'6500'},'unknown':['next_step']},
 {'name':'correction_and_negation','turns':[('customer','我原来预算5000元，想买来玩游戏。'),('customer','改一下，我不玩游戏了，主要写代码和整理文档，预算改为8000元以内，要用Zed。')],'contains':{'tasks':'代码','software':'Zed','budget':'8000'},'absent':{'budget':'5000'},'unknown':['next_step']},
 {'name':'incomplete_information','turns':[('customer','我是档案修复员，想先了解一下你们的电脑。')],'contains':{'user':'档案修复员'},'unknown':['tasks','software','budget','next_step']},
 {'name':'named_game_then_list_closed','turns':[('customer','大二学生，换电脑，预算1w以内，主要玩3A游戏。'),('staff','具体玩什么游戏？还需要其他软件吗？'),('customer','黑猴'),('staff','除此之外还有其他软件吗？'),('customer','没有了')],'contains':{'software':'黑猴'},'absent':{'software':'没有了'},'known':['software'],'not_ask':['software']},
 {'name':'private_app_then_list_closed','turns':[('staff','必须运行什么软件？'),('customer','厂里的曜石终端'),('staff','还需要别的应用吗？'),('customer','就这一种')],'contains':{'software':'曜石终端'},'absent':{'software':'就这一种'},'known':['software'],'not_ask':['software']},
 {'name':'confirmed_budget_and_purpose','turns':[('customer','我用来整理档案，预算八千以内。'),('staff','最高八千元，对吗？'),('customer','对'),('staff','除了整理档案，还有其他用途吗？'),('customer','仅此而已')],'contains':{'tasks':'档案','budget':'八千'},'absent':{'tasks':'仅此而已','budget':'对'},'known':['tasks','budget']},
 {'name':'explicit_no_software_requirement','turns':[('customer','主要写文档，预算6000以内。'),('staff','有没有必须运行的特定软件？'),('customer','没有固定的软件要求')],'contains':{'software':'无指定'},'known':['software'],'not_ask':['software']},
 {'name':'retract_and_replace_application','turns':[('customer','需要青石客户端'),('staff','还运行其他程序吗？'),('customer','不用青石了，现在只用赤帆系统。')],'contains':{'software':'赤帆'},'absent':{'software':'青石'},'known':['software'],'not_ask':['software']},
]

async def run():
    output=[]
    for case in CASES:
        messages=[{'id':str(i),'seq':i,'role':role,'text':text} for i,(role,text) in enumerate(case['turns'],1)]
        try:
            started=time.monotonic()
            raw,usage=await extract_requirement_facts(messages)
            result=build_requirements(raw,messages)
            checks={**{f'{k}_contains':v in result[k]['value'] for k,v in case.get('contains',{}).items()},**{f'{k}_absent':v not in result[k]['value'] for k,v in case.get('absent',{}).items()},**{f'{k}_unknown':result[k]['status']=='unknown' for k in case.get('unknown',[])}}
            checks.update({f'{k}_known':result[k]['status']=='known' for k in case.get('known',[])})
            checks.update({f'{k}_not_asked':result['next_question']['field']!=k for k in case.get('not_ask',[])})
            item={'name':case['name'],'passed':all(checks.values()),'checks':checks,'result':result,'usage':usage,'seconds':round(time.monotonic()-started,2)}
        except Exception as error:item={'name':case['name'],'passed':False,'error':type(error).__name__+': '+str(error)}
        output.append(item)
        folder=ROOT/'tmp'/'requirements-generalization';folder.mkdir(exist_ok=True,parents=True)
        (folder/'live-evaluation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'name':item['name'],'passed':item['passed'],'seconds':item.get('seconds'),'checks':item.get('checks'),'error':item.get('error')},ensure_ascii=False),flush=True)
    return all(item['passed'] for item in output)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('真实模型调用需显式使用 --live；测试仅包含虚构对话。')
    sys.stdout.reconfigure(encoding='utf-8');sys.exit(0 if asyncio.run(run()) else 1)
