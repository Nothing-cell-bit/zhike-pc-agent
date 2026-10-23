"""Real LLM customer, unchanged reception workflow, isolated database, verbatim Markdown."""
import argparse
import asyncio
import json
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path

from evaluate_natural_dialogue import ROOT,ai,Session,Conversation,Message
from backend import dialogue
from backend.config import DATA
from backend.db import DialogueRun,PriceRule
from backend.model_settings import get_config
from pydantic import BaseModel,Field
from sqlalchemy import select,func


class Persona(BaseModel):
    background:str
    primary_use:str
    games_or_software:list[str]=Field(min_length=1,max_length=5)
    budget_cny:int=Field(ge=10000,le=40000)
    priorities:list[str]=Field(min_length=1,max_length=4)
    constraints:list[str]=Field(max_length=4)
    willing_to_compare:bool
    purchase_timing:str
    opening_message:str=Field(min_length=1,max_length=500)


class CustomerTurn(BaseModel):
    message:str=Field(min_length=1,max_length=600)
    done:bool
    reason:str=Field(max_length=200)


CUSTOMER_POLICY='''你只扮演一名普通购机客户，不扮演客服、测试员、规划器或管理员。你的真实需求由persona给定，保持一致，不能为了配合系统随意改变预算、游戏或顾虑。
只依据可见对话回复，不知道客服内部状态、知识库、价格规则、任务或候选。自然回答客服刚问的问题，一般一两句；不一次倾倒所有需求，不反复机械回复ok。客服没有提问时，可以根据真实购买目标自然问下一步，包括比较、配置和价格。
目标是了解适合自己的具体方案，并请客服给出报价。愿意比较时，只有在客服确实提出或解释后再接受具体替代方案；只确认实际出现的产品或配置，不凭空替客服推荐。不能编造优惠资格、核实结果或价格，不命令客服绕过核验。
当关键需求已经说清，可以直接要求具体配置和报价；在此之前继续回答合理问题。客服如果明确说明实际售价缺失，可以接受待核价并询问后续安排。不要在尚未进入报价讨论时无缘无故结束。done只表示你确实想结束当前咨询，不代表系统已完成报价。
返回规定JSON，message是客户原话；reason是你的角色判断，不属于对话。不要在message里出现内部字段、测试术语或阶段编号。'''


def append(cid,role,text,action_id=''):
    with Session() as session:
        conv=session.get(Conversation,cid)
        card=dialogue.check_send_action(session,conv,action_id,text) if role=='staff' and action_id else {}
        conv.seq+=1
        message=Message(conversation_id=cid,sender_id='simulation-'+role,role=role,content=text,
                        card=json.dumps(card,ensure_ascii=False),seq=conv.seq,client_id=uuid.uuid4().hex)
        session.add(message);session.flush()
        if role=='staff':dialogue.observe_sent(session,conv,message,action_id)
        session.commit()
        return {'role':role,'text':text,'seq':message.seq,'card':card}


