"""Build a private local casebook from saved records; no HTTP or model calls."""
import base64
import html
import json
import mimetypes
import sys
from pathlib import Path

import bleach
import markdown

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend.marketing import unified_markdown, image_relative_url, has_inline_images
from backend.knowledge import knowledge


def main():
    out=ROOT/'output'/'competition';out.mkdir(parents=True,exist_ok=True)
    saved=ROOT/'data'/'acceptance'/'recovery-20261018'
    sections=[];summary=[]
    for index in [1,2,3]:
        path=saved/f'work-{index}-final.json'
        if not path.exists():raise SystemExit('缺少已保存的历史案例；不会用测试夹具或新模型调用代替。')
        work=json.loads(path.read_text(encoding='utf-8-sig'))
        content=work['content'];report=work['report']
        if isinstance(content,str):content=json.loads(content)
        if isinstance(report,str):report=json.loads(report)
        content=dict(content)
        if work.get('version',1)>1:content['strategy_current']=False
        if has_inline_images(content):raise SystemExit('历史正文含未受管理图片，请人工核对，不自动导出。')
        text=unified_markdown(content,work['brief'],report,report.get('status')!='passed')
        allowed={image_relative_url(im) for im in content.get('images',[])}
        def image_attribute(tag,name,value):return name=='alt' or (name=='src' and value in allowed)
        rendered=bleach.clean(markdown.markdown(text),tags={'h1','h2','h3','p','ul','ol','li','strong','em','a','img','blockquote','br'},attributes={'a':['href'],'img':image_attribute},protocols=['https','http'])
        for image in content.get('images',[]):
            image_path=knowledge.image_path(image['id'])
            if not image_path or not image_path.is_file():raise SystemExit('历史图片不存在，不用其他图片替代。')
            uri='data:'+(mimetypes.guess_type(image_path)[0] or 'image/png')+';base64,'+base64.b64encode(image_path.read_bytes()).decode()
            rendered=rendered.replace(image_relative_url(image),uri)
        item={'case':index,'work_id':work['id'],'version':work['version'],'platform':work['brief']['platform'],'title':content['title'],'saved_prompt_version':report.get('prompt_version'),'verification':report.get('status'),'ima_verified':False,'model_called_during_preparation':False}
        summary.append(item)
        sections.append('<section id="case-'+str(index)+'"><p class="notice">历史案例 '+str(index)+'；已人工修订后再核验。以下使用旧记录重新排版，不是 store-v3 的新运行结果，也不是 ima 验收。</p>'+rendered+'</section>')
    page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>知客本地案例册</title><style>body{max-width:960px;margin:32px auto;padding:0 20px;font:16px/1.8 system-ui;overflow-wrap:anywhere}img{max-width:100%;max-height:540px;object-fit:contain}section{border-top:2px solid #b52f37;margin-top:40px;padding-top:16px}.notice{padding:16px;background:#fff1dc}a{color:#94303a}</style><body><h1>知客 · 本地案例册</h1><p>2026-10-18 整理。私有、本地审阅用；资料图片未获公开传播确认，不发布或提交。三组为已有 store-v2 记录，当前代码为 store-v3；本轮无模型调用。</p><nav>'+''.join('<a href="#case-'+str(item['case'])+'">案例 '+str(item['case'])+' · '+html.escape(item['platform'])+'</a>　' for item in summary)+'</nav>'+''.join(sections)+'</body></html>'
    (out/'casebook.html').write_text(page,encoding='utf-8')
    (out/'casebook-summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2),encoding='utf-8')
    print('Prepared output/competition/casebook.html from 3 historical records; no model/network calls.')


if __name__=='__main__':main()
