"""Opt-in live evaluation with synthetic conversations; no production DB writes."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.ai import extract_requirement_facts
from backend.requirements import build_requirements

CASES=[
 {'name':'rare_role_and_private_app','turns':[('customer','我做运输调度，主要录入运单和核对异常记录。预算6500元以内，必须运行公司自研的云栈客户端。担心天天背着太重。')],'contains':{'user':'运输调度','tasks':'运单','software':'云栈','budget':'6500'},'unknown':['next_step']},
 {'name':'correction_and_negation','turns':[('customer','我原来预算5000元，想买来玩游戏。'),('customer','改一下，我不玩游戏了，主要写代码和整理文档，预算改为8000元以内，要用Zed。')],'contains':{'tasks':'代码','software':'Zed','budget':'8000'},'absent':{'budget':'5000'},'unknown':['next_step']},
 {'name':'incomplete_information','turns':[('customer','我是档案修复员，想先了解一下你们的电脑。')],'contains':{'user':'档案修复员'},'unknown':['tasks','software','budget','next_step']},
]

async def run():
    output=[]
    for case in CASES:
        messages=[{'id':str(i),'seq':i,'role':role,'text':text} for i,(role,text) in enumerate(case['turns'],1)]
        try:
            raw,usage=await extract_requirement_facts(messages)
            result=build_requirements(raw,messages)
            checks={**{f'{k}_contains':v in result[k]['value'] for k,v in case.get('contains',{}).items()},**{f'{k}_absent':v not in result[k]['value'] for k,v in case.get('absent',{}).items()},**{f'{k}_unknown':result[k]['status']=='unknown' for k in case.get('unknown',[])}}
            item={'name':case['name'],'passed':all(checks.values()),'checks':checks,'result':result,'usage':usage}
        except Exception as error:item={'name':case['name'],'passed':False,'error':type(error).__name__+': '+str(error)}
        output.append(item)
        folder=ROOT/'tmp'/'requirements-generalization';folder.mkdir(exist_ok=True,parents=True)
        (folder/'live-evaluation.json').write_text(json.dumps(output,ensure_ascii=False,indent=2),encoding='utf-8')
        print(json.dumps({'name':item['name'],'passed':item['passed'],'checks':item.get('checks'),'error':item.get('error')},ensure_ascii=False),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('真实模型调用需显式使用 --live；测试仅包含虚构对话。')
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(run())