def write_artifacts(folder,report):
    (folder/'run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    status={'running':'模拟进行中','formal_quote':'已生成并模拟发送报价卡（演示数据见标注）','quote_pending':'已进入报价环节，实际金额待核实',
            'customer_stopped':'模拟客户结束了咨询','turn_limit':'达到轮次上限，未完成报价','failed':'系统分析未完成，保留实际记录'}[report['status']]
    lines=['# 从产品咨询到报价：LLM 客户模拟问答','',f"生成时间：{report['started_at']}（北京时间）",'',
           '> 客户开场和全部回答均由独立客户角色的 LLM 生成；客服使用现有接待流程，每轮原样采用第一条有效建议。',
           ('> 在隔离数据库运行；用户授权生成演示报价规则，所有金额都是演示测试数据，未写入正式报价库，也未虚构性能核实结果。' if report.get('demo_pricing') else '> 在隔离数据库运行；未修改业务代码、真实聊天、门店核实结果或报价规则。'),
           '',f'**运行结果：{status}。**','', '## 实际问答','']
    for entry in report['transcript']:
        if entry['role']=='system':
            lines.extend(['*运行记录：'+entry['text']+'*','']);continue
        lines.extend(['**'+('客户' if entry['role']=='customer' else '客服')+'：**','',entry['text'],''])
        if entry.get('card',{}).get('type')=='quote':
            for quote in entry['card']['quotes']:
                lines.extend([f"> {'【演示测试，非门店售价】' if quote.get('is_demo') else ''}报价卡：{quote['name']} · {quote['variant']} · {quote['level']} · {quote['quantity']}台 · 合计 ¥{quote['total_minor']/100:.2f}",''])
    lines.extend(['## 报价与核实结果','',f"- 隔离库门店价格规则：{report.get('price_rule_count',0)} 条。",
                  ('【演示测试】本次使用用户授权的模拟规则，金额不是门店售价。' if report.get('demo_pricing') else '- 未录入、批准或虚构任何价格规则；历史参考价不能视为正式报价。')])
    state=report.get('last_state') or {}
    for quote in state.get('quotes',[]):
        lines.append('- '+quote.get('level','')+' · '+str(quote.get('variant',''))+' · 状态：'+quote.get('state','')+
                     (' · 合计 ¥'+format(quote['total_minor']/100,'.2f') if quote.get('total_minor') is not None else ' · 无确定金额'))
    pending=[task for task in state.get('tasks',[]) if task.get('kind')=='verify' and task.get('status') not in {'completed','cancelled'}]
    for task in pending:lines.append('- 待门店核实：'+task['title'])
    if report.get('error'):lines.extend(['', '运行异常：'+report['error']])
    lines.extend(['','## 执行说明','',f"- 客户模型：{report.get('model','现有文本模型')}；客服模型：网站现有配置。",
                  '- 客户角色只看到自己的设定及实际聊天，不读取客服内部规划。',
                  '- 选择客服第一条有效建议属于模拟点击采用/发送；没有另写、改写客服回复。',
                  '- 完整机器记录、客户设定和逐轮追踪保存在本目录；本文对话未润色。',''])
    (folder/'问答.md').write_text('\n'.join(lines),encoding='utf-8')


