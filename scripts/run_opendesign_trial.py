"""Run/resume one real product poster trial; never silently create another request."""
import asyncio
import json
import shutil
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))

from backend.ai_poster import prepare_poster,run_poster
from backend.db import Asset,Job,Session,Work

JID='opendesign-trial-20261019'
WID='ea54b5d98a0141678007811c44a30af0'


async def main():
    folder=ROOT/'output/opendesign-trial';folder.mkdir(parents=True,exist_ok=True)
    with Session() as session:
        job=session.get(Job,JID)
        if not job:
            work=session.get(Work,WID)
            payload=prepare_poster(work,json.loads(work.content)['images'][0]['id'],
                '大学学习、写代码；阳光下的校园书桌，年轻、清爽、有探索感。只保留简练的标题、产品型号、到店引导。','3:4',work.version)
            # Trial copy is creative, with no additional factual product claims.
            payload['design_context'].update({'已确认文案标题':'把热爱，写成代码','到店引导':'带上你的需求，到店体验','可用产品事实':[]})
            job=Job(id=JID,kind='poster',actor_id=work.actor_id,target_id=WID,payload=json.dumps(payload,ensure_ascii=False))
            session.add(job);session.commit()
    await run_poster(JID)
    with Session() as session:
        job=session.get(Job,JID);result=json.loads(job.result)
        print('TRIAL_STATUS',job.status,job.step,flush=True)
        if result.get('asset_id'):
            asset=session.get(Asset,result['asset_id']);metadata=json.loads(asset.metadata_json)
            shutil.copyfile(asset.path,folder/'final.png')
            (folder/'final-metadata.json').write_text(json.dumps(metadata,ensure_ascii=False,indent=2),encoding='utf-8')
            print('TRIAL_RESULT',json.dumps({'asset_id':asset.id,'model':metadata['model'],'engine':metadata['design_engine'],
                'revision':metadata['design_revision'],'review':metadata['review'],'attempts':len(metadata['attempts'])},ensure_ascii=True),flush=True)
        elif job.error:print('TRIAL_ERROR',job.error,flush=True)


if __name__=='__main__':asyncio.run(main())
