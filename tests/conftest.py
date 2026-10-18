import os
import tempfile
from pathlib import Path
import pytest

os.environ['STORE_DATA_DIR']=tempfile.mkdtemp(prefix='store-test-')
os.environ['TEXT_API_KEY']=''
os.environ['MODELSCOPE_IMAGE_API_KEY']=''
os.environ['IMA_OPENAPI_CLIENTID']=''
os.environ['IMA_OPENAPI_APIKEY']=''
os.environ['MARKETING_KNOWLEDGE_SOURCE']='local_zip'
from fastapi.testclient import TestClient
from sqlalchemy import delete
from backend.main import app,ph,rate
from backend.db import Base,engine,Session,User
from backend import knowledge as kb

kb.INDEX=Path(__file__).resolve().parents[1]/'data'/'knowledge'/'index.db'

@pytest.fixture
def clients():
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine);rate.clear()
    with Session() as s:
        s.add_all([User(username='admin_test',display_name='管理员',password=ph.hash('StrongTestPassword!'),role='admin'),User(username='staff_test',display_name='顾问',password=ph.hash('StrongTestPassword!'),role='staff')]);s.commit()
    with TestClient(app) as admin,TestClient(app) as staff,TestClient(app) as customer,TestClient(app) as other:
        for c,name in [(admin,'admin_test'),(staff,'staff_test')]:
            assert c.post('/api/auth/login',json={'username':name,'password':'StrongTestPassword!'},headers={'X-Store-Request':'1'}).status_code==200
        yield admin,staff,customer,other

def post(c,path,body=None):return c.post('/api'+path,json=body or {},headers={'X-Store-Request':'1'})
