"""Handbook acceptance gates. All model responses in this file are offline fixtures."""
import asyncio
import io
import json
import zipfile

import pytest
from sqlalchemy import select

from backend import ai
from backend.db import Job, Session, Work
from backend.knowledge import knowledge
from .test_workflow import make_work


def test_scenario_records_unknown_stage_without_guessing():
    from backend.marketing import scenario_judgment
    result = scenario_judgment({'audience': '新生', 'scene': '课堂笔记', 'goal': '咨询', 'platform': '小红书'})
    assert result['buying_stage'] == '待确认'
    assert result['user_problem'] == '待确认'
    assert result['audience'] == '新生'


def test_scene_changes_picture_ranking_and_has_an_explanation():
    from backend.marketing import select_images
    images = [
        {'id': 'travel', 'product_id': 'pc', 'description': '轻薄机身 差旅便携', 'name': 'a.png'},
        {'id': 'study', 'product_id': 'pc', 'description': '课堂学习 手写笔记', 'name': 'b.png'},
        {'id': 'wrong', 'product_id': 'another', 'description': '课堂学习', 'name': 'c.png'},
    ]
    study = select_images(images, {'product_id': 'pc', 'scene': '课堂学习'}, '## 学习\n\n课堂笔记。', 1)
    travel = select_images(images, {'product_id': 'pc', 'scene': '差旅便携'}, '## 出差\n\n携带办公。', 1)
    assert study[0]['id'] == 'study' and travel[0]['id'] == 'travel'
    assert study[0]['selection_reason'] and study[0]['position']
    assert 0 <= study[0]['after_block'] <= 2
    assert [i['id'] for i in select_images(images, {'product_id': 'pc'}, '', 6)] == ['travel', 'study']


def test_export_has_four_sections_and_embeds_images_at_recorded_positions(clients):
    admin, *_ = clients
    wid, _ = make_work(admin)
    with Session() as s:
        w = s.get(Work, wid)
        content = json.loads(w.content)
        content['body'] = '第一段正文。\n\n第二段正文。'
        content['images'][0].update(after_block=1, position='正文第1块后', caption='课堂图片')
        w.content = json.dumps(content)
        w.brief = json.dumps({'platform': '朋友圈', 'audience': '学生', 'scene': '上课', 'goal': '咨询'})
        s.commit()
    response = admin.get(f'/api/works/{wid}/export?format=md')
    assert response.status_code == 200
    for heading in ['一、场景判断', '二、知识库依据', '三、图文软文', '四、核验结果']:
        assert heading in response.text
    assert '待确认' in response.text and '本地' in response.text
    assert response.text.index('第一段正文。') < response.text.index('![课堂图片]') < response.text.index('第二段正文。')
    page = admin.get(f'/api/works/{wid}/export?format=html').text
    assert page.index('第一段正文。') < page.index('<img') < page.index('第二段正文。')
    assert 'src="data:image/' in page
    bundle = zipfile.ZipFile(io.BytesIO(admin.get(f'/api/works/{wid}/export?format=zip').content))
    assert {'scenario.json', 'sources.json', 'verification.json', 'article.md', 'article.html'} <= set(bundle.namelist())


def test_source_conflicts_stop_generation_without_saving_article(clients, monkeypatch):
    admin, *_ = clients
    p = knowledge.products()[0]
    with Session() as s:
        j = Job(kind='generate', actor_id=admin.get('/api/me').json()['user']['id'])
        s.add(j); s.commit(); jid = j.id
    async def conflict(*args, **kwargs):
        return {'title': '不应输出', 'body': '不应保存的正文', 'conflicts': ['同配置重量存在两个冲突值']}, {}
    monkeypatch.setattr(ai, 'model_json', conflict)
    result = asyncio.run(ai.generate({'product_id': p['id'], 'audience': '学生', 'scene': '学习', 'goal': '到店', 'platform': '朋友圈'}, jid))
    assert result.get('needs_confirmation') == ['同配置重量存在两个冲突值']
    with Session() as s:
        assert s.scalar(select(Work)) is None


def test_draft_cannot_bypass_source_conflict(clients):
    admin, *_ = clients
    wid, _ = make_work(admin)
    with Session() as s:
        w = s.get(Work, wid)
        w.report = json.dumps({'status': 'needs_review', 'blocked': True, 'issues': [{'type': '资料冲突', 'text': '待人工确认'}]})
        s.commit()
    assert admin.get(f'/api/works/{wid}/export?format=md&draft=true').status_code == 409


