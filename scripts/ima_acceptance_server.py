"""Local isolated acceptance server. Copies the business DB once, never stops an existing server."""
import os
import sqlite3
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))
TARGET=ROOT/'tmp'/'ima-live-data'
TARGET.mkdir(parents=True,exist_ok=True)

def snapshot(source,target):
    target.parent.mkdir(parents=True,exist_ok=True)
    if target.exists():return
    with sqlite3.connect(source.as_uri()+'?mode=ro',uri=True) as src:
        with sqlite3.connect(target) as dest:src.backup(dest)

snapshot(ROOT/'data'/'store.db',TARGET/'store.db')
for index in (ROOT/'data'/'knowledge').glob('index*.db'):
    if not index.name.endswith('.build.db'):snapshot(index,TARGET/'knowledge'/index.name)
os.environ['STORE_DATA_DIR']=str(TARGET)
os.environ['MARKETING_KNOWLEDGE_SOURCE']='ima_first'
os.environ['MODELSCOPE_IMAGE_API_KEY']=''
from backend.main import app

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=8768,log_level='warning')
