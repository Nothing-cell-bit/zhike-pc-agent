"""Continue the browser's isolated verification run with real-model customer replies."""
import asyncio,json,os,sys,time
from pathlib import Path
import httpx
from pydantic import BaseModel,Field

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
folder=Path((ROOT/'tmp/verification-live-current.txt').read_text(encoding='utf-8').strip()).resolve()
if not folder.is_relative_to(ROOT/'tmp'):raise RuntimeError('Not an isolated acceptance folder')
os.environ['STORE_DATA_DIR']=str(folder)
from backend import ai,model_settings
private_path=ROOT/'data/private/text-model.json'
if private_path.exists():
    private=json.loads(private_path.read_text(encoding='utf-8'))
    config=model_settings.ModelConfig(private['base_url'],private['model'],private['api_key'],'custom',private.get('disable_thinking',False))
else:config=model_settings.get_config()
ai.get_config=lambda:config
login=json.loads((folder/'login.json').read_text(encoding='utf-8'))
out=ROOT/'output/verification-flow-20261022';out.mkdir(parents=True,exist_ok=True)
BASE='http://127.0.0.1:8779/api'
HEADERS={'X-Store-Request':'1'}

class CustomerReply(BaseModel):reply:str=Field(min_length=1,max_length=250)

async def request(client,method,path,body=None):
    r=await client.request(method,BASE+path,json=body,headers=HEADERS);r.raise_for_status();return r.json()

async def main():
    report={'isolated':True,'model':config.model,'verification_data':'演示测试资料，不代表真实产品适配结论','steps':[],'passed':False}
    async with httpx.AsyncClient(timeout=60) as staff,httpx.AsyncClient(timeout=60) as customer:
        for client,name in [(staff,login['staff']),(customer,login['customer'])]:
            await request(client,'POST','/auth/login',{'username':name,'password':login['password']})
        cid=login['cid'];path='/conversations/'+cid
        detail=await request(staff,'GET',path)
        task=next(t for t in detail['dialogue']['tasks'] if t['id']==login['task_id'])
        assert task['status']=='completed' and task['feedback_status']=='sent' and task['feedback_message_id']
        assert not any(n.get('task_id')==task['id'] for n in await request(staff,'GET','/notifications'))
        report['steps'].append({'step':'浏览器发送核实反馈后，服务端确认已反馈且提醒移除','task':task})
        for turn in range(1,5):
            raw,_=await ai.model_json('你是本次隔离验收的模拟客户，只生成客户回复。按人物事实回答客服最后一个问题；不编造核实或测试事实，不替客服回答，不抢答尚未询问的事项。若客服询问购买安排，说明先比较配置。不提你是AI。输出reply。',
                {'persona':{'用途':'Blender 4.2 的小产品建模，Windows 11','复杂度':'十几万到几十万面，不用第三方插件，暂不做复杂渲染','预算':'8000元以内','关注':'视口操作流畅，先比较合适配置，不立即购买'},
                 'messages':[{'role':m['role'],'text':m['content']} for m in detail['messages']]},500,schema=CustomerReply)
            text=CustomerReply.model_validate(raw).reply
            sent=await request(customer,'POST',path+'/messages',{'content':text,'client_id':'verification-live-customer-'+str(turn)})
            report['steps'].append({'step':'真实 LLM 模拟客户回答','turn':turn,'text':text,'message_id':sent['id']})
            print('customer_turn='+str(turn),flush=True)
            deadline=time.monotonic()+300
            while time.monotonic()<deadline:
                await asyncio.sleep(1)
                detail=await request(staff,'GET',path)
                action=(detail.get('dialogue') or {}).get('action',{})
                if action.get('message_seq')==detail['seq'] and action.get('candidates'):break
                if detail.get('analysis_status') in {'failed','cancelled'}:
                    raise RuntimeError('Real analysis failed: '+detail.get('analysis_error',''))
            else:raise RuntimeError('Real analysis did not finish in 300 seconds')
            action=detail['dialogue']['action'];candidate=action['candidates'][0]
            assert candidate['reply'] and action['kind'] not in {'wait','review'}
            response=await request(staff,'POST',path+'/messages',{'content':candidate['reply'],'action_id':candidate['id'],'client_id':'verification-live-staff-'+str(turn)})
            report['steps'].append({'step':'真实客服 LLM 继续推进并实际发送','turn':turn,'kind':action['kind'],'reply':response['content'],
                                    'question':candidate.get('question'),'options':detail['dialogue'].get('options',[]),'action_id':candidate['id']})
            print('staff_turn='+str(turn)+' kind='+action['kind'],flush=True)
            report['passed']=action['kind'] in {'recommend','compare','quote'} or bool(action.get('option_ids'))
            (out/'actual-flow.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
            detail=await request(staff,'GET',path)
            if report['passed']:break
        report['final_detail']=detail
        report['passed']=report['passed'] and next(t for t in detail['dialogue']['tasks'] if t['id']==login['task_id'])['feedback_status']=='sent'
        (out/'actual-flow.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
        lines=['# 核实到反馈客户的实际验收记录','',f'验收时间：2026-10-22；模型：{config.model}。','',
               '本次使用隔离数据库。核实结果为明确标注的演示测试资料；核实后的客服回复及后续模拟客户回复均调用真实 LLM；前三条为预置的咨询场景。核实登记、采用及首条反馈在浏览器完成，后续对话通过同一网站 API 继续。','',
               '## 核实结果','',task['result'],'','## 完整对话','']
        for m in detail['messages']:lines.extend([('客户' if m['role']=='customer' else '客服')+'：'+m['content'],''])
        lines.extend(['## 实际状态','',f'- 原核实事项：{task["status"]}；客户反馈：{task["feedback_status"]}。',
                      '- 已发送反馈对应的真实消息 ID：'+task['feedback_message_id'],
                      '- 核实提醒已移除；保存或生成草稿本身不会标记已反馈。',
                      '- 后续实际推进并发送的动作：'+str(next((x.get('kind') for x in reversed(report['steps']) if x.get('kind')),''))+'；通过：'+str(report['passed'])+'。',
                      '- 本次未生成正式金额报价，具体销售 SKU 和门店价格仍需有效核价依据。',''])
        (out/'完整问答与核实流程.md').write_text('\n'.join(lines),encoding='utf-8')
        if not report['passed']:raise RuntimeError('No selection progress observed after four real turns')
        print('actual_flow_passed=True artifact='+str(out/'完整问答与核实流程.md'),flush=True)

if __name__=='__main__':asyncio.run(main())