def test_reverification_marks_conflicts_as_blocking(clients, monkeypatch):
    admin, *_ = clients
    wid, _ = make_work(admin)
    w = admin.get('/api/works/'+wid).json()
    async def conflict(*args, **kwargs):
        return {'issues': [{'type': '资料冲突', 'text': '相同配置参数矛盾'}], 'pending': [], 'claims': []}, {}
    monkeypatch.setattr(ai, 'model_json', conflict)
    report = asyncio.run(ai.verify(w['content'], w['brief']))
    assert report.get('blocked') is True


@pytest.mark.parametrize('field,value', [('title', '友商都是垃圾'), ('tags', ['全网最低']), ('caption', '100%无故障')])
def test_compliance_also_checks_tags_and_picture_captions(clients, monkeypatch, field, value):
    admin, *_ = clients
    wid, _ = make_work(admin)
    w = admin.get('/api/works/'+wid).json(); content = w['content']
    if field == 'caption': content['images'][0]['caption'] = value
    else: content[field] = value
    async def clean(*args, **kwargs):
        return {'issues': [], 'pending': [], 'claims': [{'text': '事实', 'source_id': content['sources'][0]['id']}]}, {}
    monkeypatch.setattr(ai, 'model_json', clean)
    report = asyncio.run(ai.verify(content, w['brief']))
    assert report['status'] == 'needs_review'
    assert any(i['type'] == '合规' for i in report['issues'])


def test_edit_updates_picture_placement_and_invalidates_stale_strategy(clients):
    admin, *_ = clients
    wid, iid = make_work(admin)
    response = admin.patch('/api/works/'+wid, headers={'X-Store-Request':'1'}, json={
        'expected_version': 1, 'title':'新文稿', 'body':'新的第一段。\n\n新的第二段。', 'image_ids':[iid]})
    assert response.status_code == 200
    w = admin.get('/api/works/'+wid).json()
    assert 'after_block' in w['content']['images'][0]
    assert w['content'].get('strategy_current') is False


def test_nonexistent_product_prompts_for_model_confirmation_without_calling_model(clients, monkeypatch):
    async def never(*args, **kwargs): raise AssertionError('ambiguous product must not call model')
    monkeypatch.setattr(ai, 'model_json', never)
    result = asyncio.run(ai.generate({'product_id':'想买轻薄本','audience':'学生','scene':'学习','goal':'咨询','platform':'小红书'}, 'unused'))
    assert result.get('needs_input') == ['product_id']


def test_edit_cannot_clear_source_conflict_before_reverification(clients):
    admin, *_ = clients
    wid, iid = make_work(admin)
    with Session() as s:
        w = s.get(Work,wid)
        w.report = json.dumps({'status':'needs_review','blocked':True,'issues':[{'type':'资料冲突','text':'同配置参数矛盾'}]})
        s.commit()
    admin.patch('/api/works/'+wid,headers={'X-Store-Request':'1'},json={'expected_version':1,'title':'修订稿','body':'删除争议参数。','image_ids':[iid]})
    assert admin.get(f'/api/works/{wid}/export?format=txt&draft=true').status_code == 409
    from .conftest import post
    assert post(admin, '/works/'+wid+'/compose', {'image_id':iid}).status_code == 400


def test_conflict_found_by_verifier_also_stops_generation(clients, monkeypatch):
    admin, *_ = clients
    p=knowledge.products()[0]
    with Session() as s:
        j=Job(kind='generate',actor_id=admin.get('/api/me').json()['user']['id']);s.add(j);s.commit();jid=j.id
    async def response(instruction,data,max_tokens=2400,schema=None):
        if schema is ai.GeneratedArticle:return {'title':'测试','body':'测试正文'},{}
        return {'issues':[{'type':'资料冲突','text':'同配置重量矛盾'}],'pending':[],'claims':[]},{}
    monkeypatch.setattr(ai,'model_json',response)
    result=asyncio.run(ai.generate({'product_id':p['id'],'audience':'学生','scene':'课堂','goal':'咨询','platform':'朋友圈'},jid))
    assert result['needs_confirmation']
    with Session() as s:assert s.scalar(select(Work)) is None


@pytest.mark.parametrize('body',['![假图](https://outside.test/fake.png)','<img src="https://outside.test/fake.png">'])
def test_inline_images_cannot_bypass_managed_image_sources(clients,monkeypatch,body):
    admin,*_=clients;wid,_=make_work(admin)
    with Session() as s:
        w=s.get(Work,wid);c=json.loads(w.content);c['body']=body;w.content=json.dumps(c);s.commit()
    for fmt in ['md','html','zip']:
        assert admin.get(f'/api/works/{wid}/export?format={fmt}').status_code==409
    async def clean(*args,**kwargs):return {'issues':[],'pending':[],'claims':[{'text':'事实','source_id':c['sources'][0]['id']}]},{}
    monkeypatch.setattr(ai,'model_json',clean)
    report=asyncio.run(ai.verify(c,json.loads(w.brief)))
    assert report['status']=='needs_review'
