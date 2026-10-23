"""Build the current submission PDF from the maintained Markdown manual."""
from pathlib import Path
from xml.sax.saxutils import escape
import re
from reportlab.platypus import SimpleDocTemplate,Paragraph,Spacer,PageBreak,Table,TableStyle,Image,KeepTogether
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.lib.pagesizes import A4
from PIL import Image as PILImage
ROOT=Path(__file__).resolve().parents[2]
SOURCE=ROOT/'docs/competition/WORK_DESCRIPTION.md'
OUTPUT=ROOT/'output/pdf/比比拉布-知客-作品说明书.pdf'
pdfmetrics.registerFont(TTFont('CN','C:/Windows/Fonts/msyh.ttc',subfontIndex=0))
pdfmetrics.registerFont(TTFont('CNB','C:/Windows/Fonts/msyhbd.ttc',subfontIndex=0))
GREEN=colors.HexColor('#164c3b'); INK=colors.HexColor('#24352f'); LIGHT=colors.HexColor('#e2ede5')
WIDTH=A4[0]-84
styles={
 'body':ParagraphStyle('body',fontName='CN',fontSize=11,leading=18,spaceAfter=10,wordWrap='CJK',textColor=INK),
 'small':ParagraphStyle('small',fontName='CN',fontSize=9.2,leading=14.5,spaceAfter=5,wordWrap='CJK',textColor=colors.HexColor('#52675e')),
 'h1':ParagraphStyle('h1',fontName='CNB',fontSize=21,leading=30,spaceAfter=17,wordWrap='CJK',textColor=GREEN),
 'title':ParagraphStyle('title',fontName='CNB',fontSize=29,leading=42,spaceAfter=18,wordWrap='CJK',textColor=GREEN),
}
def p(s,style='body'):
 return Paragraph(escape(s).replace('\n','<br/>'),styles[style])
def footer(c,d):
 c.saveState();c.setStrokeColor(colors.HexColor('#c8d7cf'));c.line(42,43,A4[0]-42,43)
 c.setFont('CN',8);c.setFillColor(GREEN);c.drawString(42,29,'比比拉布 · 知客 | 作品说明书 · 2026-10-23');c.drawRightString(A4[0]-42,29,f'{d.page}');c.restoreState()
def table(rows):
 widths=([90,233,WIDTH-323] if len(rows[0])==3 else [115,WIDTH-115])
 t=Table([[p(x,'small') for x in row] for row in rows],colWidths=widths,repeatRows=1,hAlign='LEFT')
 t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),LIGHT),('VALIGN',(0,0),(-1,-1),'TOP'),('LINEBELOW',(0,0),(-1,0),.7,colors.HexColor('#9cb9a8')),('LINEBELOW',(0,1),(-1,-1),.35,colors.HexColor('#d4dfd8')),('LEFTPADDING',(0,0),(-1,-1),8),('RIGHTPADDING',(0,0),(-1,-1),8),('TOPPADDING',(0,0),(-1,-1),7),('BOTTOMPADDING',(0,0),(-1,-1),5)]))
 return t
story=[];lines=SOURCE.read_text(encoding='utf-8-sig').splitlines();i=0
while i<len(lines):
 s=lines[i].strip();i+=1
 if not s:continue
 if s.startswith('# '):
  story.extend([p('比比拉布团队 | 华为·产业进阶赛道','small'),Spacer(1,12),p('知客\n华为 PC 门店增长工作台','title')]);continue
 if s.startswith('## '):story.extend([PageBreak(),p(s[3:],'h1')]);continue
 if s.startswith('|'):
  rows=[]
  while True:
   if not re.match(r'^\|[\s:|\-]+\|$',s):rows.append([v.strip() for v in s.strip('|').split('|')])
   if i>=len(lines) or not lines[i].strip().startswith('|'):break
   s=lines[i].strip();i+=1
  story.extend([table(rows),Spacer(1,11)]);continue
 if s.startswith('!['):
  m=re.match(r'!\[(.*?)\]\((.*?)\)',s);path=(SOURCE.parent/m.group(2)).resolve()
  with PILImage.open(path) as im:w,h=im.size
  scale=min(WIDTH/w,270/h)
  img=Image(str(path),w*scale,h*scale);img.hAlign='CENTER'
  story.extend([KeepTogether([img,Spacer(1,4),p(m.group(1)+' · 实际网页录制画面','small')]),Spacer(1,8)]);continue
 story.append(p(s,'small' if s.startswith(('作品说明书','版本：','材料范围：')) else 'body'))
OUTPUT.parent.mkdir(exist_ok=True,parents=True)
SimpleDocTemplate(str(OUTPUT),pagesize=A4,rightMargin=42,leftMargin=42,topMargin=40,bottomMargin=56,title='知客：华为 PC 门店增长工作台 - 作品说明书',author='比比拉布团队').build(story,onFirstPage=footer,onLaterPages=footer)
print(OUTPUT)
