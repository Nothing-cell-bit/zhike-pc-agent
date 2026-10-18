import os
from pathlib import Path
from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / '.env.ima', override=False)
load_dotenv(ROOT / '.env', override=False)
DATA = Path(os.environ.get('STORE_DATA_DIR', str(ROOT / 'data'))).resolve()
DATA.mkdir(parents=True, exist_ok=True)
TEXT_BASE = os.getenv('TEXT_API_BASE', '').rstrip('/')
TEXT_KEY = os.getenv('TEXT_API_KEY', '')
TEXT_MODEL = 'qwen3.8-27b'
IMAGE_BASE = os.getenv('MODELSCOPE_IMAGE_BASE_URL', 'https://api-inference.modelscope.cn/v1').rstrip('/')
IMAGE_KEY = os.getenv('MODELSCOPE_IMAGE_API_KEY', '')
IMAGE_MODEL = os.getenv('MODELSCOPE_IMAGE_MODEL', 'Qwen/Qwen-Image-2.1-Turbo')
IMA_CLIENT_ID = os.getenv('IMA_OPENAPI_CLIENTID', '')
IMA_API_KEY = os.getenv('IMA_OPENAPI_APIKEY', '')
MARKETING_SOURCE = os.getenv('MARKETING_KNOWLEDGE_SOURCE', 'local_zip')
