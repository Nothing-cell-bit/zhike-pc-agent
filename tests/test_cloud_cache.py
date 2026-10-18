import hashlib
import io
import sqlite3
import zipfile
from pathlib import Path
import pytest
from PIL import Image
from backend.cloud import write_catalog
from backend.cloud_cache import install_cache


def bundle(tmp_path,extra=None,bad_image_path=None,with_image=False):
    index=tmp_path/'seed/index.db'
    write_catalog(index,[{'name':'测试产品','path':'P1-产品参数库/01-鸿蒙电脑/测试产品'}])
    if bad_image_path:
        with sqlite3.connect(index) as c:
            c.execute('INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?)',('x','x',bad_image_path,'x','','','',1,1,'v'))
    image_data=None
    if with_image:
        output=io.BytesIO();Image.new('RGB',(2,2),'white').save(output,'PNG');image_data=output.getvalue()
        image_path='images/'+hashlib.sha256(image_data).hexdigest()+'.png'
        with sqlite3.connect(index) as c:
            pid=c.execute('select id from products').fetchone()[0]
            c.execute('INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?)',('image',pid,image_path,'sample.png','','','测试图片',2,2,'v'))
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('index.db',index.read_bytes())
        if image_data:z.writestr(image_path,image_data)
        if extra:z.writestr(extra,b'bad')
    return data.getvalue()


def test_private_cache_install_rewrites_only_valid_runtime_state(tmp_path):
    blob=bundle(tmp_path);digest=hashlib.sha256(blob).hexdigest();root=tmp_path/'runtime'
    install_cache(blob,digest,root)
    assert (root/'knowledge/index.db').is_file()
    with sqlite3.connect(root/'knowledge/index.db') as c:
        assert c.execute('select name from products').fetchone()[0]=='测试产品'
    assert not (root/'store.db').exists()


@pytest.mark.parametrize('case',['checksum','traversal','absolute_image'])
def test_private_cache_rejects_tampering_and_escaping_paths(tmp_path,case):
    blob=bundle(tmp_path,extra='../escape' if case=='traversal' else None,
        bad_image_path='/etc/passwd' if case=='absolute_image' else None)
    digest='0'*64 if case=='checksum' else hashlib.sha256(blob).hexdigest()
    with pytest.raises(ValueError):install_cache(blob,digest,tmp_path/'runtime')
    assert not (tmp_path/'runtime/knowledge/index.db').exists()


def test_cache_images_are_contained_and_old_index_is_preserved(tmp_path):
    blob=bundle(tmp_path,with_image=True);root=tmp_path/'runtime';digest=hashlib.sha256(blob).hexdigest()
    write_catalog(root/'knowledge/index.db',[{'name':'Before','path':'P1-产品参数库/01-鸿蒙电脑/Before'}])
    install_cache(blob,digest,root)
    with sqlite3.connect(root/'knowledge/index.db') as c:
        image=Path(c.execute('select path from images').fetchone()[0])
        assert image.is_relative_to(root) and image.is_file()
    assert list((root/'knowledge').glob('index-before-*.db'))


def test_private_download_verifies_bundle_and_skips_after_install(tmp_path,monkeypatch):
    import httpx
    from backend import cloud_cache,config
    blob=bundle(tmp_path);digest=hashlib.sha256(blob).hexdigest();calls=[]
    monkeypatch.setenv('CLOUD_CACHE_SHA256',digest)
    monkeypatch.setattr(config,'DATA',tmp_path/'runtime')
    monkeypatch.setattr(config,'TEXT_BASE','https://relay.example/v1')
    monkeypatch.setattr(config,'TEXT_KEY','a-test-relay-key')
    class Stream:
        def __enter__(self):return httpx.Response(200,content=blob,request=httpx.Request('GET','https://relay.example/v1/knowledge-cache'))
        def __exit__(self,*args):pass
    def stream(method,url,**kwargs):
        calls.append(url)
        assert kwargs['headers']['Authorization']=='Bearer a-test-relay-key'
        return Stream()
    monkeypatch.setattr(httpx,'stream',stream)
    cloud_cache.bootstrap_private_cache();cloud_cache.bootstrap_private_cache()
    assert calls==['https://relay.example/v1/knowledge-cache']
