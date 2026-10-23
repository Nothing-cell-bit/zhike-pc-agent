"""Read-only reception lookup, exact product scope, bounded fresh fact cache."""
import asyncio
import json
from datetime import datetime,timezone
from . import ima

TTL_SECONDS=6*3600


async def retrieve(product,query,client_factory=None):
    path=ima.CACHE_ROOT/'dialogue'/(ima.digest(product['id'].encode())+'.json')
    try:
        cached=json.loads(path.read_text(encoding='utf-8'))
        age=(datetime.now(timezone.utc)-datetime.fromisoformat(cached['retrieved_at'])).total_seconds()
        if (cached['product_id']==product['id'] and cached['product_path']==product['path'] and 0<=age<TTL_SECONDS
            and cached['sources'] and all(ima.digest(s['excerpt'].encode())==s['sha256'] for s in cached['sources'])):
            return {**cached,'status':'cached'}
    except (OSError,ValueError,KeyError,TypeError):pass
    result=await asyncio.wait_for(_fetch(product,query,client_factory or ima.ImaClient),timeout=40)
    ima.save_json(path,result)
    return {**result,'status':'retrieved'}


async def _fetch(product,query,client_factory):
    async with client_factory() as client:
        bases=await client.listing('search_knowledge_base',{'query':ima.LIBRARY_NAME,'limit':20},'info_list')
        matches=[x for x in bases if x.get('kb_name',x.get('name'))==ima.LIBRARY_NAME]
        if len(matches)!=1:raise ValueError('未唯一找到接待使用的 ima 共享库')
        kb=matches[0].get('kb_id',matches[0].get('id'))
        hits=await client.listing('search_knowledge',{'knowledge_base_id':kb,'query':(product['name']+' '+query)[:200]},'info_list')
        async def children(folder=None):
            return await client.listing('get_knowledge_list',{'knowledge_base_id':kb,'limit':50,**({'folder_id':folder} if folder else {})},'knowledge_list')
        entries=await children()
        wrapper=[x for x in entries if x.get('media_type')==99 and x.get('title')==ima.LIBRARY_NAME]
        if len(wrapper)==1:entries=await children(wrapper[0]['media_id'])
        segments=product['path'].split('/')
        if segments[0]!='P1-产品参数库' or any(s in {'','..','.'} for s in segments):raise ValueError('接待产品目录映射无效')
        for segment in segments:
            folders=[x for x in entries if x.get('media_type')==99 and x.get('title')==segment]
            if len(folders)!=1:raise ValueError('ima 未找到唯一对应型号的事实目录')
            entries=await children(folders[0]['media_id'])
        docs=[x for x in entries if x.get('media_type')==7 and x.get('title') in {'产品事实.md','article.md'}]
        if not docs:raise ValueError('ima 对应型号暂无可读事实资料')
        sources=[];retrieved=ima.timestamp()
        for item in docs[:2]:
            try:body=(await client.media(item)).decode('utf-8-sig')
            except UnicodeDecodeError:raise ValueError('ima 产品原文编码无效') from None
            if not 20<=len(body)<=60000:raise ValueError('ima 产品事实为空或过长')
            sha=ima.digest(body.encode())
            sources.append({'id':'ima-fact-'+sha[:32],'product_id':product['id'],'title':product['name']+' · '+item['title'],
                'excerpt':body,'sha256':sha,'source_type':'ima','retrieved_at':retrieved})
        return {'product_id':product['id'],'product_path':product['path'],'sources':sources,'retrieved_at':retrieved,
                'search_hits':len(hits)}