async def run(max_turns,demo_pricing=False,persona_path=None,persona_brief=None):
    folder=ROOT/'output'/('llm-customer-simulation-'+datetime.now().strftime('%Y%m%d-%H%M%S'))
    folder.mkdir(parents=True)
    report={'started_at':datetime.now().isoformat(timespec='seconds'),'status':'running','model':get_config().model,
            'isolated_database':str(DATA/'store.db'),'transcript':[],'turns':[]}
    report['demo_pricing']=demo_pricing
    if demo_pricing:
        from demo_price_fixture import seed_demo_prices
        await seed_demo_prices(ROOT,folder)
    with Session() as session:report['price_rule_count']=session.scalar(select(func.count()).select_from(PriceRule))
    write_artifacts(folder,report)
    print('ARTIFACT '+str(folder/'问答.md'),flush=True)
    if persona_path:
        persona_raw=json.loads(Path(persona_path).read_text(encoding='utf-8'))
        report['persona_source']=str(Path(persona_path).resolve())
    else:
        brief=persona_brief or '最初对 HUAWEI MateBook Fold 非凡大师 感兴趣；主要想玩3A游戏，预算约3万元，可根据合理解释比较其他电脑。'
        report['persona_brief']=brief
        persona_raw,_=await ai.model_json(
        '生成一个虚构但自然的电脑购机客户设定和首句询问。'+brief+
        '具体游戏、个人背景、偏好和限制由你生成，要相互一致。此人想最终拿到明确配置和报价，购买一台；不要编造具体商品售价。'
        'opening_message只作自然初次咨询，不一次透露全部画像；所有内容只供隔离模拟，不冒充真实客户。',
            {},900,schema=Persona,system_prompt='',structured_output=True,compact_schema=True,request_timeout=60)
    persona=Persona.model_validate(persona_raw).model_dump()
    (folder/'客户设定.json').write_text(json.dumps(persona,ensure_ascii=False,indent=2),encoding='utf-8')
    with Session() as session:
        conversation=Conversation(customer_id='simulation-customer',customer_name='LLM模拟客户（隔离）',owner_id='simulation-staff',status='active')
        session.add(conversation);session.commit();cid=conversation.id
    report['conversation_id']=cid
    no_reply=False
    try:
        for number in range(1,max_turns+1):
            if number==1:
                customer={'message':persona['opening_message'],'done':False,'reason':'LLM生成的首次咨询'}
            else:
                raw,usage=await ai.model_json(CUSTOMER_POLICY,
                    {'persona':persona,'conversation':[{'role':m['role'],'text':m['text']} for m in report['transcript'] if m['role']!='system'],
                     'last_service_turn_had_no_message':no_reply},
                    650,schema=CustomerTurn,system_prompt='',structured_output=True,compact_schema=True,request_timeout=60)
                customer=CustomerTurn.model_validate(raw).model_dump()
            entry=append(cid,'customer',customer['message']);report['transcript'].append(entry)
            turn={'number':number,'customer':customer,'started':time.time()};report['turns'].append(turn)
            print(json.dumps({'turn':number,'customer':customer['message']},ensure_ascii=False),flush=True)
            write_artifacts(folder,report)
            if customer['done']:
                report['status']='customer_stopped';break
            result=None
            for attempt in range(2):
                try:
                    result=await ai.analysis(cid);break
                except Exception as error:
                    turn.setdefault('analysis_errors',[]).append(type(error).__name__+': '+str(error))
                    print(json.dumps({'turn':number,'analysis_error':str(error),'retry':attempt==0},ensure_ascii=False),flush=True)
                    if attempt==1:raise
            with Session() as session:
                row=session.scalar(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at.desc()).limit(1))
                trace=json.loads(row.trace)
            (folder/f'{number:02d}-客服追踪.json').write_text(json.dumps(trace,ensure_ascii=False,indent=2),encoding='utf-8')
            if result.get('stale'):raise ValueError('隔离模拟收到过期结果')
            state=result['dialogue'];report['last_state']=state
            action=state['action'];choices=action.get('candidates') or []
            chosen=choices[0] if choices else action
            text=chosen.get('reply','')
            turn.update(goal=state.get('goal'),action=action['kind'],seconds=round(time.time()-turn['started'],2),
                        customer_needs=state.get('needs'),quotes=state.get('quotes',[]))
            if text:
                entry=append(cid,'staff',text,chosen['id']);report['transcript'].append(entry)
                report['last_state']=dialogue.view(cid)
                turn['staff']=text;no_reply=False
                print(json.dumps({'turn':number,'staff':text,'goal':state.get('goal'),'action':action['kind']},ensure_ascii=False),flush=True)
                if entry['card'].get('type')=='quote':report['status']='formal_quote';break
                if state.get('goal')=='quote' and state.get('quotes'):
                    report['status']='quote_pending';break
            else:
                no_reply=True
                report['transcript'].append({'role':'system','text':'本轮系统未给出客服可发送回复；状态为'+action['kind']+'，由客户角色自行决定如何继续。'})
                print(json.dumps({'turn':number,'staff_message':None,'action':action['kind'],'goal':state.get('goal')},ensure_ascii=False),flush=True)
            write_artifacts(folder,report)
        else:report['status']='turn_limit'
    except Exception as error:
        report.update(status='failed',error=type(error).__name__+': '+str(error))
        print('SIMULATION_ERROR '+report['error'],flush=True)
    finally:
        with Session() as session:
            rows=session.scalars(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at)).all()
            attempts=[{'id':row.id,'status':row.status,'trace':json.loads(row.trace)} for row in rows]
        (folder/'全部分析尝试.json').write_text(json.dumps(attempts,ensure_ascii=False,indent=2),encoding='utf-8')
        write_artifacts(folder,report)
    print('RESULT '+json.dumps({'status':report['status'],'markdown':str(folder/'问答.md'),'customer_turns':len(report['turns'])},ensure_ascii=False),flush=True)
    return report


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--live',action='store_true')
    parser.add_argument('--max-turns',type=int,default=16)
    parser.add_argument('--demo-pricing',action='store_true',help='仅隔离库：使用用户授权的演示价格，全部标注测试数据')
    parser.add_argument('--persona',help='复用此前LLM生成的客户设定，所有后续回答仍由客户LLM即时生成')
    parser.add_argument('--persona-brief',help='客户情景范围；具体画像、开场及后续回答仍由LLM生成，不提供客服话术')
    args=parser.parse_args()
    if not args.live:parser.error('--live is required for real LLM calls')
    if not 1<=args.max_turns<=24:parser.error('max-turns must be 1..24')
    sys.stdout.reconfigure(encoding='utf-8')
    if args.persona and args.persona_brief:parser.error('persona and persona-brief are mutually exclusive')
    asyncio.run(run(args.max_turns,args.demo_pricing,args.persona,args.persona_brief))
