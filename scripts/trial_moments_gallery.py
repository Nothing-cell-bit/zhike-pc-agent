"""Run one explicitly configured real Moments album; never resubmit unknown requests."""
import argparse
import asyncio
import json
import sys
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1];sys.path.insert(0,str(ROOT))
from backend.db import Session,Work,Job
from backend.moments_gallery import prepare_gallery,run_moments_gallery,latest_gallery


async def run(work_id,count,mode,scene):
    with Session() as session:
        work=session.get(Work,work_id)
        if not work:raise ValueError('作品不存在')
        payload=prepare_gallery(work,count,mode,scene)
        job=Job(kind='moments_gallery',actor_id=work.actor_id,target_id=work_id,payload=json.dumps(payload,ensure_ascii=False));session.add(job);session.commit();jid=job.id
    print(json.dumps({'event':'started','job_id':jid,'count':count,'originals':payload['original_count'],'ai_images':payload['ai_count']}),flush=True)
    async def monitor(task):
        previous=''
        while not task.done():
            with Session() as session:
                job=session.get(Job,jid);value={'status':job.status,'step':job.step,'result':json.loads(job.result or '{}'),'error':job.error}
            current=json.dumps(value)
            if current!=previous:print(current,flush=True);previous=current
            await asyncio.sleep(3)
    for _ in range(3):
        task=asyncio.create_task(run_moments_gallery(jid));await asyncio.gather(task,monitor(task))
        with Session() as session:
            job=session.get(Job,jid);status=job.status
        if status!='waiting_remote':break
    with Session() as session:
        job=session.get(Job,jid);work=session.get(Work,work_id)
        record={'job_id':jid,'status':job.status,'step':job.step,'error':job.error,'result':json.loads(job.result or '{}'),'gallery':latest_gallery(session,work)}
    target=ROOT/'output/platform-content-preview/moments-gallery-result.json';target.write_text(json.dumps(record,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({'event':'finished','status':record['status'],'error':record['error'],'result':record['result']}),flush=True)


if __name__=='__main__':
    parser=argparse.ArgumentParser();parser.add_argument('--work-id',required=True);parser.add_argument('--count',type=int,choices=[1,3,6,9],default=9);parser.add_argument('--mode',choices=['original','mixed','ai'],default='mixed');parser.add_argument('--scene',required=True);args=parser.parse_args()
    asyncio.run(run(args.work_id,args.count,args.mode,args.scene))
