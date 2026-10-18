"""Isolated review-flow browser fixtures; never uses the live database/model."""
import asyncio
import json
import os

from . import e2e_server as base
from backend import ai
from backend.db import Session, User, Work, WorkVersion
from sqlalchemy import select

original_model=ai.model_json

async def review_model(instruction,data,max_tokens=2400,schema=None):
    if schema is ai.GeneratedArticle:
        await asyncio.sleep(0.8)
        if data.get('content',{}).get('title')=='测试：自动调整失败':
            raise ValueError('测试连接失败，原稿已保留')
    return await original_model(instruction,data,max_tokens,schema)

ai.model_json=review_model
with Session() as s:
    user=s.scalar(select(User))
    product=base.kb.knowledge.products()[0]
    for title,issues in [('测试：自动调整', [{'type':'合规','text':'请删除全网最低的表述'}]),
                         ('测试：人工确认', []),('测试：自动调整失败', [])]:
        content={'title':title,'body':'选购前请核对自己的使用场景。','intro':'离线测试内容',
                 'pending':['门店活动需要确认'],'images':base.kb.knowledge.images(product['id'])[:1],
                 'sources':[],'claims':[],'product_name':product['name']}
        report={'status':'needs_review','issues':issues,'pending':['门店活动需要确认']}
        work=Work(actor_id=user.id,brief=json.dumps({'product_id':product['id'],'platform':'朋友圈','scene':'移动办公'}),
                  content=json.dumps(content,ensure_ascii=False),report=json.dumps(report,ensure_ascii=False))
        s.add(work);s.flush()
        s.add(WorkVersion(work_id=work.id,version=1,content=work.content,report=work.report))
    s.commit()

if __name__=='__main__':
    import uvicorn
    uvicorn.run(base.app,host='127.0.0.1',port=int(os.environ.get('E2E_PORT','8779')),log_level='warning')
