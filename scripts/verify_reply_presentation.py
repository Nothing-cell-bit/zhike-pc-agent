"""Replay the reported introduction and an explicit comparison with the real LLM."""
import argparse,asyncio,json
from datetime import datetime
from evaluate_natural_dialogue import ROOT,ai,Session,Conversation,DialogueRun,append
from sqlalchemy import select

async def run():
    folder=ROOT/'output'/('reply-presentation-'+datetime.now().strftime('%Y%m%d-%H%M%S'));folder.mkdir(parents=True)
    print('ARTIFACT '+str(folder),flush=True)
    report={'cases':[],'passed':False}
    for name,text in [('introduction','我想了解 HUAWEI MateBook D 16 2024，能介绍一下吗？'),
                      ('comparison','请对比HUAWEI MateBook D 16 2024和HUAWEI MateBook X Pro 酷睿 Ultra 微绒典藏版的重量、分辨率和色域。')]:
        with Session() as session:
            conv=Conversation(customer_id='presentation-replay',customer_name='回复显示隔离复核',owner_id='presentation-staff',status='active')
            session.add(conv);session.commit();cid=conv.id
        append(cid,'customer',text)
        case={'name':name,'customer':text};report['cases'].append(case)
        try:
            result=await ai.analysis(cid);state=result['dialogue'];reply=state['action']['candidates'][0]['reply']
            case.update(reply=reply,action=state['action']['kind'])
            assert '资料原文' not in reply and '<br' not in reply.lower(),reply
            if name=='introduction':assert '| 机型 |' not in reply and len(reply)<900,reply
            else:assert '1920' in reply and '3120' in reply and '重量' in reply,reply
            with Session() as session:
                trace=session.scalar(select(DialogueRun).where(DialogueRun.conversation_id==cid).order_by(DialogueRun.created_at.desc()).limit(1))
                (folder/(name+'-trace.json')).write_text(trace.trace,encoding='utf-8')
            case['passed']=True
            print(json.dumps(case,ensure_ascii=False),flush=True)
        except Exception as error:
            case.update(passed=False,error=str(error));print(json.dumps(case,ensure_ascii=False),flush=True)
    report['passed']=all(c['passed'] for c in report['cases'])
    (folder/'result.json').write_text(json.dumps(report,ensure_ascii=False,indent=2),encoding='utf-8')
    md=['# 实际LLM回复显示复核','','复现截图中的真实咨询，使用隔离数据库和网站实际AI链路；没有改写任何模型回复。','']
    for case in report['cases']:
        md+=['## '+case['name'],'','**客户：** '+case['customer'],'','**客服原文：**','',case.get('reply',case.get('error','')),'']
    (folder/'问答.md').write_text('\n'.join(md),encoding='utf-8')
    print('PASSED '+str(report['passed']),flush=True)

if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--live',action='store_true');args=parser.parse_args()
    if not args.live:parser.error('--live is required')
    import sys
    sys.stdout.reconfigure(encoding='utf-8');asyncio.run(run())
