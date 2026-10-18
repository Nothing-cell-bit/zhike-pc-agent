import csv
import hashlib
import io
import zipfile

import pytest
from PIL import Image
from backend import knowledge as kb


def package(path,version='first',extra=None):
    folder='P1-产品参数库/01-产品/示例型号'
    image=io.BytesIO();Image.new('RGB',(12,8),'white').save(image,'PNG')
    files={folder+'/产品事实.md':f'# 示例型号 - 产品事实\n## 屏幕\n{version} 资料\nhttps://example.com/spec'.encode(),folder+'/图片/a.png':image.getvalue(),
      folder+'/图片/图片索引.csv':'文件名,来源页面,原始图片URL,官网图片说明\na.png,https://example.com/spec,https://example.com/a.png,示例实图\n'.encode(),
      'P1-产品参数库/00-全库横向索引/全部图片联合检索表.csv':f'本地目录,文件名,页面来源,原始图片URL,画面说明\n{folder}/图片,a.png,https://example.com/spec,https://example.com/a.png,示例实图\n'.encode(),
      'P4-报价/不能检索.md':'# 私有报价\n不能自动输出'.encode(),
      'P1-产品参数库/08-价格/官方价格快照.csv':'型号,时间,价格\n示例型号,2026-10-18,历史记录\n'.encode()}
    listing=io.StringIO();writer=csv.writer(listing);writer.writerow(['相对路径','SHA256','字节数'])
    for name,blob in files.items():writer.writerow([name,hashlib.sha256(blob).hexdigest(),len(blob)])
    files['全库文件清单_SHA256.csv']=listing.getvalue().encode('utf-8-sig')
    if extra:files.update(extra)
    with zipfile.ZipFile(path,'w') as z:
        for name,blob in files.items():z.writestr('库/'+name,blob)
    return path


@pytest.fixture
def isolated_kb(tmp_path,monkeypatch):
    monkeypatch.setattr(kb,'KNOWLEDGE',tmp_path/'knowledge')
    monkeypatch.setattr(kb,'INDEX',tmp_path/'knowledge/index.db')
    return tmp_path


def test_import_verified_versions_and_original_references(isolated_kb):
    root=isolated_kb
    first=kb.import_zip(package(root/'one.zip'))
    p=kb.knowledge.products()[0];iid=kb.knowledge.images(p['id'])[0]['id'];did=p['facts_id']
    before=kb.knowledge.image_path(iid).read_bytes()
    assert first['images']==1 and first['products']==1 and first['ima_connected'] is False
    assert not kb.knowledge.search('私有报价')
    second=kb.import_zip(package(root/'two.zip','second'))
    assert first['version']!=second['version']
    assert 'first' in kb.knowledge.document(did)['body']
    assert kb.knowledge.image_path(iid).read_bytes()==before
    assert 'second' in kb.knowledge.product(p['id'])['facts']['body']


@pytest.mark.parametrize('extra',[{'../escape.md':b'bad'},{'unlisted.md':b'no checksum'},{'bad.exe':b'executable'},{'P1-产品参数库/01-产品/示例型号/产品事实.md':b'tampered'}])
def test_invalid_import_never_changes_current_index(isolated_kb,extra):
    root=isolated_kb
    kb.import_zip(package(root/'valid.zip'))
    original=kb.INDEX.read_bytes()
    with pytest.raises(ValueError):kb.import_zip(package(root/'invalid.zip',extra=extra))
    assert kb.INDEX.read_bytes()==original
