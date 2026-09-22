from __future__ import annotations
import hashlib
import json
import os
import uuid
import time
from pathlib import Path
from datetime import datetime, timezone
import yaml


def now():
    return datetime.now(timezone.utc).isoformat()


def digest_file(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def signature(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.' + uuid.uuid4().hex + '.tmp')
    temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding='utf-8')
    try:
        for attempt in range(10):
            try:
                os.replace(temp, path)
                break
            except PermissionError:
                # Windows may briefly deny replacing a file another process just
                # opened. Never expose a partially written JSON as the target.
                if attempt == 9:
                    raise
                time.sleep(.02 * (attempt + 1))
    finally:
        temp.unlink(missing_ok=True)


def read_json(path):
    return json.loads(Path(path).read_text(encoding='utf-8-sig'))


def config(path='config.yaml'):
    path = Path(path).resolve()
    cfg = yaml.safe_load(path.read_text(encoding='utf-8'))
    cfg['project_root'] = str(path.parent)
    cfg['data_dir'] = str((path.parent / cfg['data_dir']).resolve())
    return cfg


def load_env(root):
    path = Path(root) / '.env'
    if path.exists():
        for raw in path.read_text(encoding='utf-8-sig').splitlines():
            line = raw.strip()
            if line and not line.startswith('#') and '=' in line:
                key, value = line.split('=', 1)
                os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_pages(spec, count):
    pages = set()
    for part in spec.split(','):
        span = part.strip().split('-')
        start, end = int(span[0]), int(span[-1])
        if len(span) > 2 or not (1 <= start <= end <= count):
            raise ValueError(f'Invalid page range {part}; page count={count}')
        pages.update(range(start, end + 1))
    return sorted(pages)
