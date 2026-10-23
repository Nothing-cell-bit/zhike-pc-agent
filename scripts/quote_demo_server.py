"""Local full-chain demo site. Run with a fresh E2E_DATA_DIR below project tmp."""
import json,os,secrets,shutil
from contextlib import asynccontextmanager
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
folder=Path(os.environ['E2E_DATA_DIR']).resolve()
resume=os.environ.get('DEMO_RESUME')=='1'
if not folder.is_relative_to(ROOT/'tmp') or not folder.name.startswith('quote-demo-'):raise RuntimeError('An isolated quote-demo directory below tmp is required')
if (folder/'store.db').exists() and not resume:raise RuntimeError('Use DEMO_RESUME=1 to preserve an existing demo')
if resume and not all((folder/name).exists() for name in ['store.db','demo-catalog.db','login.json']):raise RuntimeError('Incomplete saved demo')
folder.mkdir(parents=True,exist_ok=True);os.environ['STORE_DATA_DIR']=str(folder)
from backend import ai,knowledge,model_settings,dialogue_catalog
from backend.main import app,ph
from backend.db import init_db,Session,User,Conversation
from scripts.demo_quote_rules import seed

private=ROOT/'data/private/text-model.json'
if private.exists():
    v=json.loads(private.read_text(encoding='utf-8'));configured=model_settings.ModelConfig(v['base_url'],v['model'],v['api_key'],'custom',v.get('disable_thinking',False))
else:configured=model_settings.get_config()
ai.get_config=lambda:configured
knowledge.INDEX=folder/'demo-catalog.db' if resume else ROOT/'data/knowledge/index.db'
if not resume and (ROOT/'data/ima').exists():shutil.copytree(ROOT/'data/ima',folder/'ima',dirs_exist_ok=True)
dialogue_catalog.CACHE_ROOT=folder/'ima'
if resume:
    credentials=json.loads((folder/'login.json').read_text(encoding='utf-8'))
else:
    init_db();password=secrets.token_urlsafe(24)
    with Session() as s:
        users={role:User(username='quote_demo_'+role,display_name={'staff':'报价演示客服','customer':'LLM 报价演示客户','author':'演示规则编制员','reviewer':'演示规则复核员'}[role],
                        password=ph.hash(password),role=role if role in {'staff','customer'} else 'admin') for role in ['staff','customer','author','reviewer']}
        s.add_all(users.values());s.flush()
        c=Conversation(customer_id=users['customer'].id,customer_name=users['customer'].display_name,owner_id=users['staff'].id,status='active');s.add(c);s.commit()
        credentials={role:u.username for role,u in users.items()};credentials.update(password=password,cid=c.id,customer_id=users['customer'].id,model=configured.model)
        author_id=users['author'].id;reviewer_id=users['reviewer'].id
out=ROOT/'output/quote-full-chain-20261022'
original_lifespan=app.router.lifespan_context
@asynccontextmanager
async def demo_lifespan(application):
    if not resume:await seed(ROOT,author_id,reviewer_id,out)
    (folder/'login.json').write_text(json.dumps(credentials),encoding='utf-8')
    async with original_lifespan(application):yield
app.router.lifespan_context=demo_lifespan

@app.middleware('http')
async def demo_marker(request,call_next):
    response=await call_next(request)
    response.headers['X-Demo-Only']='true'
    if response.headers.get('content-type','').startswith('text/html'):
        body=b''.join([chunk async for chunk in response.body_iterator]).decode('utf-8')
        banner='<div role="status" style="position:fixed;bottom:0;left:0;right:0;z-index:2000;background:#fff4da;color:#704718;padding:5px 12px;text-align:center;font:12px/1.5 sans-serif;pointer-events:none">演示测试站 · 所有价格与 SKU 均为模拟数据，非真实门店售价</div>'
        from fastapi.responses import HTMLResponse
        return HTMLResponse(body.replace('</body>',banner+'</body>'),status_code=response.status_code,headers={k:v for k,v in response.headers.items() if k not in {'content-length','content-type'}})
    return response
