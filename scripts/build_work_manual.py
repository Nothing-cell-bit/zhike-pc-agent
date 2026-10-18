"""Build a source-backed Chinese competition manual, without network/model calls."""
from pathlib import Path
from io import BytesIO
from xml.sax.saxutils import escape
import json
import zipfile

from PIL import Image as PILImage
from reportlab.pdfgen import canvas
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.colors import HexColor, Color, white
from reportlab.lib.styles import ParagraphStyle
from reportlab.platypus import Paragraph, Table, TableStyle
from reportlab.lib.utils import ImageReader

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / 'tmp/pdfs/redesign'
OUT.mkdir(parents=True, exist_ok=True)
DEST = OUT / '比比拉布-知客-作品说明书.pdf'
EVIDENCE = ROOT / 'data/acceptance/ima-20261018-v4'
pdfmetrics.registerFont(TTFont('CN', 'C:/Windows/Fonts/msyh.ttc', subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNB', 'C:/Windows/Fonts/msyhbd.ttc', subfontIndex=0))
pdfmetrics.registerFontFamily('CN', normal='CN', bold='CNB', italic='CN', boldItalic='CNB')
W, H = 595.276, 841.89
M, CW = 43, 509.276
INK, MUTED = HexColor('#222B36'), HexColor('#606976')
RED, PALE = HexColor('#B72C3C'), HexColor('#FAF0EF')
LINE, LIGHT = HexColor('#DDDDE1'), HexColor('#F5F6F8')
GREEN, AMBER = HexColor('#276B58'), HexColor('#916022')
C = canvas.Canvas(str(DEST), pagesize=(W, H), pageCompression=1)
C.setTitle('知客｜从门店需求到有依据的营销图文')
C.setAuthor('比比拉布团队')
C.setSubject('华为·产业进阶赛道作品说明书；真实需求、操作流程、运行案例及要求对照')
CHECKS = []
PAGE = 0

def para(text, x=M, y=0, w=CW, size=10.3, leading=None, color=INK, bold=False):
    """Draw a paragraph using top-origin coordinates and return its bottom."""
    st = ParagraphStyle('p', fontName='CNB' if bold else 'CN', fontSize=size,
                        leading=leading or size*1.62, textColor=color, wordWrap='CJK',
                        splitLongWords=True, allowWidows=0, allowOrphans=0)
    p = Paragraph(escape(text).replace('\n', '<br/>'), st)
    _, h = p.wrap(w, H)
    p.drawOn(C, x, H-y-h)
    CHECKS.append({'page': PAGE, 'bottom': round(y+h, 1), 'text': text[:32]})
    return y+h

def rule(y, x=M, w=CW, color=LINE):
    C.setStrokeColor(color); C.setLineWidth(.65); C.line(x, H-y, x+w, H-y)

def rect(x, y, w, h, fill=LIGHT, radius=0):
    C.setFillColor(fill)
    if radius: C.roundRect(x,H-y-h,w,h,radius,stroke=0,fill=1)
    else: C.rect(x,H-y-h,w,h,stroke=0,fill=1)

def tag(text, x, y, w, fill=PALE, color=RED):
    rect(x,y,w,23,fill,5); para(text,x+9,y+4,w-18,8.5,13,color,True)

def box(title, body, x, y, w, h, fill=LIGHT, accent=RED):
    rect(x,y,w,h,fill,7)
    yy=para(title,x+15,y+13,w-30,11.2,18,accent,True)
    bottom=para(body,x+15,yy+7,w-30,9.5,15.5)
    if bottom>y+h-8: raise ValueError(f'Box overflow on page {PAGE}: {title}: {bottom} > {y+h}')

def table(headers, rows, widths, y, font=9.1):
    st=ParagraphStyle('cell',fontName='CN',fontSize=font,leading=font*1.55,textColor=INK,wordWrap='CJK')
    hd=ParagraphStyle('head',parent=st,fontName='CNB',textColor=white)
    vals=[[Paragraph(escape(str(v)).replace('\n','<br/>'),hd if i==0 else st)
           for v in row] for i,row in enumerate([headers]+rows)]
    t=Table(vals,colWidths=widths,hAlign='LEFT')
    t.setStyle(TableStyle([
        ('BACKGROUND',(0,0),(-1,0),INK),('VALIGN',(0,0),(-1,-1),'TOP'),
        ('ROWBACKGROUNDS',(0,1),(-1,-1),[LIGHT,white]),
        ('LEFTPADDING',(0,0),(-1,-1),10),('RIGHTPADDING',(0,0),(-1,-1),10),
        ('TOPPADDING',(0,0),(-1,-1),10),('BOTTOMPADDING',(0,0),(-1,-1),10),
        ('LINEBELOW',(0,1),(-1,-1),.4,LINE),
    ]))
    _,h=t.wrap(CW,H);t.drawOn(C,M,H-y-h)
    CHECKS.append({'page':PAGE,'bottom':round(y+h,1),'text':'TABLE '+headers[0]})
    return y+h

def section(title,y): return para(title,y=y,size=13,leading=20,bold=True)+9

def photo(path,x,y,w,maxh=None,crop=None):
    im=PILImage.open(path)
    if crop: im=im.crop(crop)
    h=w*im.height/im.width
    if maxh and h>maxh: w=w*maxh/h;h=maxh
    C.drawImage(ImageReader(im),x,H-y-h,width=w,height=h,mask='auto')
    return y+h

def link(label,url,x,y,w=CW):
    b=para(label,x,y,w,9.3,15,RED)
    C.linkURL(url,(x,H-b,x+w,H-y),relative=0,thickness=0)
    return b

def start(kicker,title,subtitle):
    global PAGE
    PAGE+=1
    rect(0,0,W,7,RED)
    para('比比拉布  /  知客',M,25,230,9,14,MUTED,True)
    para(kicker,W-222,25,179,8.5,14,RED)
    rule(50)
    para(title,y=68,size=23,leading=32,bold=True)
    para(subtitle,y=109,size=9.7,leading=15.5,color=MUTED)
    C.bookmarkPage(f'p{PAGE}')
    C.addOutlineEntry(title,f'p{PAGE}',0,False)

def finish(source):
    para(source,y=757,size=7.2,leading=11,color=MUTED)
    rule(790)
    para('华为·产业进阶赛道  |  作品说明书  |  2026.10.18',M,800,440,7.4,11,MUTED)
    para(f'{PAGE:02d} / 11',W-87,800,44,7.4,11,MUTED)
    C.showPage()

def load_work(i):
    d=json.loads((EVIDENCE/f'review-{i}-work.json').read_text(encoding='utf-8'))
    c=d['content']; d['content']=json.loads(c) if isinstance(c,str) else c
    return d

WORKS=[load_work(i) for i in range(1,4)]
def content_paragraphs(c,x,y,w,size=9.5):
    for t in c['body'].split('\n\n'):
        if t.startswith('## '):
            y=para(t[3:],x,y+6,w,size+1,17,INK,True)+5
        else: y=para(t,x,y,w,size,size*1.65)+6
    return y

# 01: A useful cover, with an immediate answer and reading route.
start('作品定位', '知客', '华为 PC 营销图文智能体  ·  门店增长工作台')
para('从顾客需求出发，\n把产品资料写成可核验的营销图文。',y=157,size=24,leading=38,bold=True)
para('服务对象：华为 PC 门店导购与内容运营。\n核心任务：理解人群和场景，调用 ima 资料与同型号图片，生成适配平台的内容，经核验与人工确认后导出。',y=256,size=11,leading=19)
gap=12; bw=(CW-2*gap)/3
for i,(title,body) in enumerate([
    ('需求从哪里来','客户咨询形成的需求摘要，或运营人员直接填写的营销任务。'),
    ('知客负责什么','场景与平台策略、资料检索、图文组织、独立核验和版本管理。'),
    ('门店拿到什么','可编辑的图文、资料与配图依据、核验结果，以及可复制或导出的文件。')]):
    box(title,body,M+i*(bw+gap),337,bw,130)
rect(M,492,CW,100,PALE,7)
para('当前可核验的进度',M+16,506,CW-32,12,18,RED,True)
para('已保存 3 组真实运行结果：2 组 ima 来源，1 组本地回退；均在人工修订后通过 V2 独立模型核验。当前交付为本地可运行原型。',M+16,535,CW-32,10.5,18)
para('阅读导航',y=619,size=12,leading=19,bold=True)
para('02 真实需求与范围     03 操作流程     04 交付格式\n05-07 真实案例          08-09 技术与核验     10 要求对照     11 运行与证据',y=651,size=10.4,leading=24)
finish('说明范围：依据现有需求、赛题手册 v4 与 store-v4-ima 保存记录整理；本次重制未新增模型调用。')

# 02: Business need, not a feature inventory.
start('真实需求', '门店需要解决的，是这四件事', '以日常接待和内容创作为起点，把每项功能对应到具体工作。')
y=table(['实际工作中的问题','知客的处理方式','员工最终得到'],[
    ['客户只说“想买电脑”，需求不完整','从客户原话整理需求；缺失项标为“尚未了解”，给出下一句追问。','有依据的需求摘要；员工确认后再继续沟通。'],
    ['产品资料多，相近型号容易混用','绑定完整型号、系统和配置；检索事实、限制条件及同型号图片。','能回查来源的事实点与图片清单。'],
    ['同一套文案难以适配不同人群和平台','先确定场景和内容目标，再调整卖点顺序、结构、语气、配图和引导。','公众号、小红书、朋友圈或海报内容。'],
    ['改完稿件后，旧的“通过”状态不可信','保存新版本，撤销旧核验状态，再检查当前全文和图片。','与当前稿件对应的核验结果及导出文件。'],
],[133,214,162.276],156,font=9.3)
y=section('客户需求记录：七个字段各司其职',y+24)
y=para('客户身份 · 购机意向 · 购机预算 · 主要用途 · 必用软件 · 主要顾虑 · 下一步安排',y=y,size=10.5,bold=True)
y=para('不由“大学生”推断用途，不由“想了解价格”推断成交意向；下一步只记录客户明确同意的安排。自动提取保留原话依据，人工修正优先。',y=y+10,size=10)
y=section('业务扩展与赛题核心的关系',y+23)
box('本次说明书重点','营销任务 → ima 资料与图片 → 场景与平台策略 → 图文 → 核验 → 修改与导出。',M,y,247,101,PALE)
box('服务门店的扩展能力','访客咨询、员工接待、需求分析、产品资料和跟进待办。AI 回复由员工手动发送。',M+262,y,247,101)
para('四级报价、报价准确率 95% 等早期设想缺少真实规则和统计口径，当前未实现，也不属于本赛题手册的最低要求。',y=y+116,size=9,leading=15,color=MUTED)
finish('需求依据：spec.md（含七字段更新）；PROJECT_NOTES.md（早期需求来源）；赛题手册 v4，第 3-5 页。')

# 03: Walkthrough and authentic interface.
start('功能讲解', '一次营销任务，怎样完成', '可以从客户需求摘要进入，也可以直接在“营销内容 → 新建内容”创建任务。')
steps=[
    ('01  填写任务','选择完整产品型号、目标人群、使用场景、内容目标和平台；购买阶段、主要问题可补充。必要信息不足时先补齐。'),
    ('02  获取依据','优先读取指定 ima 库中的产品事实、卖点与限制和原图；来源与型号绑定，记录本次资料快照。'),
    ('03  组织内容','根据场景确定切入点，按平台生成标题、导语、正文、标签、行动引导，并记录图片及位置。'),
    ('04  核验与改稿','查看内容检查和创作依据，修改正文或图片。改动后旧核验状态失效，需重新核验。'),
    ('05  保存与交付','核验允许后复制或导出；保留作品版本、资料依据与核验记录。平台切换会创建新的生成任务。'),
]
y=156
for title,body in steps:
    para(title,M,y,110,10.5,17,RED,True)
    b=para(body,M+120,y,CW-120,9.6,16)
    y=max(y+44,b+13)
rule(y)
y=section('实际界面：作品、来源与检查状态在同一工作区',y+17)
photo(ROOT/'data/migrations/8765-browser/case-1-preview.png',M,y,CW,crop=(278,317,1404,970))
para('截图裁切自 2026-10-18 本地迁移验收；左侧为图文预览，右侧可见 ima 来源与“可使用”状态。',y=y+302,size=8.4,leading=13,color=MUTED)
finish('功能依据：README.md；界面证据：data/migrations/8765-browser/case-1-preview.png。')

# 04: What the product actually delivers.
start('交付标准', '换平台，内容结构也要跟着变', '平台适配同时涉及表达、图片与行动引导；所有结果按四部分组织，方便检查和复用。')
y=table(['平台','内容组织','图片要求','行动引导'],[
    ['公众号','标题 + 导语 + 分节正文；围绕问题展开事实与条件。','2-4 张','带任务清单到店体验'],
    ['小红书','口语标题 + 短段落 + 场景 + 话题标签；不伪造亲身体验。','3-6 张','留言、咨询、到店'],
    ['朋友圈','短文案，集中讲一个核心卖点。','1-3 张','私信或预约到店'],
    ['门店海报','主标题 + 副标题 + 最多 3 个卖点 + 活动说明。','1 张主视觉','明确咨询或到店'],
],[72,241,70,126.276],156,font=9.1)
y=section('统一输出：既有成稿，也有可检查的依据',y+25)
box('一 / 场景判断','人群、场景、主要问题、内容目标、平台；购买阶段未提供时保留“待确认”。',M,y,247,106)
box('二 / 知识库依据','完整产品型号、事实点、资料标题与来源；图片记录名称、来源和适用型号。',M+262,y,247,106)
box('三 / 图文软文','标题、导语、正文、行动引导、标签；图片说明与正文插入位置。',M,y+119,247,106)
box('四 / 核验结果','产品事实、图片型号、合规检查与待确认信息；说明实际使用的知识来源。',M+262,y+119,247,106)
para('可交付格式：复制文本、Markdown、HTML、图片与引用 ZIP、本地海报 PNG。稿件修改后需重验；资料冲突时连草稿导出也会被阻止。',y=y+243,size=9.6,leading=16)
finish('规则依据：赛题手册 v4，第 4-5 页；实现依据：backend/prompts/marketing-system.txt、README.md。')

# 05: Case 1, complete real text. Use actual image thumbnails, never fabricated output.
c=WORKS[0]['content']
start('真实案例 01  /  ima', '大学新生 × 小红书', '产品：HUAWEI MateBook 14（鸿蒙版）  |  三张同型号图片  |  人工修订后 V2 通过')
para('任务输入',y=151,size=11,leading=17,color=RED,bold=True)
para('准备开学的大学新生；课堂笔记、图书馆阅读与日常文档，需要携带方便；目标为咨询与到店体验。购买阶段和用户问题未填写，保留待确认。',y=176,size=9.5,leading=15)
rule(218)
para(c['title'],y=232,size=15,leading=23,bold=True)
y=para(c['intro'],y=269,size=9.4,leading=15)+5
y=content_paragraphs(c,M,y,CW,size=9.4)
y=para(c['cta'],y=y+2,size=9.4,leading=15,color=RED)+6
y=para('话题：'+' / '.join(c['tags']),y=y,size=8.6,leading=14,color=MUTED)+12
with zipfile.ZipFile(EVIDENCE/'final-case-1.zip') as z:
    names=[n for n in z.namelist() if n.startswith('images/') and not n.endswith('/')]
    for j,n in enumerate(names[:3]):
        x=M+j*174; rect(x,y,161,70,LIGHT,4)
        im=PILImage.open(BytesIO(z.read(n)))
        if im.mode == 'RGBA' and im.getbbox():
            im = im.crop(im.getbbox())
        iw,ih=im.size; scale=min(149/iw,60/ih)
        C.drawImage(ImageReader(im),x+(161-iw*scale)/2,H-y-(70+ih*scale)/2,iw*scale,ih*scale,mask='auto')
        para(['手写笔创作场景','轻薄侧面细节','双侧接口细节'][j],x,y+75,161,8,12,MUTED)
para('配图位置按保存结果：三图均在正文第 2 块后。来源为指定 ima 库该型号目录；以上为结果缩略展示。',y=y+94,size=8.1,leading=13,color=MUTED)
finish('案例原文：final-case-1.md（store-v4-ima）；依据为该次 ima“产品事实.md / 卖点与限制.md”快照。参数仅转录历史结果。')

# 06: Case 2 excerpts are clearly identified, with actual evidence.
c=WORKS[1]['content']
start('真实案例 02  /  ima', '差旅办公 × 公众号', '产品：HUAWEI MateBook 14 酷睿 Ultra  |  两张同型号图片  |  人工修订后 V2 通过')
para('任务输入',y=151,size=11,leading=17,color=RED,bold=True)
para('经常出差的职场人士；会议记录、机场处理文档、差旅携带；引导咨询与到店体验，并核对实际销售版本。购买阶段和用户问题保留待确认。',y=176,size=9.5,leading=15)
para(c['title'],y=222,size=15,leading=23,bold=True)
para('以下为最终稿原文节选；完整稿共五节，依次讨论任务、尺寸、屏幕、系统和到店核对。',y=255,size=8.5,leading=14,color=MUTED)
parts=c['body'].split('\n\n')
y=283
for idx in [2,6]:
    y=para(parts[idx].removeprefix('## '),y=y,size=10.8,leading=17,bold=True)+6
    y=para(parts[idx+1],y=y,size=9.6,leading=15.8)+15
y=para(c['cta'],y=y,size=9.7,leading=16,color=RED)+18
box('这组内容如何回应差旅场景','用电脑包、样例文档和系统版本构成选购路径；保留 Windows / Linux 功能条件。与开学场景相比，重点转为工作流程核对。',M,y,CW,90)
y+=106
table(['资料与配图','保存记录'],[
    ['事实依据','指定 ima 库 / P1-产品参数库 / 02-MateBook-Windows / MateBook 14 酷睿 Ultra / 产品事实.md、卖点与限制.md'],
    ['图片与插入位置','轻薄机身细节、主视觉，共 2 图；均位于正文第 4 块后。最终图为人工选择，位置由程序重新计算。'],
],[109,400.276],y,font=8.7)
finish('案例原文：final-case-2.md；核验记录：review-2-work.json。图源为 ima，文中参数为保存结果，不代表新增实测。')

# 07: Case 3 and honest comparison.
c=WORKS[2]['content']
start('真实案例 03  /  本地回退', '同一学习场景，压缩成朋友圈', '产品：HUAWEI MateBook 14（鸿蒙版）  |  一张图片  |  本例用于说明平台差异和失败回退')
rect(M,153,CW,63,PALE,7)
para('来源必须说清',M+14,164,CW-28,11,17,RED,True)
para('本次 ima 返回错误码 220021，整项改用本地 ZIP。该案例不计为 ima 图源案例，错误码的具体原因未确认。',M+14,187,CW-28,9.3,15)
para(c['title'],y=239,size=15,leading=23,bold=True)
y=para(c['intro'],y=276,size=10.2,leading=17)+9 if c.get('intro') else 276
y=content_paragraphs(c,M,y,CW,size=10.2)
y=para(c['cta'],y=y+3,size=10.2,leading=17,color=RED)+22
y=table(['对照维度','案例 01：小红书','案例 03：朋友圈'],[
    ['内容组织','三个核对主题：课件、携带、软件。','集中讲屏幕，再保留软件兼容条件。'],
    ['配图与引导','3 图；留言交流或带清单到店。','1 图；私信预约到店体验。'],
    ['证据范围','ima；人工修订后 V2 通过。','本地 ZIP；人工修订后 V2 通过。'],
],[90,209,210.276],y,font=9.2)
y=section('从三个真实案例中，能证明什么',y+23)
y=para('已有两类场景、三个平台的真实结果；但两场景同时换了产品，尚不能单独证明“同产品换场景”的效果。小红书与朋友圈也存在来源差异，需要补做同来源的严格对照。',y=y,size=9.7,leading=16)
para('目前文案以核对清单为主，营销吸引力仍可提升；前两例图片集中插入，图片说明较多沿用文件名。后续应优化图文对应和自然说明，再用新结果验收。',y=y+13,size=9.3,leading=15.5,color=MUTED)
finish('案例原文：final-case-3.md；对照依据：三组 final-case 文件。V2“通过”表示该次检查通过，不代表全部评分项达标。')

# 08: Architecture with readable responsibilities.
start('技术方案', '自研 Agent 如何组织整个流程', 'ima 提供事实与素材；模型理解和表达；业务程序控制型号、流程、状态和交付。')
box('门店工作台  /  React + TypeScript','客户接待、营销任务、图文编辑、创作依据、作品版本与导出。',M,156,CW,72)
para('↓',M+245,233,24,16,20,RED,True)
box('业务编排  /  FastAPI + SQLAlchemy','输入检查 → 型号绑定 → 来源选择 → 平台规则 → 生成任务 → 选图编排 → 核验 → 版本与导出。',M,261,CW,82,PALE)
para('↓',M+116,348,24,16,20,RED,True);para('↓',M+378,348,24,16,20,RED,True)
box('知识与图片','指定库“任德耀新建华为PC知识库”；读取失败可整体回退本地。保存来源快照供重验使用。',M,376,247,99)
box('文本模型','qwen3.8-27b；生成与核验分开调用。没有配置时显示失败，不返回伪造结果。',M+262,376,247,99)
y=section('ima 读取路径',498)
for a,b in [
    ('找到库','search_knowledge_base：按指定库名定位。'),
    ('检索与目录回退','search_knowledge：按型号和任务搜索；无结果时用 get_knowledge_list 逐级定位目录。'),
    ('获取资料与原图','get_media_info：读取对应资料及图片，全部成功后建立本次来源快照。'),
]:
    para(a,M,y,112,9.5,16,RED,True)
    y=para(b,M+121,y,CW-121,9.5,16)+12
para('当前产品目录映射覆盖 10 个型号，不等于已导入 ima 全库；目录调整或新增型号需要维护映射。业务数据使用 SQLite，既有本地检索使用 FTS5。',y=y+4,size=9.1,leading=15,color=MUTED)
finish('实现依据：backend/ima.py、backend/ai.py、backend/marketing.py；接入说明：IMA_INTEGRATION.md、PROMPT_DESIGN.md。')

# 09: Prompt and gates.
start('提示词与质量控制', '哪些事交给模型，哪些必须拦住', '系统提示词覆盖赛题八模块，并在实际模型调用中读取；规则与独立核验共同约束结果。')
y=table(['提示词模块','具体约束'],[
    ['角色与任务','服务华为 PC 营销，输出有资料依据的图文。'],
    ['场景理解','提取人群、场景、购买阶段、主要问题与目标；缺失信息不猜。'],
    ['平台规则','按平台改变结构、语气、图片数量和行动引导。'],
    ['知识库约束','产品事实绑定完整型号、系统、版本和条件，引用实际来源。'],
    ['图片规则','只用候选中的同型号图，说明来源、位置与选择理由。'],
    ['生成要求','交付标题、导语、正文、配图、引导与标签。'],
    ['核验规则','重新抽取当前稿件的事实；无依据内容删除或待确认。'],
    ['合规规则','检查虚构价格、补贴、体验、销量和绝对化承诺等风险。'],
],[103,406.276],153,font=9.1)
y=section('三条交付控制',y+22)
for title,body in [
    ('资料冲突 → 停止输出','真正的同条件来源冲突需人工确认，不能切换来源绕过；正式稿、草稿和海报均拦截。'),
    ('改稿 → 重新核验','正文、标签、图片等修改后保存新版本；旧版“通过”不能沿用到新稿。'),
    ('来源失败 → 明示回退','ima_first 可整体回退本地并记录原因；ima 严格模式失败即停止。比赛证据需核对实际来源。'),
]:
    para(title,M,y,159,9.7,16,RED,True)
    y=para(body,M+171,y,CW-171,9.4,15.5)+14
para('现阶段选图依据文件名、描述和场景规则，不代表像素级视觉理解；模型检查也不能替代最终人工审阅。三组展示案例均有人工修订与人工选图记录。',y=y+2,size=8.8,leading=14.3,color=MUTED)
finish('提示词全文：backend/prompts/marketing-system.txt；实际调用与重验机制：PROMPT_DESIGN.md、IMA_INTEGRATION.md。')

# 10: Direct requirement traceability, without self-awarding a score.
start('赛题要求对照', '按评审问题，逐项给出证据', '要求来自赛题手册 v4；“实现”与“完整验收”分别说明，不以功能清单代替真实结果。')
y=table(['要求 / 评分关注','本作品的对应内容','当前证据与差距'],[
    ['业务场景理解 / 20分','人群、场景、目标、购买阶段与问题输入；按场景组织内容。','第 2-7 页；已展示学习与差旅，尚需同产品、同平台换场景对照。'],
    ['产品事实准确性 / 20分','完整型号和来源快照；独立重验数字、系统与限制条件。','第 5-6、9 页；两组 ima 通过，未知购买阶段仍保留待确认。'],
    ['图文与图片引用 / 15分','同型号原图、来源、说明、插入位置。','第 5-7 页；两组 ima，第三组本地回退；图片说明与编排仍需提升。'],
    ['平台适配与软文 / 15分','四平台规则；标题、正文结构、配图和引导随平台变化。','第 4-7 页；已有三平台结果；海报效果及完整对照仍需验收。'],
    ['自研 Agent / 15分','业务编排、八模块提示词、来源绑定、版本与核验。','第 8-9 页；可查实际读取的系统提示词与代码。'],
    ['完成度与体验 / 10分','本地可运行、编辑、重验、导出；保存真实界面。','第 3、11 页；尚缺连续完整 Demo 与复赛统一任务证据。'],
    ['合规与安全 / 5分','检查无依据承诺；凭证留在服务端；保留人工确认。','第 9、11 页；不以一次检查通过承诺所有输出正确。'],
],[125,191,193.276],156,font=9.1)
y=section('材料要求与剩余动作',y+22)
y=para('初赛：GitHub、魔搭、作品说明书；至少一组可辨认的实际运行结果。\n复赛：至少 3 组结果、2 类场景、2 个平台，并补真实运行视频。当前第三组为本地回退，需补足符合 ima 图源要求的案例。',y=y,size=9.5,leading=16)
para('账号识别与共享库连接状态、完整干扰任务、匿名访问链接和连续演示，均需按提交时环境复核。本文不自评分，也不将已有公开入口等同于完成正式提交。',y=y+12,size=9,leading=15,color=MUTED)
finish('对照依据：赛题手册 v4，第 2、5、8、9 页；权重合计 100 分。完成状态以原始记录与本说明的范围为准。')

# 11: Runnable and reviewable, with source register.
start('运行与证据', '怎样运行，怎样核对', '公开源码提供程序与说明；模型、ima 权限和有权使用的知识包由运行者自行配置。')
y=section('本地启动的最短路径',153)
y=para('环境：Python 3.11+；Node.js 22.12+ 或 24+。安装 requirements.txt；前端执行 npm ci 与 npm run build。按 README 创建管理员、导入有权使用的知识包。先用自己的 ima 账号加入指定共享库，再获取同账号凭证。',y=y,size=9.5,leading=15.5)
y=para('服务端配置：.env 填写 TEXT_API_BASE、TEXT_API_KEY；.env.ima 填写 IMA_OPENAPI_CLIENTID、IMA_OPENAPI_APIKEY，设置 MARKETING_KNOWLEDGE_SOURCE=ima_first。凭证不进入源码、前端或截图。',y=y+10,size=9.2,leading=15)
rect(M,y+13,CW,58,LIGHT,5)
para('运行：.\\scripts\\start.ps1\n客服：http://127.0.0.1:8765/staff    客户：http://127.0.0.1:8765/',M+12,y+24,CW-24,9.4,18)
y=y+88
y=section('一条可复核的证据链',y)
y=para('任务输入 → V1 原稿与问题 → 人工修改 → V2 稿件 → 独立核验 → 最终导出。三组案例的核验结果均为 passed；本次仅核对保存记录，不把历史测试写成重新执行。',y=y,size=9.4,leading=15.5)
y=table(['证据','位置 / 用途'],[
    ['需求与规则','spec.md；赛题手册 v4 的本地抽取件 tmp/pdfs/handbook-extracted.txt。'],
    ['三组真实案例','data/acceptance/ima-20261018-v4/：work-*、review-*-edit、review-*-work、final-case-*。'],
    ['真实界面','data/migrations/8765-browser/：作品预览、核验界面及导出；本说明第 3 页截图来自此处。'],
    ['实现与复现','README.md；docs/competition/IMA_INTEGRATION.md、API_CONFIGURATION.md；系统提示词及后端源码。'],
],[96,413.276],y+15,font=8.5)
y=section('项目入口与提交前补齐',y+20)
y=link('GitHub：Nothing-cell-bit / zhike-pc-agent','https://github.com/Nothing-cell-bit/zhike-pc-agent',M,y)
y=link('魔搭：NothingK / zhike-pc-agent（静态项目展示）','https://modelscope.cn/studios/NothingK/zhike-pc-agent',M,y+4)
para('补齐第三组 ima 案例、同产品换场景对照、完整干扰与修改任务、连续真实录屏；提交前检查公开入口无需额外授权。魔搭展示页不提供完整业务工作台在线推理。',y=y+13,size=9.1,leading=15)
finish('入口来自项目提交配置，本次未重新验证远端可访问性。私有记录供本地核对，不包含在公开源码包中。')

C.save()
bad=[r for r in CHECKS if r['bottom']>748 and not (r['text'].startswith('华为·') or r['bottom']<=785 and r['bottom']>=757 or r['text'].endswith('/ 11'))]
# Main content should remain above the compact source/footer region.
(OUT/'layout-check.json').write_text(json.dumps({'pages':PAGE,'blocks':CHECKS,'potential_overflow':bad},ensure_ascii=False,indent=2),encoding='utf-8')
print(str(DEST))
print('pages:',PAGE,'bytes:',DEST.stat().st_size)
print('potential_overflow:',json.dumps(bad,ensure_ascii=False))
