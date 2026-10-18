"""Install only an explicitly approved, hash-pinned private product cache."""
import hashlib
import io
import json
import os
import re
import shutil
import sqlite3
import stat
import zipfile
from contextlib import closing
from pathlib import Path

import httpx
from PIL import Image

IMAGE_PATH = re.compile(r'images/[0-9a-f]{64}\.(?:png|jpg|webp)')
TABLES = {'meta','documents','chunks','search','search_data','search_idx','search_content',
          'search_docsize','search_config','products','images','prices'}


def install_cache(blob, expected, data_root):
    if not re.fullmatch(r'[0-9a-f]{64}', expected or '') or hashlib.sha256(blob).hexdigest() != expected:
        raise ValueError('Private cache checksum mismatch.')
    if len(blob) > 25_000_000:
        raise ValueError('Private cache is too large.')
    knowledge = Path(data_root)/'knowledge'
    folder = knowledge/('cache-'+expected[:16])
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = archive.infolist()
        names = [e.filename for e in entries]
        if len(names) != len(set(names)) or 'index.db' not in names or len(names) > 200:
            raise ValueError('Invalid private cache file list.')
        if sum(e.file_size for e in entries) > 40_000_000:
            raise ValueError('Expanded cache is too large.')
        for entry in entries:
            if entry.filename != 'index.db' and not IMAGE_PATH.fullmatch(entry.filename):
                raise ValueError('Unapproved cache path.')
            if stat.S_ISLNK(entry.external_attr >> 16) or entry.flag_bits & 1:
                raise ValueError('Unsupported cache entry.')
        folder.mkdir(parents=True, exist_ok=True)
        for entry in entries:
            target = (folder/entry.filename).resolve()
            if not target.is_relative_to(folder.resolve()):
                raise ValueError('Cache path leaves its runtime directory.')
            target.parent.mkdir(parents=True, exist_ok=True)
            data = archive.read(entry)
            if entry.filename != 'index.db':
                if hashlib.sha256(data).hexdigest() != target.stem:
                    raise ValueError('Cache image checksum mismatch.')
                with Image.open(io.BytesIO(data)) as picture:
                    if picture.width*picture.height > 50_000_000:
                        raise ValueError('Cache image dimensions are too large.')
                    picture.verify()
            target.write_bytes(data)
    staging = folder/'index.db'
    with closing(sqlite3.connect(staging)) as db:
        db.execute('PRAGMA trusted_schema=OFF')
        objects = db.execute("SELECT type,name FROM sqlite_master WHERE type IN ('table','view','trigger')").fetchall()
        if any(kind != 'table' or name not in TABLES for kind, name in objects):
            raise ValueError('Cache contains unapproved database objects.')
        if db.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
            raise ValueError('Cache database integrity check failed.')
        if db.execute('SELECT count(*) FROM prices').fetchone()[0] != 0:
            raise ValueError('Price records are outside the approved cache scope.')
        for iid, path in db.execute('SELECT id,path FROM images').fetchall():
            if not IMAGE_PATH.fullmatch(path) or not (folder/path).is_file():
                raise ValueError('Cache image path is invalid.')
            db.execute('UPDATE images SET path=? WHERE id=?', (str((folder/path).resolve()), iid))
        db.commit()
    index = knowledge/'index.db'
    if index.exists():
        backup = knowledge/('index-before-'+expected[:12]+'.db')
        if not backup.exists():
            with closing(sqlite3.connect(index.as_uri()+'?mode=ro',uri=True)) as source:
                with closing(sqlite3.connect(backup)) as target:
                    source.backup(target)
    pending = knowledge/'index.installing'
    shutil.copyfile(staging, pending)
    pending.replace(index)
    (knowledge/'private-cache.json').write_text(json.dumps({'sha256':expected}), encoding='utf-8')


def bootstrap_private_cache():
    expected = os.getenv('CLOUD_CACHE_SHA256', '')
    if not expected:
        return
    from .config import DATA, TEXT_BASE, TEXT_KEY
    state = DATA/'knowledge/private-cache.json'
    if state.exists() and (DATA/'knowledge/index.db').exists():
        if json.loads(state.read_text())['sha256'] == expected:
            return
    try:
        chunks = []
        size = 0
        with httpx.stream('GET', TEXT_BASE.rstrip('/')+'/knowledge-cache',
                          headers={'Authorization':'Bearer '+TEXT_KEY}, timeout=90, trust_env=False) as response:
            response.raise_for_status()
            for chunk in response.iter_bytes():
                size += len(chunk)
                if size > 25_000_000:
                    raise ValueError('Cache exceeds the approved transfer limit.')
                chunks.append(chunk)
        install_cache(b''.join(chunks), expected, DATA)
    except httpx.HTTPError:
        raise ValueError('Private product cache transfer failed; existing data is preserved.') from None
