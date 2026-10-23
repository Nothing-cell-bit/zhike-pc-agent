"""Local-only UI viewer for a completed isolated acceptance DB (no production writes)."""
import os
import sys
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
if len(sys.argv) not in {2,3}:raise SystemExit('Provide the isolated dialogue-live-* folder')
folder=Path(sys.argv[1]).resolve()
if not folder.name.startswith('dialogue-live-') or not (folder/'store.db').is_file():raise SystemExit('Not an isolated acceptance DB')
os.environ['STORE_DATA_DIR']=str(folder)
from backend import knowledge as kb,dialogue_catalog
kb.INDEX=ROOT/'data'/'knowledge'/'index.db'
dialogue_catalog.CACHE_ROOT=ROOT/'data'/'ima'
from backend.db import Session,User,Conversation,init_db
from backend.main import app,ph
from sqlalchemy import select
import uvicorn
init_db()
with Session() as s:
    user=s.scalar(select(User).where(User.username=='dialogue_acceptance'))
    if not user:
        user=User(username='dialogue_acceptance',display_name='多轮验收客服（隔离）',password=ph.hash('IsolatedDialogueCheck2026!'),role='admin');s.add(user);s.flush()
    for conv in s.scalars(select(Conversation)):conv.owner_id=user.id;conv.status='active'
    s.commit()
uvicorn.run(app,host='127.0.0.1',port=int(sys.argv[2]) if len(sys.argv)==3 else 8766)
