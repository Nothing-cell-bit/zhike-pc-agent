"""Generate three real drafts with the same product evidence and existing gateway."""
import argparse
import asyncio
import html
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
from backend import ai
from backend.db import Session,Job,Work
from backend.knowledge import knowledge
from backend.platform_content import publication_text
from backend.publication import render_publication
from backend.moments_gallery import latest_gallery,gallery_paths,gallery_zip


async def run(source_work,output,revise_from=None,platforms=None,reuse_from=None):
    output=Path(output).resolve();output.mkdir(parents=True,exist_ok=True)
    original_model=ai.model_json;trace_count=0
    async def traced_model(instruction,data,max_tokens=2400,schema=None,**kwargs):
        nonlocal trace_count
        trace_count+=1;number=trace_count
        result,usage=await original_model(instruction,data,max_tokens,schema=schema,**kwargs)
        folder=output/'traces';folder.mkdir(exist_ok=True)
        (folder/f'{number:02}-{schema.__name__ if schema else "json"}.json').write_text(json.dumps({'instruction':instruction,'input':data,'output':result,'usage':usage},ensure_ascii=False,indent=2),encoding='utf-8')
        return result,usage
    ai.model_json=traced_model
    with Session() as session:
        original=session.get(Work,source_work)
        if not original:raise ValueError('原作品不存在')
        product_id=json.loads(original.brief)['product_id'];actor=original.actor_id
    product,refs=ai.evidence_for_product(product_id)
    async def shared_evidence(brief):return product,refs,{'source_type':'local_zip','fallback_reason':''}
    ai.marketing_evidence=shared_evidence
    common={'workflow':'platform-v1','product_id':product_id,'audience':'准备上大学、以日常学习和入门编程为主的学生',
      'scene':'在教室、图书馆和宿舍学习，阅读课件、写报告，并学习编程、写代码。具体专业、开发软件和系统版本未提供。',
      'goal':'帮助学生按真实学习与编程任务判断是否值得了解，并引导带课程软件清单到店体验',
      'tone':'自然、具体、专业，不夸张，不像说明书',
      'emphasis':'只围绕学习和写代码。不承诺未证实的软件兼容、性能表现、实际续航或活动。三平台按各自内容目标独立创作，不得把同一篇文章缩短重复使用。'}
    outcomes=[]
    revisions={item['platform']:item for item in json.loads(Path(revise_from).read_text(encoding='utf-8'))} if revise_from else {}
    reuse={item['platform']:item for item in json.loads(Path(reuse_from).read_text(encoding='utf-8'))} if reuse_from else {}
    feedback={
      '公众号':'当前正文参数清单过密、反复强调核验。请改成给准大学生的选购推理：先把课件阅读、报告写作、理解代码的任务排清，再解释屏幕和接口为什么有价值。只保留16:10屏幕与常用接口这两组事实，不列CPU、色域、重量、内存、续航或专业GPU分支。三个小节自然推理，限制集中在末尾一句。不要反复“到店核验”。标题30字以内，导语80字以内，正文500–700个汉字左右。',
      '小红书':'当前稿又长又像产品核对说明书。请写校园三个场景：课堂查课件、图书馆看代码、宿舍接外设。每个场景一条具体动作建议及简短原因，像可收藏笔记，不要逐条“为什么：”。最多1–2个实证参数，不列CPU、色域、系统差异或蓝牙指纹目录。正文250–350个汉字，标题总长20字符以内，结尾只问一个具体问题，3–5个话题。intro和cta为空。',
      '朋友圈':'当前稿开头像照抄任务描述，后面堆分辨率、ppi等参数。请写80–130个字符、两段自然微信短文，只围绕“阅读课件和看代码”一个顾虑、16:10屏幕一个特点。正文可简称这台MateBook D14，完整型号放内部title。不要列其他参数，不要假装有现货、实测或兼容所有软件。最后一句自然邀请带软件清单咨询或来体验。intro/cta/tags均为空。',
    }
    (output/'evidence.json').write_text(json.dumps({'product':product['name'],'sources':refs},ensure_ascii=False,indent=2),encoding='utf-8')
    for index,platform in enumerate(['公众号','小红书','朋友圈'],1):
        brief={**common,'platform':platform}
        if platforms is not None and platform not in platforms and platform in reuse:
            jid=reuse[platform]['job_id']
            print(json.dumps({'event':'reused','platform':platform,'job_id':jid}),flush=True)
        else:
            with Session() as session:
                previous=session.get(Work,revisions[platform]['work_id']) if platform in revisions else None
                payload={'expected_version':previous.version,'editorial_feedback':feedback[platform]} if previous else brief
                job=Job(kind='repair' if previous else 'generate',actor_id=actor,target_id=previous.id if previous else '',status='queued',payload=json.dumps(payload,ensure_ascii=False));session.add(job);session.commit();jid=job.id
            print(json.dumps({'event':'started','platform':platform,'job_id':jid}),flush=True)
            await ai.run_text_job(jid)
        with Session() as session:
            job=session.get(Job,jid);result=json.loads(job.result or '{}')
            if job.status!='completed' or not result.get('work_id'):
                failure={'event':'failed','platform':platform,'job_id':jid,'status':job.status,'error':job.error,'result':result}
                print(json.dumps(failure),flush=True)
                (output/f'{index}-error.json').write_text(json.dumps(failure,ensure_ascii=False,indent=2),encoding='utf-8');continue
            work=session.get(Work,result['work_id']);content=json.loads(work.content);report=json.loads(work.report)
            item={'platform':platform,'work_id':work.id,'job_id':jid,'brief':brief,'content':content,'report':report,'seconds':result.get('seconds')}
            gallery=latest_gallery(session,work) if platform=='朋友圈' else None
            photo_paths=gallery_paths(session,work,gallery) if gallery else []
            if gallery:
                item['gallery']=gallery
                (output/'moments-gallery.zip').write_bytes(gallery_zip(session,work,gallery))
        outcomes.append(item)
        slug=['wechat','xiaohongshu','moments'][index-1]
        (output/f'{index:02}-{slug}.json').write_text(json.dumps(item,ensure_ascii=False,indent=2),encoding='utf-8')
        (output/f'{index:02}-{slug}.md').write_text(publication_text(content,platform)+'\n',encoding='utf-8')
        def image_url(image):
            folder=output/'images';folder.mkdir(exist_ok=True)
            original=knowledge.image_path(image['id'])
            suffix=original.suffix.lower() if original.suffix.lower() in {'.png','.jpg','.jpeg','.webp'} else '.png'
            name=__import__('hashlib').sha256(image['id'].encode()).hexdigest()[:16]+suffix
            if not (folder/name).exists():shutil.copyfile(original,folder/name)
            return 'images/'+name
        rendered_gallery=None
        if gallery:
            folder=output/'images';folder.mkdir(exist_ok=True);rendered_items=[]
            for number,(photo,path) in enumerate(zip(gallery['items'],photo_paths),1):
                name=f'moments-{number:02d}'+path.suffix.lower();shutil.copyfile(path,folder/name)
                rendered_items.append({**photo,'url':'images/'+name})
            rendered_gallery={**gallery,'items':rendered_items}
        fragment=render_publication(content,platform,image_url,gallery=rendered_gallery)
        item['rendered_html']=fragment
        page='<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>'+html.escape(platform+' · '+product['name'])+'</title><style>body{margin:30px auto;padding:24px;max-width:760px;background:#fff;font-synthesis:weight style}img{max-width:100%;height:auto}h1{font-size:28px;line-height:1.5}p{line-height:1.9}figure{margin:24px 0}figcaption{color:#888;font-size:12px;text-align:center}</style><body>'+fragment+'</body></html>'
        (output/f'{index:02}-{slug}.html').write_text(page,encoding='utf-8')
        print(json.dumps({'event':'completed','platform':platform,'work_id':item['work_id'],'status':report['status'],'issues':[x['text'][:140] for x in report.get('issues',[])],'pending':report.get('pending',[]),'seconds':item['seconds']}),flush=True)
    cards=[]
    for index,item in enumerate(outcomes,1):
        report=item['report'];warnings=[x['text'] for x in report.get('issues',[])]+report.get('pending',[])
        status={'passed':'本次检查通过','needs_review':'有待确认事项'}.get(report['status'],report['status'])
        details='<details><summary>文案核验 · '+html.escape(status)+'</summary><p>'+html.escape('；'.join(warnings) if warnings else '本次检查未发现待处理问题')+'</p></details>'
        if item.get('gallery'):details+='<p style="padding:0 24px 18px;color:#8a7660;font-size:11px;line-height:1.8">配图：'+str(item['gallery']['original_count'])+'张产品原图 ＋ '+str(item['gallery']['ai_count'])+'张AI场景图。AI场景为创意示意，不代表实际使用实拍。<br><a href="moments-gallery.zip" download>下载九张配图与朋友圈文案</a></p>'
        label={'公众号':'选购推理 · 深度文章','小红书':'校园场景 · 收藏笔记','朋友圈':'顾问口吻 · 自然短文'}[item['platform']]
        cards.append('<article><header><b>'+html.escape(item['platform'])+'</b><span>'+label+'</span></header><div class="paper">'+item['rendered_html']+'</div>'+details+'</article>')
    page='''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>同一产品，三种平台表达</title><style>
    *{box-sizing:border-box}body{margin:0;background:#f5f5f0;color:#29332c;font-family:Microsoft YaHei,system-ui;font-synthesis:weight style}main{max-width:1720px;margin:auto;padding:32px}h1{font-size:29px;margin:0 0 10px}main>p{color:#7d8479;font-size:13px;line-height:1.9} .grid{display:grid;grid-template-columns:1.3fr 1fr 1fr;gap:20px;margin-top:28px;align-items:start}article{background:white;border:1px solid #e3e6de;border-radius:12px;overflow:hidden}header{display:flex;gap:12px;justify-content:space-between;align-items:center;padding:20px 24px;border-bottom:1px solid #eee}header b{font-size:19px}header span{font-size:11px;color:#929b89}.paper{padding:24px;max-height:72vh;overflow:auto}.paper h1{font-size:24px}.paper p{font-size:15px;line-height:1.9}.paper img{width:100%;height:auto;max-height:280px;object-fit:contain}.paper .moments-image-grid img{height:100%;aspect-ratio:1;object-fit:contain}.paper figure{margin:22px 0;background:#f8f8f3;padding:12px}.paper figcaption{font-size:11px;color:#929b89}.paper li{font-size:15px;line-height:1.9;margin-bottom:8px}details{padding:15px 24px;border-top:1px solid #eee;font-size:12px;color:#8a7660}details p{line-height:1.8}@media(max-width:1000px){.grid{grid-template-columns:1fr}.paper{max-height:none}main{padding:20px}}</style><body><main><h1>同一台华为电脑，三种平台表达</h1><p>HUAWEI MateBook D 14 2024 · 大学学习、写报告、学习编程<br>三份内容共用同一份现有产品资料，由已配置的模型实际生成。下方是发布正文，核验记录另列。</p><div class="grid">'''+''.join(cards)+'</div></main></body></html>'
    (output/'index.html').write_text(page,encoding='utf-8')
    (output/'manifest.json').write_text(json.dumps([{key:item[key] for key in ['platform','work_id','job_id','seconds']} for item in outcomes],ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'event':'finished','count':len(outcomes),'output':str(output)}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--source-work',required=True);parser.add_argument('--output',default='output/platform-trial');parser.add_argument('--revise-from');parser.add_argument('--reuse-from');parser.add_argument('--platforms',nargs='+',choices=['公众号','小红书','朋友圈']);parser.add_argument('--render-only',action='store_true');args=parser.parse_args()
    if args.render_only and not args.reuse_from:parser.error('--render-only requires --reuse-from')
    asyncio.run(run(args.source_work,args.output,args.revise_from,[] if args.render_only else args.platforms,args.reuse_from))
