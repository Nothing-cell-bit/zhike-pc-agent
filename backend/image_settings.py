"""Private, live configuration for ModelScope-compatible asynchronous images."""
import asyncio
import hashlib
import json
import os
import re
import tempfile
import threading
from dataclasses import dataclass,field

import httpx
from . import config
from .model_settings import public_address,validate_base

CONFIG_PATH=config.DATA/'private'/'image-model.json'
_lock=threading.RLock()


@dataclass(frozen=True)
class ImageConfig:
    base:str
    model:str
    key:str=field(repr=False)
    source:str='environment'

    @property
    def identity(self):
        return hashlib.sha256(json.dumps([self.base,self.model,self.key]).encode()).hexdigest()

    def public(self):
        return {'base_url':self.base,'model':self.model,'key_configured':bool(self.key),
                'configured':bool(self.base and self.key),'source':self.source,'protocol':'modelscope_async'}


def get_config(*,base=None,model=None,key=None):
    with _lock:
        if CONFIG_PATH.exists():
            try:
                value=json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
                return ImageConfig(value['base_url'],value['model'],value['api_key'],'custom')
            except (ValueError,KeyError,TypeError,OSError):
                raise ValueError('私有图片配置无法读取，请管理员恢复默认后重新配置') from None
        return ImageConfig(config.IMAGE_BASE if base is None else base,
                           config.IMAGE_MODEL if model is None else model,
                           config.IMAGE_KEY if key is None else key)


def save_config(value):
    if not isinstance(value,dict):raise ValueError('请填写图片基础地址、模型名称和 API Key')
    base=validate_base(value.get('base_url'))
    if base.endswith(('/images/generations','/images/edits','/tasks')):
        raise ValueError('请填写图片 API 基础地址，不要附加 /images/generations 或 /tasks')
    model=value.get('model');key=value.get('api_key','')
    if not isinstance(model,str) or not model.strip() or len(model)>160 or any(ord(c)<32 for c in model):
        raise ValueError('请填写有效图片模型名称（最多160个字符）')
    if not isinstance(key,str) or len(key)>8192 or any(ord(c)<32 for c in key):
        raise ValueError('图片 API Key 格式无效')
    public_address(base)
    with _lock:
        previous=get_config();key=key.strip()
        if not key:
            if base!=previous.base:raise ValueError('更换图片服务地址时必须重新填写 API Key')
            key=previous.key
        if not key:raise ValueError('首次配置图片服务必须填写 API Key')
        result=ImageConfig(base,model.strip(),key,'custom')
        CONFIG_PATH.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
        descriptor,temporary=tempfile.mkstemp(dir=CONFIG_PATH.parent,prefix='.image-model-')
        try:
            with os.fdopen(descriptor,'w',encoding='utf-8') as stream:
                json.dump({'base_url':result.base,'model':result.model,'api_key':result.key},stream)
                stream.flush();os.fsync(stream.fileno())
            os.replace(temporary,CONFIG_PATH)
        finally:
            if os.path.exists(temporary):os.unlink(temporary)
        return result.public()


def reset_config():
    with _lock:
        CONFIG_PATH.unlink(missing_ok=True)
        return get_config().public()


def bind_job(payload,settings,remote=False):
    """Persist only a fingerprint. Never send an old task ID to a new account."""
    previous=payload.get('_image_service_id')
    if previous and previous!=settings.identity:
        raise ValueError('图片服务配置已变更，请恢复原配置后续查，或新建图片任务')
    if not previous and remote and settings.source!='environment':
        raise ValueError('历史任务的图片配置无法确认，请恢复部署默认配置后续查')
    if payload.get('model') and payload['model']!=settings.model:
        raise ValueError('图片模型配置已变更，请重新新建图片任务')
    payload['_image_service_id']=settings.identity
    payload['model']=settings.model


class ServiceClient:
    def __init__(self,settings,timeout):self.settings=settings;self.timeout=timeout
    async def __aenter__(self):
        self.client=httpx.AsyncClient(timeout=self.timeout,trust_env=False,follow_redirects=False)
        await self.client.__aenter__();return self
    async def __aexit__(self,*args):return await self.client.__aexit__(*args)
    async def _request(self,method,url,**kwargs):
        settings=self.settings
        if not isinstance(url,str) or not url.startswith(settings.base+'/'):
            raise ValueError('图片接口地址与保存配置不一致')
        path=url[len(settings.base):]
        allowed=method=='POST' and path=='/images/generations' or method=='GET' and path=='/models'
        if method=='GET' and path.startswith('/tasks/'):
            identifier=path[len('/tasks/'):]
            allowed=bool(re.fullmatch(r'[A-Za-z0-9_.:-]{1,256}',identifier)) and identifier not in {'.','..'}
        if not allowed:raise ValueError('图片服务请求路径无效')
        target=httpx.URL(url);headers={**kwargs.pop('headers',{}),'Authorization':'Bearer '+settings.key}
        extensions={}
        if settings.source=='custom':
            address,hostname=await asyncio.to_thread(public_address,settings.base)
            target=target.copy_with(host=address);headers['Host']=hostname;extensions['sni_hostname']=hostname
        response=await getattr(self.client,method.lower())(target,headers=headers,extensions=extensions,**kwargs)
        if response.status_code>=400:
            message='email verification required' if 'email verification' in response.text.lower() else '图片服务拒绝请求'
            return httpx.Response(response.status_code,json={'errors':{'message':message}},request=response.request)
        if settings.key and settings.key in response.text:
            raise ValueError('图片服务响应含敏感凭证，已停止处理')
        return response
    async def post(self,url,**kwargs):return await self._request('POST',url,**kwargs)
    async def get(self,url,**kwargs):return await self._request('GET',url,**kwargs)


def client(settings,timeout):return ServiceClient(settings,timeout)


async def check_config():
    settings=get_config()
    if not settings.base or not settings.key:return {'ok':False,'message':'尚未配置图片服务'}
    try:
        async with client(settings,httpx.Timeout(15,connect=8)) as connection:
            response=await connection.get(settings.base+'/models')
        status=response.status_code
        if status in {404,405}:
            return {'ok':None,'http_status':status,'message':'该接口不提供模型列表，无法通过只读测试确认；请用实际生图任务验证'}
        if status!=200:
            messages={401:'图片服务鉴权失败，请检查 API Key',403:'图片服务访问被拒绝，请检查账号权限',429:'图片服务限流，请稍后重试'}
            return {'ok':False,'http_status':status,'message':messages.get(status,'图片服务请求失败，请检查服务状态')}
        body=response.json();models=body.get('data',[]) if isinstance(body,dict) else []
        if not isinstance(models,list):raise ValueError()
        listed=any(isinstance(model,dict) and model.get('id')==settings.model for model in models)
        return {'ok':True if listed else None,'http_status':200,'message':
                '图片服务鉴权及模型目录检查通过；生图权限、额度和参考图能力仍需实际任务验证' if listed else
                '接口已响应，但目录未列出所填图片模型；部分服务只列文本模型，请在实际生图任务中验证'}
    except ValueError:
        return {'ok':False,'message':'图片服务地址或模型目录响应无效，请检查公网地址与接口协议'}
    except Exception:
        return {'ok':False,'message':'无法连接图片服务，请检查基础地址、网络和服务状态'}
