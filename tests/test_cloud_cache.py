import hashlib
import io
import sqlite3
import zipfile
from pathlib import Path
import pytest
from backend.cloud import write_catalog
from backend.cloud_cache import install_cache


def bundle(tmp_path,extra=None,bad_image_path=None):
    index=tmp_path/'seed/index.db'
    write_catalog(index,[{'name':'测试产品','path':'P1-产品参数库/01-鸿蒙电脑/测试产品'}])
    if bad_image_path:
        with sqlite3.connect(index) as c:
            c.execute('INSERT INTO images VALUES(?,?,?,?,?,?,?,?,?,?)',('x','x',bad_image_path,'x','','','',1,1,'v'))
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as z:
        z.writestr('index.db',index.read_bytes())
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
