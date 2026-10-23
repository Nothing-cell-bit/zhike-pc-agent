"""Real-model customer and reception, through local HTTP routes; pause before final quote send."""
import asyncio,json,os,sys,time,uuid
from pathlib import Path
from datetime import datetime,timezone,timedelta
import httpx
from pydantic import BaseModel,Field

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
folder=Path((ROOT/'tmp/quote-demo-current.txt').read_text(encoding='utf-8').strip()).resolve()
if not folder.is_relative_to(ROOT/'tmp'):raise RuntimeError('Expected isolated demo folder')
os.environ['STORE_DATA_DIR']=str(folder)
from backend import ai,model_settings
vpath=ROOT/'data/private/text-model.json'
if vpath.exists():
    v=json.loads(vpath.read_text(encoding='utf-8'));config=model_settings.ModelConfig(v['base_url'],v['model'],v['api_key'],'custom',v.get('disable_thinking',False))
else:config=model_settings.get_config()
ai.get_config=lambda:config
login=json.loads((folder/'login.json').read_text(encoding='utf-8'))
OUT=ROOT/'output/quote-full-chain-20261022';OUT.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8780/api';HEADERS={'X-Store-Request':'1'}

class Persona(BaseModel):
    background:str
    needs:str
    preferences:str
    opening:str=Field(min_length=1,max_length=300)

class Reply(BaseModel):message:str=Field(min_length=1,max_length=400)

async def req(c,method,path,body=None):
    r=await c.request(method,BASE+path,json=body,headers=HEADERS);r.raise_for_status();return r.json()

def save(report,detail):
    report['final_detail']=detail
    (OUT/'actual-run.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    lines=['# 从咨询到报价：真实 LLM 完整问答','',report['started_at']+'（北京时间）','',
        '独立演示库，所有价格和销售 SKU 均为演示测试数据。客户开场、后续回答及客服话术均由真实 LLM 生成；客服走网站现有分析、采用、发送和报价卡接口。',
        '', '## 当前结果','',report['status'],'','## 完整问答','']
    for m in detail.get('messages',[]):
        lines.extend(['**'+('客户' if m['role']=='customer' else '客服')+'：**', '',m['content'],''])
        card=m.get('card') or {}
        for q in card.get('quotes',[]):lines.extend([f'> 【演示测试，非门店售价】{q["level"]} · {q["variant"]} · {q["quantity"]} 台 · 应付 ¥{q["total_minor"]/100:.2f}',''])
    price_tasks=[t for t in detail.get('dialogue',{}).get('tasks',[]) if t.get('verification',{}).get('kind')=='price']
    if price_tasks:
        lines.extend(['## 页面中的价格核实与反馈',''])
        for task in price_tasks:lines.extend([task['title'], '',task['result'],'', '反馈状态：'+task.get('feedback_status','pending')+'；对应消息：'+task.get('feedback_message_id','未发送'),''])
    lines.extend(['## 核对结果','',json.dumps(report.get('checks',{}),ensure_ascii=False,indent=2),'','演示规则见同目录《演示四级报价规则.md》。'])
    (OUT/'完整问答.md').write_text('\n'.join(lines),encoding='utf-8')

