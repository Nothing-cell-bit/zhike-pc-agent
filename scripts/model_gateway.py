"""Local-only authenticated relay for the approved temporary Cloudflare tunnel."""
import asyncio
import json
import secrets
import time
from collections import deque
from pathlib import Path

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse, Response, FileResponse

ROOT = Path(__file__).resolve().parents[1]


def create_app(config, transport=None):
    app = FastAPI(docs_url=None, redoc_url=None, openapi_url=None)
    pending = asyncio.Semaphore(2)
    recent = deque()

    @app.get('/health')
    async def health():
        return {'ready':True}

    @app.api_route('/v1/{path:path}', methods=['GET','POST'])
    async def relay(path, request: Request):
        supplied = request.headers.get('authorization', '')
        if not secrets.compare_digest(supplied.encode(), ('Bearer '+config['token']).encode()):
            return JSONResponse({'detail':'需要有效网关凭证'}, 401)
        if (request.method, path) == ('GET','knowledge-cache'):
            cache = config.get('knowledge_cache')
            if not cache or not Path(cache).is_file():
                return JSONResponse({'detail':'未配置私有产品缓存'}, 404)
            return FileResponse(cache, media_type='application/zip', filename='knowledge-cache.zip',
                                headers={'Cache-Control':'no-store'})
        if (request.method, path) not in {('GET','models'), ('POST','chat/completions')}:
            return JSONResponse({'detail':'接口未开放'}, 404)
        now = time.monotonic()
        while recent and recent[0] < now-60:
            recent.popleft()
        if len(recent) >= 30:
            return JSONResponse({'detail':'请求过于频繁，请稍后重试'}, 429)
        recent.append(now)
        chunks = []
        size = 0
        async for chunk in request.stream():
            size += len(chunk)
            if size > 250000:
                return JSONResponse({'detail':'请求过大'}, 413)
            chunks.append(chunk)
        body = b''.join(chunks)
        if request.method == 'POST':
            try:
                payload = json.loads(body)
                tokens = payload.get('max_tokens', 4096)
                if payload.get('model') != 'qwen3.8-27b' or payload.get('stream'):
                    raise ValueError()
                if not isinstance(tokens, int) or not 1 <= tokens <= 8192:
                    raise ValueError()
            except (ValueError, AttributeError, TypeError):
                return JSONResponse({'detail':'仅支持指定模型的限量非流式请求'}, 400)
        async with pending:
            try:
                async with httpx.AsyncClient(timeout=180, trust_env=False, transport=transport) as client:
                    result = await client.request(request.method, config['upstream_url'].rstrip('/')+'/'+path,
                        content=body, headers={'Authorization':'Bearer '+config['upstream_key'],
                                               'Content-Type':'application/json'})
                if result.status_code >= 400:
                    return JSONResponse({'detail':'模型上游返回错误'}, result.status_code)
                if len(result.content) > 8_000_000:
                    return JSONResponse({'detail':'模型响应超过大小限制'}, 502)
                return Response(result.content, result.status_code, media_type='application/json',
                                headers={'Cache-Control':'no-store'})
            except httpx.HTTPError:
                return JSONResponse({'detail':'模型上游暂不可用'}, 502)
    return app


def from_private_file():
    config = json.loads((ROOT/'data/deployment/model-gateway.json').read_text(encoding='utf-8'))
    if not all(isinstance(config.get(k), str) and config[k] for k in ('token','upstream_url','upstream_key')):
        raise ValueError('Private gateway configuration is incomplete.')
    return create_app(config)


if __name__ == '__main__':
    import uvicorn
    uvicorn.run(from_private_file(), host='127.0.0.1', port=18739, access_log=False)
