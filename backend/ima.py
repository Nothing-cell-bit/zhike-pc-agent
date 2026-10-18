"""Read-only ima retrieval and immutable per-work evidence. Credentials never reach media hosts."""
import asyncio
import hashlib
import io
import json
import re
import uuid
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx
from PIL import Image
from .config import DATA, IMA_CLIENT_ID, IMA_API_KEY
from .marketing import select_images

CACHE_ROOT = DATA/'ima'
LIBRARY_NAME = '任德耀新建华为PC知识库'
READ_APIS = {'search_knowledge_base','get_knowledge_base','get_knowledge_list','search_knowledge','get_media_info'}


def timestamp(): return datetime.now(timezone.utc).isoformat()
def digest(blob): return hashlib.sha256(blob).hexdigest()


def save_json(path, data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_name(path.name+'.'+uuid.uuid4().hex+'.tmp')
    temp.write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    temp.replace(path)


def _record(identifier,kind):
    if not re.fullmatch('ima-'+kind+r'-[0-9a-f]{32}',identifier):raise ValueError('ima 资料编号无效')
    path=CACHE_ROOT/'records'/(identifier+'.json')
    if not path.is_file():raise ValueError('ima 来源快照缺失，请重新创建营销任务')
    return json.loads(path.read_text(encoding='utf-8'))


def image_path(identifier):
    record=_record(identifier,'img')
    filename=record.get('object','')
    if not re.fullmatch(r'[0-9a-f]{64}\.(png|jpg|webp)',filename):raise ValueError('ima 图片路径无效')
    return CACHE_ROOT/'objects'/filename


def document(identifier): return _record(identifier,'doc')['document']


def load_snapshot(snapshot_id,product_id):
    if not re.fullmatch(r'[0-9a-f]{32}',snapshot_id or ''):raise ValueError('ima 来源快照编号无效')
    path=CACHE_ROOT/'snapshots'/(snapshot_id+'.json')
    if not path.is_file():raise ValueError('ima 来源快照缺失，请重新创建营销任务')
    data=json.loads(path.read_text(encoding='utf-8'))
    if data['product']['id']!=product_id:raise ValueError('ima 快照与产品型号不匹配')
    for ref in data['sources']:
        original=document(ref['id'])
        if digest(original['body'].encode())!=ref['sha256']:raise ValueError('ima 文档完整性检查失败')
    for image in data['product']['images']:
        path=image_path(image['id'])
        if not path.is_file() or digest(path.read_bytes())!=image['sha256']:raise ValueError('ima 图片完整性检查失败')
    return data['product'],data['sources']


def connection_status():
    path=CACHE_ROOT/'connection.json'
    result=json.loads(path.read_text(encoding='utf-8')) if path.exists() else {}
    return {'configured':bool(IMA_CLIENT_ID and IMA_API_KEY),'library_name':LIBRARY_NAME,**result}


class ImaClient:
    def __init__(self,client_id=None,api_key=None,transport=None):
        self.client_id=IMA_CLIENT_ID if client_id is None else client_id
        self.api_key=IMA_API_KEY if api_key is None else api_key
        self.transport=transport

    async def __aenter__(self):
        if not self.client_id or not self.api_key:raise ValueError('ima 凭证尚未配置')
        self.http=httpx.AsyncClient(timeout=httpx.Timeout(25,connect=8),trust_env=False,follow_redirects=False,transport=self.transport)
        return self

    async def __aexit__(self,*args): await self.http.aclose()

    async def call(self,api,body):
        if api not in READ_APIS:raise ValueError('仅允许 ima 只读接口')
        try:
            r=await self.http.post('https://ima.qq.com/openapi/wiki/v1/'+api,json=body,headers={
                'ima-openapi-clientid':self.client_id,'ima-openapi-apikey':self.api_key,
                'ima-openapi-ctx':'skill_version=1.1.10','Content-Type':'application/json'})
            r.raise_for_status();result=r.json()
        except (httpx.HTTPError,ValueError):raise ValueError('ima 连接失败或响应无效，请稍后重试') from None
        if result.get('code')==200002:raise ValueError('ima 凭证鉴权失败，请检查 Client ID 和 API Key 是否对应')
        if result.get('code')!=0:
            code=result.get('code') if isinstance(result.get('code'),int) else '未知'
            reason={110021:'ima 请求频率受限',110030:'ima 共享库读取权限不足'}.get(code,'ima 读取失败')
            message=str(result.get('msg',''))[:240]
            for secret in [self.client_id,self.api_key]:
                if secret:message=message.replace(secret,'[凭证已隐藏]')
            message=re.sub(r'https?://\S+','[链接已隐藏]',message)
            raise ValueError(reason+'（错误码 '+str(code)+'）'+('：'+message if message else ''))
        if not isinstance(result.get('data'),dict):raise ValueError('ima 返回结构不完整')
        return result['data']

    async def listing(self,api,body,field):
        result=[];cursor='';seen=set()
        for _ in range(20):
            data=await self.call(api,{**body,'cursor':cursor})
            items=data.get(field,[])
            if not isinstance(items,list):raise ValueError('ima 列表结构不完整')
            result.extend(items)
            cursor=data.get('next_cursor','')
            if data.get('is_end') is True or not cursor:return result
            if cursor in seen:raise ValueError('ima 分页游标重复')
            seen.add(cursor)
        raise ValueError('ima 检索超过分页上限，请缩小范围')

    async def download(self,url_info):
        url=url_info.get('url','');parsed=urlparse(url);host=parsed.hostname or ''
        if parsed.scheme!='https' or parsed.username or parsed.password or parsed.port not in {None,443} or not (host=='ima.qq.com' or host.endswith('.myqcloud.com')):
            raise ValueError('ima 原文链接不在允许的官方存储域名内')
        headers=url_info.get('headers') or {}
        if not isinstance(headers,dict) or any(secret and secret in str(headers) for secret in [self.api_key,self.client_id]):
            raise ValueError('ima 媒体访问凭证不符合隔离要求')
        try:
            async with self.http.stream('GET',url,headers=headers) as r:
                r.raise_for_status();parts=[];size=0
                for_redirect=300<=r.status_code<400
                if for_redirect:raise ValueError('ima 媒体链接发生跳转，请重新检索')
                async for part in r.aiter_bytes():
                    size+=len(part)
                    if size>12_000_000:raise ValueError('ima 单个素材超过读取上限')
                    parts.append(part)
                return b''.join(parts)
        except httpx.HTTPError:raise ValueError('ima 原文或图片下载失败，请重新检索') from None

    async def media(self,item):
        info=await self.call('get_media_info',{'media_id':item['media_id']})
        if info.get('media_type')!=item['media_type']:raise ValueError('ima 媒体类型与目录记录不一致')
        return await self.download(info.get('url_info',{}))


class ImaProvider:
    def __init__(self,client_factory=ImaClient):self.client_factory=client_factory

    async def fetch_product(self,product,brief):
        try:
            result=await asyncio.wait_for(self._fetch(product,brief),timeout=150)
            save_json(CACHE_ROOT/'connection.json',{'connected':True,'last_success':timestamp(),'last_error':''})
            return result
        except (ValueError,TimeoutError,KeyError,TypeError) as e:
            reason='ima 检索超时' if isinstance(e,TimeoutError) else 'ima 返回结构不完整' if isinstance(e,(KeyError,TypeError)) else str(e)
            save_json(CACHE_ROOT/'connection.json',{'connected':False,'last_error':reason,'checked_at':timestamp()})
            raise ValueError(reason) from None

    async def _fetch(self,product,brief):
        snapshot_id=uuid.uuid4().hex;retrieved=timestamp();trace=[]
        async with self.client_factory() as client:
            bases=await client.listing('search_knowledge_base',{'query':LIBRARY_NAME,'limit':20},'info_list')
            matches=[x for x in bases if x.get('kb_name',x.get('name'))==LIBRARY_NAME]
            if len(matches)!=1:raise ValueError('未唯一找到指定 ima 共享知识库，请确认加入权限')
            kb=matches[0].get('kb_id',matches[0].get('id'))
            query=(product['name']+' '+brief.get('scene',''))[:200]
            hits=await client.listing('search_knowledge',{'knowledge_base_id':kb,'query':query},'info_list')
            trace.append({'action':'search','query':query,'hits':len(hits),'directory_fallback':not hits})
            async def children(folder=None):
                body={'knowledge_base_id':kb,'limit':50}
                if folder:body['folder_id']=folder
                return await client.listing('get_knowledge_list',body,'knowledge_list')
            entries=await children()
            wrappers=[x for x in entries if x.get('media_type')==99 and x.get('title')==LIBRARY_NAME]
            if len(wrappers)==1:entries=await children(wrappers[0]['media_id'])
            segments=product['path'].split('/')
            if not segments or segments[0]!='P1-产品参数库' or any(x in {'','..','.'} for x in segments):raise ValueError('产品目录映射无效')
            for segment in segments:
                match=[x for x in entries if x.get('media_type')==99 and x.get('title')==segment]
                if len(match)!=1:raise ValueError('ima 未找到唯一完整型号目录：'+segment)
                entries=await children(match[0]['media_id'])
            trace.append({'action':'exact_product_directory','path':product['path']})
            docs=[x for x in entries if x.get('media_type')==7 and x.get('title') in {'产品事实.md','卖点与限制.md','article.md'}]
            docs.sort(key=lambda x:0 if x['title']=='产品事实.md' else 1)
            if not any(x['title'] in {'产品事实.md','article.md'} for x in docs):raise ValueError('ima 该型号缺少产品事实原文')
            refs=[];doc_records=[]
            for item in docs:
                blob=await client.media(item)
                try:body=blob.decode('utf-8-sig')
                except UnicodeDecodeError:raise ValueError('ima 产品原文不是有效 UTF-8 文档') from None
                if len(body.strip())<20 or len(body)>60000:raise ValueError('ima 产品原文为空或超过长度限制')
                sha=digest(body.encode());did='ima-doc-'+digest((snapshot_id+item['media_id']+sha).encode())[:32]
                ref={'id':did,'title':item['title'],'path':product['path']+'/'+item['title'],'version':'ima-'+snapshot_id,
                     'sha256':sha,'excerpt':body,'urls':list(dict.fromkeys(re.findall(r'https?://[^\s)<>`]+',body)))[:20],
                     'source_type':'ima','knowledge_base_name':LIBRARY_NAME,'retrieved_at':retrieved,
                     'applicable_product_id':product['id'],'applicable_model':product['name'],'source_dates':list(dict.fromkeys(re.findall(r'20\d{2}-\d{2}-\d{2}',body)))}
                refs.append(ref);doc_records.append((did,{'document':{**ref,'body':body},'media_id':item['media_id'],'kb_id':kb}))
            images=[x for x in entries if x.get('media_type')==9]
            for folder in [x for x in entries if x.get('media_type')==99 and x.get('title') in {'images','商城款式图片'}]:
                images.extend(x for x in await children(folder['media_id']) if x.get('media_type')==9)
            candidates=[{'id':x['media_id'],'product_id':product['id'],'name':x['title'],'description':Path(x['title']).stem,'remote':x} for x in images]
            selected=select_images(candidates,{**brief,'product_id':product['id']},'',6)
            pictures=[];image_records=[];seen=set()
            for item in selected:
                blob=await client.media(item['remote']);sha=digest(blob)
                if sha in seen:continue
                seen.add(sha)
                try:
                    with Image.open(io.BytesIO(blob)) as im:
                        width,height=im.size;fmt=im.format;im.verify()
                    ext={'PNG':'png','JPEG':'jpg','WEBP':'webp'}[fmt]
                except Exception:raise ValueError('ima 图片文件校验失败') from None
                if width*height>50_000_000:raise ValueError('ima 图片尺寸超过限制')
                iid='ima-img-'+digest((snapshot_id+item['id']+sha).encode())[:32]
                filename=re.sub(r'[^\w.\-]','_',Path(item['name']).stem)+'.'+ext
                meta={'id':iid,'product_id':product['id'],'name':filename,'description':item['description'],
                      'source':'ima共享知识库：'+LIBRARY_NAME+' / '+product['path']+' / '+item['name'],
                      'source_type':'ima','knowledge_base_name':LIBRARY_NAME,'sha256':sha,'retrieved_at':retrieved,'width':width,'height':height,'version':'ima-'+snapshot_id}
                pictures.append(meta);image_records.append((iid,{'image':meta,'object':sha+'.'+ext,'media_id':item['id'],'kb_id':kb},blob))
            if not pictures:raise ValueError('ima 该型号没有可读取的原始图片')
        # Activate only after the complete retrieval succeeds; signed URLs are never exported.
        for did,record in doc_records:save_json(CACHE_ROOT/'records'/(did+'.json'),record)
        for iid,record,blob in image_records:
            path=CACHE_ROOT/'objects'/record['object'];path.parent.mkdir(parents=True,exist_ok=True)
            if not path.exists():path.write_bytes(blob)
            save_json(CACHE_ROOT/'records'/(iid+'.json'),record)
        p={**product,'images':pictures,'facts':{**refs[0],'body':refs[0]['excerpt']},'documents':refs}
        save_json(CACHE_ROOT/'snapshots'/(snapshot_id+'.json'),{'product':p,'sources':refs,'retrieved_at':retrieved,'trace':trace})
        return p,refs,snapshot_id


ima=ImaProvider()
