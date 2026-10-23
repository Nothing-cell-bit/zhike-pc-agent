import json
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'output/competition-video-voice-20261023';OUT.mkdir(parents=True,exist_ok=True)
short=json.loads((ROOT/'output/competition-video-short-20261023/剪辑与检查.json').read_text(encoding='utf-8'))
texts=[
'知客，让门店服务更高效。',
'客户从网页发起咨询，说清自己的购买需求。',
'消息实时同步，建立同一笔客户会话。',
'管理员统一维护网站设置。',
'客服账号由管理员集中管理。',
'按客服工作量分配新咨询，接待责任清晰。',
'客服打开刚分配的客户会话。',
'人工智能准备回复，客服确认后发送。',
'客户继续补充预算、配置和出差需求。',
'四级报价分别管理规则、资格和审批。',
'系统承接多轮上下文，提供三个回复候选。',
'客服选择合适表达，继续回复客户。',
'客户确认配置，并提出含税报价请求。',
'知识库状态和资料版本清晰可查。',
'价格不确定时，先登记核实事项。',
'填写结论、条件、来源和有效期。这里的价格均为演示测试数据。',
'核实完成后，系统继续生成客户反馈。',
'模型服务由管理员配置，密钥不回显。',
'客服确认发送，报价卡自动附上配置、金额和有效期。',
'客户端收到同一笔报价，核实记录也更新为已反馈，服务形成闭环。',
'本次咨询结束，历史记录继续保留。',
'营销环节展示另一个产品的已有作品，文案和配图一同预览。',
'自动核验与人工审核状态区分，问题记录可追溯。',
'审核后的图文可以导出，用于后续发布。',
'知客，连接客户、门店与内容。']
assert len(texts)==len(short['chapters'])
plan=[{**c,'narration':t,'index':i} for i,(c,t) in enumerate(zip(short['chapters'],texts),1)]
(OUT/'voice-plan.json').write_text(json.dumps(plan,ensure_ascii=False,indent=2),encoding='utf-8')
(OUT/'配音稿.txt').write_text('\n\n'.join(f'{p["index"]:02} {p["title"]}\n{p["narration"]}' for p in plan),encoding='utf-8')
