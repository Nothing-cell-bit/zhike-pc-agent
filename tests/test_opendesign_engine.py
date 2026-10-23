import asyncio
import json

import httpx
import pytest
from PIL import Image

from backend import opendesign_engine as engine
from backend.model_settings import ModelConfig


@pytest.fixture(autouse=True)
def configured_models(monkeypatch):
    monkeypatch.setattr(engine,'get_config',lambda:ModelConfig('https://model.test/v1','test-vlm','test-key'))


def spec():
    return {'brief':'学习和编程海报','artifact_type':'poster','canvas':{'w_px':960,'h_px':1280},
            'palette':['#123b42','#fff8e8'],'composition_notes':'阳光校园书桌，产品为视觉主体',
            'layer_graph':[{'layer_id':'scene','name':'场景','kind':'background','z_index':0,'prompt':'大学书桌上的产品参考电脑'},
                           {'layer_id':'title','name':'主标题','kind':'text','z_index':1,'text':'把热爱写成代码'},
                           {'layer_id':'model','name':'产品型号','kind':'text','z_index':2,'text':'HUAWEI MateBook D 14 2024'}]}


def tool_response(calls):
    return httpx.Response(200,json={'choices':[{'finish_reason':'tool_calls','message':{'content':'','tool_calls':[
        {'id':str(index),'type':'function','function':{'name':name,'arguments':json.dumps(args)}}
        for index,(name,args) in enumerate(calls)]}}],'usage':{'prompt_tokens':10,'completion_tokens':20}})


def payload():
    return {'ratio':'3:4','design_context':{'产品型号':'HUAWEI MateBook D 14 2024','使用场景':'学习和写代码','可用产品事实':[]}}


def test_actual_upstream_planner_validates_and_compiles_design(tmp_path,monkeypatch):
    image=tmp_path/'reference.png';Image.new('RGB',(120,80),'white').save(image)
    async def complete(settings,request,timeout=100):
        assert request['tools'][0]['function']['name']=='propose_design_spec'
        return tool_response([('propose_design_spec',{'design_spec':spec()})])
    monkeypatch.setattr(engine,'completion',complete)
    design=asyncio.run(engine.plan(payload(),image,tmp_path))
    assert design['engine']=='OpenDesign'
    assert design['spec']['canvas']['w_px']==960
    assert '把热爱写成代码' in design['prompt']
    assert design['trace'][1]['tool_name']=='propose_design_spec'


def test_actual_upstream_critic_reads_both_images_before_verdict(tmp_path,monkeypatch):
    source=tmp_path/'reference.png';poster=tmp_path/'poster.png'
    Image.new('RGB',(120,80),'white').save(source);Image.new('RGB',(96,128),'blue').save(poster)
    calls=[]
    async def complete(settings,request,timeout=100):
        calls.append(request)
        if len(calls)==1:return tool_response([('read_slide_render',{'slide_id':'poster_full'}),('read_slide_render',{'slide_id':'product_reference'})])
        assert sum(part.get('type')=='image_url' for m in request['messages'] if isinstance(m['content'],list) for part in m['content'])==2
        return tool_response([('report_verdict',{'score':.91,'verdict':'pass','issues':[],'summary':'标题可读，产品一致'})])
    monkeypatch.setattr(engine,'completion',complete)
    report=asyncio.run(engine.review(payload(),{'spec':spec()},poster,source,tmp_path,1))
    assert report['verdict']=='pass' and report['review_state']=='completed'
    assert set(report['vision_images'])=={'poster_full','product_reference'}


def test_critic_cannot_pass_without_seeing_pixels(tmp_path,monkeypatch):
    source=tmp_path/'reference.png';Image.new('RGB',(20,20),'white').save(source)
    async def complete(settings,request,timeout=100):
        return tool_response([('report_verdict',{'score':1,'verdict':'pass','issues':[],'summary':'未看图'})])
    monkeypatch.setattr(engine,'completion',complete)
    report=asyncio.run(engine.review(payload(),{'spec':spec()},source,source,tmp_path,1))
    assert report['verdict']=='fail' and report['review_state']=='unavailable'


def test_provider_prompt_preserves_exact_copy_within_budget():
    design=spec();design['composition_notes']='视觉设计描述'*500
    prompt=engine.compile_prompt(design)
    assert len(prompt)<=1900 and 'HUAWEI MateBook D 14 2024' in prompt and '把热爱写成代码' in prompt


def test_planner_rejects_canvas_that_differs_from_requested_ratio(tmp_path,monkeypatch):
    image=tmp_path/'reference.png';Image.new('RGB',(20,20),'white').save(image)
    async def complete(settings,request,timeout=100):
        wrong=spec();wrong['canvas']={'w_px':500,'h_px':500}
        return tool_response([('propose_design_spec',{'design_spec':wrong})])
    monkeypatch.setattr(engine,'completion',complete)
    with pytest.raises(ValueError,match='画布'):
        asyncio.run(engine.plan(payload(),image,tmp_path))
