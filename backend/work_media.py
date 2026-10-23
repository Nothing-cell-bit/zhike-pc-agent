"""Work-scoped user pictures, separate from authoritative product knowledge."""
import hashlib
import io
import json
import warnings
from pathlib import Path
from urllib.parse import quote

from PIL import Image, ImageOps, UnidentifiedImageError
from sqlalchemy import select

from .config import DATA
from .db import Asset, Session, uid
from .knowledge import knowledge, work_images

MAX_UPLOAD_BYTES = 10 * 1024 * 1024
MAX_UPLOAD_PIXELS = 25_000_000


def uploaded_images(session, work_id):
    result = []
    for asset in session.scalars(select(Asset).where(Asset.kind == 'work_upload').order_by(Asset.created_at)):
        metadata = json.loads(asset.metadata_json)
        if metadata.get('work_id') == work_id:
            result.append(metadata['image'])
    return result


def editable_images(session, work):
    return [*work_images(json.loads(work.content), json.loads(work.brief)), *uploaded_images(session, work.id)]


def image_url(image):
    iid = image['id']
    return ('/api/assets/' if iid.startswith('upload-') else '/api/knowledge/images/') + quote(iid, safe='')


def image_path(iid, work_id):
    if not iid.startswith('upload-'):
        return knowledge.image_path(iid)
    with Session() as session:
        asset = session.get(Asset, iid)
        if not asset or asset.kind != 'work_upload' or json.loads(asset.metadata_json).get('work_id') != work_id:
            raise ValueError('本地配图不属于当前作品')
        path = Path(asset.path).resolve()
        if not path.is_relative_to(DATA / 'work-uploads') or not path.is_file():
            raise ValueError('本地配图文件不存在')
        return path


def save_upload(session, work, actor_id, data, filename):
    if len(uploaded_images(session, work.id)) >= 60:
        raise ValueError('当前作品已上传60张图片，请使用已有配图')
    try:
        with warnings.catch_warnings():
            warnings.simplefilter('error', Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data)) as source:
                if source.format not in {'JPEG', 'PNG', 'WEBP'}:
                    raise ValueError('仅支持 JPG、PNG、WebP 图片')
                if source.width * source.height > MAX_UPLOAD_PIXELS:
                    raise ValueError('图片超过2500万像素，请缩小后上传')
                if getattr(source, 'n_frames', 1) != 1:
                    raise ValueError('请上传静态图片')
                source.load()
                normalized = ImageOps.exif_transpose(source).convert('RGBA' if 'A' in source.getbands() or 'transparency' in source.info else 'RGB')
                normalized.info.clear()
                output = io.BytesIO()
                extension = '.jpg' if source.format == 'JPEG' else '.png'
                normalized.save(output, 'JPEG' if extension == '.jpg' else 'PNG', **({'quality': 95} if extension == '.jpg' else {}))
                width, height = normalized.size
    except (UnidentifiedImageError, OSError, SyntaxError, Image.DecompressionBombError, Image.DecompressionBombWarning):
        raise ValueError('图片无法读取，请选择完整的 JPG、PNG 或 WebP 文件') from None
    blob = output.getvalue()
    if len(blob) > 30 * 1024 * 1024:
        raise ValueError('图片解码后过大，请缩小后上传')
    iid = 'upload-' + uid()
    # Client filenames are display text only; never use them as filesystem/ZIP paths.
    display = ''.join(c for c in filename.replace('\\', '/').rsplit('/', 1)[-1] if c.isprintable())[:120] or '本地配图'
    image = {'id': iid, 'name': iid + extension, 'caption': display,
             'description': display, 'source_type': 'user_upload', 'source': '本地上传（用户提供）',
             'selection_reason': '用户上传的配图；画面适用性由用户确认',
             'width': width, 'height': height}
    folder = DATA / 'work-uploads'; folder.mkdir(parents=True, exist_ok=True)
    path = folder / image['name']
    path.write_bytes(blob)
    try:
        session.add(Asset(id=iid, actor_id=actor_id, kind='work_upload', path=str(path),
                          metadata_json=json.dumps({'work_id': work.id, 'image': image,
                              'sha256': hashlib.sha256(blob).hexdigest()}, ensure_ascii=False)))
        session.commit()
    except Exception:
        session.rollback(); path.unlink(missing_ok=True)
        raise
    return image
