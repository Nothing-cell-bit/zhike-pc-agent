"""Admin model overrides in the private persistent volume, outside the DB."""
import asyncio
import ipaddress
import json
import os
import socket
import tempfile
import threading
from dataclasses import dataclass, field
from urllib.parse import urlsplit

import httpx
from . import config

CONFIG_PATH = config.DATA / 'private' / 'text-model.json'
_lock = threading.RLock()


@dataclass(frozen=True)
class ModelConfig:
    base: str
    model: str
    key: str = field(repr=False)
    source: str = 'environment'
    disable_thinking: bool = False

    def public(self):
        return {'base_url': self.base, 'model': self.model,
                'key_configured': bool(self.key), 'configured': bool(self.base and self.key),
                'source': self.source, 'disable_thinking': self.disable_thinking}


def get_config():
    with _lock:
        if CONFIG_PATH.exists():
            try:
                value = json.loads(CONFIG_PATH.read_text(encoding='utf-8'))
                return ModelConfig(value['base_url'], value['model'], value['api_key'], 'custom', value.get('disable_thinking', False))
            except (ValueError, KeyError, OSError, TypeError):
                raise ValueError('私有模型配置无法读取，请管理员重新保存配置') from None
        return ModelConfig(config.TEXT_BASE, config.TEXT_MODEL, config.TEXT_KEY,
                           disable_thinking='qwen' in config.TEXT_MODEL.lower())


def validate_base(value):
    if not isinstance(value, str) or not value or len(value) > 512 or any(c.isspace() or ord(c) < 32 for c in value):
        raise ValueError('请填写有效的公网 HTTPS API 基础地址')
    try:
        url = urlsplit(value)
        if (url.scheme != 'https' or not url.hostname or url.username or url.password
                or url.port not in (None, 443) or url.query or url.fragment or '\\' in value
                or url.path.rstrip('/').endswith(('/chat/completions', '/models'))):
            raise ValueError()
    except ValueError:
        raise ValueError('请填写公网 HTTPS 基础地址（443端口），不要包含密钥、查询参数或 /chat/completions') from None
    return value.rstrip('/')


def public_address(base):
    hostname = urlsplit(validate_base(base)).hostname
    try:
        addresses = socket.getaddrinfo(hostname, 443, type=socket.SOCK_STREAM)
        if not addresses or any(not ipaddress.ip_address(item[4][0]).is_global for item in addresses):
            raise ValueError('模型地址必须解析到公网，不能使用本机、内网或元数据服务地址')
        return addresses[0][4][0], hostname
    except (socket.gaierror, OSError):
        raise ValueError('模型域名无法解析，请检查公网地址') from None


def save_config(value):
    if not isinstance(value, dict):
        raise ValueError('请填写模型基础地址、名称和 API Key')
    base = validate_base(value.get('base_url'))
    model = value.get('model')
    key = value.get('api_key', '')
    disable_thinking = value.get('disable_thinking', False)
    if not isinstance(disable_thinking, bool):
        raise ValueError('Qwen 思考模式开关必须为布尔值')
    if not isinstance(model, str) or not model.strip() or len(model) > 160 or any(ord(c) < 32 for c in model):
        raise ValueError('请填写有效模型名称（最多160个字符）')
    if not isinstance(key, str) or len(key) > 8192 or any(ord(c) < 32 for c in key):
        raise ValueError('API Key 格式无效')
    public_address(base)
    with _lock:
        previous = get_config()
        key = key.strip()
        if not key:
            if base != previous.base:
                raise ValueError('更换服务地址时必须重新填写 API Key，避免旧密钥发送到其他服务')
            key = previous.key
        if not key:
            raise ValueError('首次配置必须填写 API Key')
        result = ModelConfig(base, model.strip(), key, 'custom', disable_thinking)
        CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        descriptor, temporary = tempfile.mkstemp(dir=CONFIG_PATH.parent, prefix='.text-model-')
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
                json.dump({'base_url': result.base, 'model': result.model, 'api_key': result.key,
                           'disable_thinking': result.disable_thinking}, stream)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, CONFIG_PATH)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
        return result.public()


def reset_config():
    with _lock:
        CONFIG_PATH.unlink(missing_ok=True)
        return get_config().public()


async def completion(settings, payload, timeout=100):
    payload = dict(payload)
    if settings.disable_thinking and 'qwen' in settings.model.lower():
        payload['chat_template_kwargs'] = {'enable_thinking': False}
    url = httpx.URL(settings.base + '/chat/completions')
    headers = {'Authorization': 'Bearer ' + settings.key}
    extensions = {}
    if settings.source == 'custom':
        # Pin a validated public IP on every request; preserve TLS SNI and Host.
        address, hostname = await asyncio.to_thread(public_address, settings.base)
        url = url.copy_with(host=address)
        headers['Host'] = hostname
        extensions['sni_hostname'] = hostname
    async with httpx.AsyncClient(timeout=httpx.Timeout(timeout, connect=8), trust_env=False, follow_redirects=False) as client:
        return await client.post(url, headers=headers, json=payload, extensions=extensions)


async def check_config():
    settings = get_config()
    if not settings.base or not settings.key:
        return {'ok': False, 'message': '尚未配置文本模型'}
    payload = {'model': settings.model, 'messages': [
        {'role': 'system', 'content': 'Return only a JSON object.'},
        {'role': 'user', 'content': 'Return {"ok":true}'}],
        'max_tokens': 64, 'stream': False}
    try:
        response = await completion(settings, payload, timeout=20)
        if response.status_code != 200:
            messages = {401: '模型鉴权失败，请核对 API Key', 403: '模型无访问权限', 404: '接口或模型不存在，请核对基础地址与模型名称', 429: '服务限流或额度不足'}
            return {'ok': False, 'http_status': response.status_code,
                    'message': messages.get(response.status_code, '模型请求失败，请检查服务状态')}
        content = response.json()['choices'][0]['message']['content'].strip()
        valid = isinstance(json.loads(content), dict)
        return {'ok': valid, 'http_status': 200, 'message': '模型调用成功，已返回 JSON；实际内容仍需按业务核验'}
    except ValueError:
        return {'ok': False, 'message': '地址无效或模型没有返回有效 JSON，请核对配置及模型能力'}
    except Exception:
        return {'ok': False, 'message': '模型连接失败或响应不兼容，请检查网络、服务和模型名称'}
