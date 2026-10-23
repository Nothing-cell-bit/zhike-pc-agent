import asyncio
import pytest
from backend.platform_content import generate_platform,platform_issues,publication_text


@pytest.mark.parametrize('platform,format,title,body,tags',[
    ('公众号','explainer','学习编程，先弄清任务', '## 先看任务\n\n写代码先选系统。\n\n## 再看使用\n\n到店检查键盘。',[]),
    ('小红书','scene-note','新生选本先看这两点','写代码选电脑，先别急着比参数。\n\n- 核对系统\n- 试试键盘',['大学生选本','学习电脑','写代码']),
    ('朋友圈','personal-share','学习编程到店体验','准备上大学、想买电脑写代码的同学，可以带着专业课的软件清单来店里，先核对系统，再试试键盘和屏幕。',[]),
])
def test_platform_planner_and_writer_have_distinct_contracts(platform,format,title,body,tags):
    calls=[]
    async def model(instruction,data,max_tokens=0,schema=None,**kwargs):
        calls.append((data,schema.__name__))
        if schema.__name__=='ArticlePlan':
            return {'format':format,'thesis':'按真实学习任务选本','target_reader':'大学新生','hook':'先核对系统',
                    'sections':[{'title':'学习任务','intent':'解释选择'}] if platform!='朋友圈' else [],
                    'evidence_ids':['s1'],'cover_direction':'同型号电脑原图','image_purposes':['展示外观'],'risk_notes':['不承诺软件兼容'],'conflicts':[]},{}
        return {'title':title,'body':body,'intro':'先梳理任务，再看配置。' if platform=='公众号' else '',
                'cta':'带上软件清单到店体验。' if platform=='公众号' else '', 'tags':tags,
                'strategy':'按平台和人群确定叙述','claims':[{'text':'电脑型号','source_id':'s1'}]},{}
    content,usage=asyncio.run(generate_platform({'platform':platform,'scene':'学习写代码','audience':'大学新生'},
        {'name':'HUAWEI MateBook D 14 2024'},[{'id':'s1','excerpt':'真实产品资料'}],model))
    assert len(calls)==2
    assert calls[0][1]=='ArticlePlan' and calls[1][1] in {'WechatDraft','RedNoteDraft','MomentsDraft'}
    assert calls[1][0]['article_plan']['format']==format
    assert content['content_format']==format and content['editorial_plan']['evidence_ids']==['s1']
    assert not platform_issues(content,platform)
    if platform=='朋友圈':
        assert publication_text(content,platform)==body
        assert title not in publication_text(content,platform)


def test_moments_article_shape_is_rejected_with_bounded_rewrite():
    calls=[]
    async def model(instruction,data,max_tokens=0,schema=None,**kwargs):
        calls.append(schema.__name__)
        if schema.__name__=='ArticlePlan':return {'format':'personal-share','thesis':'任务','target_reader':'学生','hook':'你好','evidence_ids':['s1']},{}
        return {'title':'内部作品名','body':'## 这是标题\n\n- 参数介绍','strategy':'长文章'},{}
    with pytest.raises(ValueError,match='平台结构'):
        asyncio.run(generate_platform({'platform':'朋友圈'},{'name':'产品'},[{'id':'s1'}],model))
    assert calls==['ArticlePlan','MomentsDraft','MomentsDraft']


def test_planner_conflict_stops_before_writer():
    async def model(instruction,data,max_tokens=0,schema=None,**kwargs):
        assert schema.__name__=='ArticlePlan'
        return {'format':'explainer','conflicts':['同配置参数冲突：s1 / s2']},{}
    content,_=asyncio.run(generate_platform({'platform':'公众号'},{'name':'产品'},[{'id':'s1'},{'id':'s2'}],model))
    assert content['conflicts'] and not content['body']


def test_generated_marketing_body_decodes_double_escaped_line_breaks():
    async def model(instruction,data,max_tokens=0,schema=None,**kwargs):
        if schema.__name__=='ArticlePlan':return {'format':'explainer','thesis':'学习选本','evidence_ids':['s1']},{}
        return {'title':'学习选本','intro':'先看任务','body':r'## 看学习任务\n\n阅读课件。\n\n## 看编程任务\n\n核对软件。','cta':'到店体验'},{}
    content,_=asyncio.run(generate_platform({'platform':'公众号'},{'name':'产品'},[{'id':'s1'}],model))
    assert '\n' in content['body'] and r'\n' not in content['body']


def test_app_generation_uses_platform_pipeline_and_saves_moments_without_article_fields(clients,monkeypatch):
    import json
    from backend import ai
    from backend.db import Session,Job,Work
    from backend.knowledge import knowledge
    admin,*_=clients;p=knowledge.products()[0];source=knowledge.product(p['id'])['facts']['id'];seen=[]
    actor=admin.get('/api/me').json()['user']['id']
    with Session() as s:
        job=Job(kind='generate',actor_id=actor,status='running');s.add(job);s.commit();jid=job.id
    async def model(instruction,data,max_tokens=0,schema=None,**kwargs):
        seen.append(schema.__name__)
        if schema.__name__=='ArticlePlan':return {'format':'personal-share','thesis':'按任务选本','target_reader':'学生','hook':'先核对软件','evidence_ids':[source]},{}
        if schema.__name__=='MomentsDraft':return {'title':'内部作品名','body':p['name']+'可以作为学习选本的了解对象。带着专业课的软件清单到店，先核对系统和配置，再看看键盘、屏幕是否适合自己的习惯。','claims':[{'text':p['name'],'source_id':source}]},{}
        if schema.__name__ in {'VerificationResult','PlatformVerificationResult'}:return {'issues':[],'pending':[],'claims':[{'text':p['name'],'source_id':source}]},{}
        return {'title':'旧流程','body':'旧流程'},{}
    monkeypatch.setattr(ai,'model_json',model)
    result=asyncio.run(ai.generate({'workflow':'platform-v1','platform':'朋友圈','product_id':p['id'],'audience':'学生','scene':'学习和写代码','goal':'咨询'},jid))
    assert seen==['ArticlePlan','MomentsDraft','PlatformVerificationResult']
    with Session() as s:
        content=json.loads(s.get(Work,result['work_id']).content)
    assert content['content_format']=='personal-share' and content['images']==[]
    assert not content['intro'] and not content['cta'] and not content['tags']


def test_publication_html_has_distinct_layout_and_only_managed_images():
    from backend.publication import render_publication
    content={'title':'内部作品名','intro':'导语','body':'## 先看学习任务\n\n正文 <script>alert(1)</script>\n\n## 再看编程任务\n\n建议','cta':'到店体验','tags':[],
             'images':[{'id':'owned','name':'产品.png','caption':'同型号产品图','after_block':1}]}
    wechat=render_publication(content,'公众号')
    assert 'data-platform="公众号"' in wechat and 'style=' in wechat and '<script>' not in wechat
    assert '/api/knowledge/images/owned' in wechat
    moments=render_publication({**content,'body':'自然短文','images':[]},'朋友圈')
    assert '内部作品名' not in moments and '导语' not in moments and '自然短文' in moments
