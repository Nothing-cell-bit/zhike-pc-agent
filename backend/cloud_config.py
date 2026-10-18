"""Load a single hosting-platform secret without exposing it in logs or source."""
import json
import os

ALLOWED = {'TEXT_API_BASE', 'TEXT_API_KEY', 'IMA_OPENAPI_CLIENTID',
           'IMA_OPENAPI_APIKEY', 'CLOUD_ADMIN_USERNAME', 'CLOUD_ADMIN_PASSWORD', 'CLOUD_CACHE_SHA256'}


def apply_private_environment():
    raw = os.environ.pop('ZHIKE_PRIVATE_CONFIG', '')
    if not raw:
        return
    try:
        data = json.loads(raw)
        if not isinstance(data, dict) or not set(data).issubset(ALLOWED):
            raise ValueError()
        if any(not isinstance(v, str) or not v or len(v) > 12000 for v in data.values()):
            raise ValueError()
    except (ValueError, TypeError):
        raise ValueError('Invalid private cloud configuration; check the secret variable.') from None
    os.environ.update(data)
