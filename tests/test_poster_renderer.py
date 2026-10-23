import pytest
from PIL import Image

from backend.poster_renderer import build_html,poster_copy,render_poster
from .conftest import post
from .test_workflow import make_work


def test_poster_uses_only_sourced_claims_and_keeps_qualifiers():
    content={'title':'到店选本：先核对使用需求','sources':[{'id':'s1'}],
             'claims':[{'text':'无依据的宣传','source_id':'unknown'},
                       {'text':'MateBook 标准版支持背光，SE版不支持','source_id':'s1'}]}
    copy=poster_copy(content,'MateBook')
    assert copy['headline']=='先核对使用需求'
    assert copy['highlights']==['标准版支持背光，SE版不支持']


def test_poster_html_escapes_copy_and_uses_embedded_images(tmp_path):
    product=tmp_path/'product.png';Image.new('RGBA',(20,30),'red').save(product)
    original=product.read_bytes()
    content={'title':'<script>alert(1)</script>','intro':'<img src="https://example.com">','cta':'a & b'}
    document,copy=build_html(content,'产品',product,product,(960,1280),'ember','来源')
    assert '<script>alert(1)</script>' not in document
    assert '&lt;script&gt;' in document and 'a &amp; b' in document
    assert 'src="https://' not in document
    assert document.count('src="data:image/png;base64,')==2
    assert product.read_bytes()==original
    with pytest.raises(ValueError,match='风格'):
        build_html(content,'产品',product,None,(960,1280),'unknown','来源')


def test_unknown_poster_style_is_rejected(clients):
    admin,*_=clients;wid,iid=make_work(admin)
    assert post(admin,f'/works/{wid}/compose',{'image_id':iid,'style':'unknown'}).status_code==422


def test_long_copy_exports_as_a_real_png(tmp_path):
    product=tmp_path/'product.png';Image.new('RGBA',(900,400),'blue').save(product)
    output=tmp_path/'poster.png'
    content={'title':'按学习和办公需求核对配置，'+('先体验再决定。'*20),'cta':'欢迎到店体验，'+('核对你的软件与课程需求。'*8),'intro':'没有卖点依据时保留导语。'}
    metadata=render_poster(content,'测试产品',product,None,(960,1280),'studio','本地知识库',output)
    assert metadata['poster_copy']['headline']==content['title']
    with Image.open(output) as image:
        assert image.size==(960,1280) and image.getpixel((0,0))!=image.getpixel((480,640))
    box=metadata['layout']['product']
    assert (box[2]-box[0])/(box[3]-box[1])==pytest.approx(900/400,rel=.01)


def test_missing_browser_explains_install_step(tmp_path,monkeypatch):
    from contextlib import contextmanager
    from types import SimpleNamespace
    import playwright.sync_api as playwright
    def missing(**kwargs):raise playwright.Error('test browser is missing')
    @contextmanager
    def fake_runtime():yield SimpleNamespace(chromium=SimpleNamespace(launch=missing))
    monkeypatch.setattr(playwright,'sync_playwright',fake_runtime)
    product=tmp_path/'product.png';Image.new('RGB',(10,10),'red').save(product)
    with pytest.raises(ValueError,match='playwright install chromium'):
        render_poster({'title':'标题'},'产品',product,None,(960,1280),'studio','来源',tmp_path/'out.png')


def test_source_package_includes_template_and_license():
    from pathlib import Path
    from scripts.prepare_submission import public_files
    files=public_files(Path(__file__).resolve().parents[1])
    assert 'backend/poster_templates/product.html' in files
    assert 'third_party/poster-maker/LICENSE' in files