async def main():
    report={'started_at':datetime.now(timezone(timedelta(hours=8))).isoformat(timespec='seconds'),'model':config.model,'status':'进行中','turns':[],'checks':{}}
    path='/conversations/'+login['cid']
    async with httpx.AsyncClient(timeout=60) as staff,httpx.AsyncClient(timeout=60) as customer,httpx.AsyncClient(timeout=60) as reviewer:
        for c,name in [(staff,login['staff']),(customer,login['customer']),(reviewer,login['reviewer'])]:await req(c,'POST','/auth/login',{'username':name,'password':login['password']})
        if '--new-conversation' in sys.argv:
            created=await req(customer,'POST','/conversations',{})
            login['cid']=created['id'];path='/conversations/'+login['cid']
            await req(staff,'POST',path+'/claim',{})
            (folder/'login.json').write_text(json.dumps(login),encoding='utf-8')
        if '--finalize' in sys.argv:
            report=json.loads((OUT/'actual-run.json').read_text(encoding='utf-8'));detail=await req(staff,'GET',path)
            cards=[m['card'] for m in detail['messages'] if m.get('card',{}).get('type')=='quote']
            assert cards and all(q.get('is_demo') for card in cards for q in card['quotes'])
            assert all(q['level']!='L4' for card in cards for q in card['quotes'])
            pending=[t for t in detail['dialogue'].get('tasks',[]) if t['kind']=='verify' and t['status'] not in {'completed','cancelled'}]
            assert detail['dialogue']['next_owner']==('staff' if pending else 'customer')
            price_tasks=[t for t in detail['dialogue'].get('tasks',[]) if t.get('verification',{}).get('kind')=='price']
            assert all(t.get('feedback_status')=='sent' for t in price_tasks)
            assert all(q.get('delivery_status')=='sent' for q in detail['dialogue']['quotes'] if q['state']=='ready_for_review')
            report['status']='已在浏览器实际发送演示报价卡'
            report['checks'].update(quote_card_sent=True,demo_marked=True,unapproved_special_not_sent=True,
                price_verification_feedback_sent=bool(price_tasks) and all(t.get('feedback_status')=='sent' for t in price_tasks),
                after_send_owner=detail['dialogue']['next_owner'],remaining_verification=[t['title'] for t in pending])
            save(report,detail);print('COMPLETE '+str(OUT/'完整问答.md'));return
        raw,_=await ai.model_json('生成一名虚构普通购机客户和自然开场。目标仅考虑 MateBook D 16 2024，允许比较的CPU配置仅为i5-13420H和i9-13900H，不自行增加其他型号；用途以文档、网页、多任务和视频会议为主，不玩游戏，不要求未知软件性能承诺；预算8000元以内，买1台，本周考虑购买，Windows 11、16GB、1TB都可以，不需要配件或优惠资格。开场只询问这台电脑是否适合自己的办公/会议场景，禁止第一句直接问价格或确认具体配置；后续仍应按购买目标逐步问到价格。不一次倾倒全部画像，不知道报价规则或测试流程。',{},700,schema=Persona)
        persona=Persona.model_validate(raw).model_dump();(OUT/'LLM客户设定.json').write_text(json.dumps(persona,ensure_ascii=False,indent=2),encoding='utf-8')
        # Check rule gates before interviewing. This review is explicitly demo-only.
        rules=await req(reviewer,'GET','/admin/price-rules');assert len(rules)==8
        report['checks']['four_levels_seeded']=True
        for turn in range(1,13):
            detail=await req(staff,'GET',path)
            if turn==1:text=persona['opening']
            else:
                raw,_=await ai.model_json('你只扮演该购机客户，用一两句回答最后的客服问题。只看persona和实际聊天，不知道后台状态。保持8000以内、1台、仅比较D16的两种CPU配置、Windows 11、16GB/1TB即可、不需要配件、无优惠资格的偏好。客服提出可选配置后按自己的需求明确选一套；需求已说清时主动要报价，不机械回复ok，不为了迎合客服改变需求。不能自造价格、优惠资格或测试结论。输出message。',
                    {'persona':persona,'conversation':[{'role':m['role'],'content':m['content']} for m in detail['messages']]},500,schema=Reply)
                text=Reply.model_validate(raw).message
            await req(customer,'POST',path+'/messages',{'content':text,'client_id':uuid.uuid4().hex})
            job=await req(staff,'POST',path+'/ai/analysis',{})
            print('customer_turn='+str(turn),flush=True)
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                await asyncio.sleep(1)
                j=await req(staff,'GET','/jobs/'+job['job_id'])
                if j['status']=='completed':break
                if j['status'] in {'failed','cancelled'}:raise RuntimeError('Analysis failed: '+j.get('error',''))
            else:raise RuntimeError('Analysis timed out')
            detail=await req(staff,'GET',path);state=detail['dialogue'];action=state['action'];candidates=action.get('candidates') or []
            if not candidates:raise RuntimeError('No usable customer response at turn '+str(turn))
            candidate=candidates[0]
            report['turns'].append({'turn':turn,'customer':text,'action':action['kind'],'goal':state['goal'],'reply':candidate['reply']})
            save(report,detail)
            print('staff_turn='+str(turn)+' action='+action['kind'],flush=True)
            if action['kind']=='quote' and state['goal']=='quote' and any(q['state']=='ready_for_review' for q in state['quotes']):
                levels={q['level']:q for q in state['quotes']}
                assert levels['L2']['state']=='needs_qualification' and levels['L4']['state']=='needs_approval'
                assert levels['L2']['total_minor'] is None and levels['L4']['total_minor'] is None
                report['checks'].update(qualification_gate=True,approval_gate=True,amounts_computed=True,quote_not_automatically_sent=True)
                report['status']='报价已生成，等待浏览器采用并发送'
                save(report,detail);print('READY_FOR_BROWSER '+str(OUT/'完整问答.md'),flush=True);return
            await req(staff,'POST',path+'/messages',{'content':candidate['reply'],'action_id':candidate['id'],'client_id':uuid.uuid4().hex})
            detail=await req(staff,'GET',path)
            assert not any(m.get('card',{}).get('type')=='quote' for m in detail['messages'])
            report['checks']['no_early_quote_card']=True;save(report,detail)
        raise RuntimeError('No formal quote after twelve natural customer turns')

if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(main())
