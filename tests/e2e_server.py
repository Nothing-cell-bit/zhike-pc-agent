"""Isolated browser-test server. All model responses are clearly marked fixtures."""
import json
import os
import secrets
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=Path(os.environ.get('E2E_DATA_DIR',str(ROOT/'tmp'/'e2e-data'))).resolve()
if not DATA.is_relative_to((ROOT/'tmp').resolve()):raise ValueError('E2E_DATA_DIR 必须在项目 tmp 目录内')
DATA.mkdir(parents=True,exist_ok=True)
os.environ['STORE_DATA_DIR']=str(DATA)
os.environ['TEXT_API_KEY']=''
os.environ['MODELSCOPE_IMAGE_API_KEY']=''
os.environ['IMA_OPENAPI_CLIENTID']=''
os.environ['IMA_OPENAPI_APIKEY']=''
os.environ['MARKETING_KNOWLEDGE_SOURCE']='local_zip'
from backend import ai,knowledge as kb
from backend.main import app,ph
from backend.db import init_db,Session,User,Base,engine
from sqlalchemy import select

kb.INDEX=ROOT/'data'/'knowledge'/'index.db'
kb.KNOWLEDGE=ROOT/'data'/'knowledge'

async def model_fixture(instruction,data,max_tokens=2400,schema=None):
    if schema is ai.GeneratedArticle:
        return {'title':'测试夹具：学习电脑选购清单','intro':'自动化界面测试，不是真实生成结果','body':'## 先核对需求\n请到店核对使用场景和软件兼容性。','cta':'欢迎咨询','strategy':'测试平台策略','claims':[{'text':'测试引用','source_id':data['evidence'][0]['id']}]},{'total_tokens':0}
    if schema is ai.VerificationResult:return {'issues':[],'pending':[],'claims':[{'text':'测试事实','source_id':data['evidence'][0]['id']}]},{}
    if schema is ai.RequirementAnalysis:return {},{}
    return {'reply':'测试建议：请补充使用软件。','recommendations':[]},{}

ai.model_json=model_fixture
Base.metadata.drop_all(engine)
init_db()
with Session() as s:
    username='e2e_'+secrets.token_hex(4);password=secrets.token_urlsafe(24)
    s.add(User(username=username,password=ph.hash(password),display_name='自动化测试管理员',role='admin'));s.commit()
(DATA/'login.json').write_text(json.dumps({'username':username,'password':password}),encoding='utf-8')

if os.getenv('STORE_E2E_HOME_FIXTURES')=='1':
    # Explicit, isolated visual QA data; never imported into the live database.
    from datetime import datetime,timedelta,timezone
    from backend.db import Conversation,Followup,Work,WorkVersion
    today=datetime.now(timezone(timedelta(hours=8)))
    products=kb.knowledge.products()
    product=next(p for p in products if '14（鸿蒙' in p['name'])
    picture=kb.knowledge.images(product['id'])[0]
    with Session() as s:
        actor=s.scalar(select(User).where(User.username==username))
        for index,(name,purpose,title,platform) in enumerate([
            ('林同学','确认专业软件','大学新生选购清单','小红书'),
            ('陈先生','到店体验回访','差旅办公电脑怎么选','公众号'),
            ('王女士','补充选购需求','周末到店体验邀请','朋友圈')
        ]):
            c=Conversation(customer_id='visual-fixture-'+str(index),customer_name=name,status='waiting',owner_id=actor.id);s.add(c);s.flush()
            due=today.replace(hour=15+index,minute=0,second=0,microsecond=0)
            if index==2:due=(today+timedelta(days=1)).replace(hour=10,minute=0,second=0,microsecond=0)
            s.add(Followup(conversation_id=c.id,owner_id=actor.id,due_at=due.isoformat(),purpose=purpose,script='离线界面测试用跟进'))
            content={'title':title,'intro':'仅用于界面验收的测试内容','body':'这是一份离线界面测试夹具。','images':[picture],'sources':[],'claims':[]}
            work=Work(actor_id=actor.id,brief=json.dumps({'product_id':product['id'],'platform':platform,'scene':'测试场景'}),content=json.dumps(content,ensure_ascii=False),report=json.dumps({'status':'unchecked'}),updated_at=(today-timedelta(days=index)).isoformat());s.add(work);s.flush()
            s.add(WorkVersion(work_id=work.id,version=1,content=work.content,report=work.report))
        s.commit()

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=int(os.environ.get('E2E_PORT','8766')),log_level='warning')
