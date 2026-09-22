"""Authenticated local retrieval; signed, allow-listed original PDF images."""
from __future__ import annotations

from contextlib import asynccontextmanager
import hashlib
import hmac
import math
import os
from pathlib import Path
import threading
import time
from urllib.parse import quote, parse_qsl

from fastapi import Depends, FastAPI, Header, HTTPException, Request
from starlette.concurrency import run_in_threadpool
from fastapi.responses import FileResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .common import load_env, read_json
from .corpus import DOMAINS
from .hybrid import HybridSearch

ROUTES = {k: [k] for k in DOMAINS}
ROUTES.update({'projects_finance': ['projects', 'finance'], 'equipment_finance': ['equipment', 'finance'],
               'procurement_master': ['procurement', 'master_ops'], 'internal_funds': ['internal', 'funds'],
               'finance_funds': ['finance', 'funds']})


class SearchRequest(BaseModel):
    model_config = ConfigDict(extra='forbid')
    query: str = Field(min_length=1, max_length=1000)
    route: str = ''
    source_id: str = Field(default='', max_length=64)
    section_prefix: str = Field(default='', max_length=100)
    kind: str = 'detail'
    top_k: int = Field(default=6, ge=1, le=20)


def create_app(cfg, engine=None):
    load_env(cfg['project_root'])
    key = os.getenv('LOCAL_RETRIEVAL_API_KEY', '')
    public_url = os.getenv('LOCAL_RETRIEVAL_URL', '').rstrip('/')
    if len(key) < 32 or not public_url.startswith(('http://', 'https://')):
        raise ValueError('Configure LOCAL_RETRIEVAL_API_KEY (32+ chars) and LOCAL_RETRIEVAL_URL in .env')
    root = Path(cfg['data_dir']).resolve()
    lock = threading.Lock()
    retrieval_cfg = cfg.get('retrieval_service', {})
    max_requests = int(retrieval_cfg.get('max_pending_requests', 8))
    queue_wait = float(retrieval_cfg.get('queue_wait_seconds', 60))
    if max_requests < 1 or not math.isfinite(queue_wait) or queue_wait <= 0:
        raise ValueError('Retrieval queue capacity and wait timeout must be positive')
    # Keep one model invocation at a time, but admit a bounded number of callers
    # while it finishes. Two seconds was shorter than a normal CPU rerank.
    admission = threading.BoundedSemaphore(max_requests)
    state = {'engine': engine, 'assets': set(), 'inputs': None}

    def source_stamp():
        return tuple((root / p).stat().st_mtime_ns for p in
                     ('full-export/manifest.json', 'process-navigation/catalog.json', 'local-index/current.json'))

    def load():
        previous = state['engine']
        if previous is None:
            current = HybridSearch(cfg)
            current.warm()
        elif state['inputs'] is None:
            current = previous
        else:
            current = HybridSearch(cfg, encoder=previous.encoder, reranker=previous.reranker)
        state.update(engine=current, inputs=source_stamp(),
                     assets={im['path'] for d in current.docs for im in d['images']})

    @asynccontextmanager
    async def lifespan(app):
        load()
        yield

    app = FastAPI(title='Local operations retrieval', docs_url=None, redoc_url=None,
                  openapi_url=None, lifespan=lifespan)

    def authenticate(authorization: str = Header(default='')):
        if not hmac.compare_digest(authorization, 'Bearer ' + key):
            raise HTTPException(401, 'Unauthorized')

    def asset_signature(path, expires):
        return hmac.new(key.encode(), f'{path}\n{expires}'.encode(), hashlib.sha256).hexdigest()

    def image_link(im, source_name):
        expires = int(time.time()) + 3600
        path = im['path']
        return f"![{source_name}，PDF 第 {im['page']} 页]({public_url}/assets/{quote(path, safe='/')}?expires={expires}&signature={asset_signature(path, expires)})"

    def run(body):
        if body.route and body.route not in ROUTES:
            raise HTTPException(422, 'Unknown business route')
        if body.kind not in ('detail', 'overview'):
            raise HTTPException(422, 'Unknown content kind')
        if not body.query.strip():
            raise HTTPException(422, 'Empty query')
        if not admission.acquire(blocking=False):
            raise HTTPException(429, 'Retrieval queue is full; retry later', headers={'Retry-After': '5'})
        acquired = False
        try:
            acquired = lock.acquire(timeout=queue_wait)
            if not acquired:
                raise HTTPException(429, 'Retrieval queue wait timed out; retry later', headers={'Retry-After': '5'})
            if state['inputs'] != source_stamp():
                try: load()
                except ValueError: raise HTTPException(409, 'Index is stale; run ops-rag index') from None
            result = state['engine'].search(body.query, body.top_k, domains=ROUTES.get(body.route),
                source_id=body.source_id, section_prefix=body.section_prefix, kind=body.kind)
            for d in result['results']:
                images = [image_link(im, d['source_name']) for im in d.pop('images')]
                d['content'] += '\n\n' + '\n'.join(images)
                d['image_count'] = len(images)
            return result
        finally:
            if acquired:
                lock.release()
            admission.release()

    @app.get('/health')
    def health():
        return {'status': 'ready' if state['engine'] else 'starting', 'inference': 'local_cpu'}

    @app.post('/search', dependencies=[Depends(authenticate)])
    def search(body: SearchRequest):
        return run(body)

    @app.post('/search-form', dependencies=[Depends(authenticate)])
    async def search_form(request: Request):
        # Dify encodes form fields safely even for quotes/newlines in user input.
        if request.headers.get('content-type', '').split(';')[0] != 'application/x-www-form-urlencoded':
            raise HTTPException(415, 'Expected URL-encoded form')
        raw = await request.body()
        if len(raw) > 20000:
            raise HTTPException(413, 'Request too large')
        try:
            pairs = parse_qsl(raw.decode('utf-8'), keep_blank_values=True, max_num_fields=10)
            if len(dict(pairs)) != len(pairs): raise ValueError('Duplicate fields')
            body = SearchRequest.model_validate(dict(pairs))
        except (UnicodeDecodeError, ValueError, ValidationError):
            raise HTTPException(422, 'Invalid search request') from None
        return await run_in_threadpool(run, body)

    @app.get('/assets/{path:path}')
    def asset(path: str, expires: int, signature: str):
        if expires < int(time.time()) or expires > int(time.time())+3660 or path not in state['assets']:
            raise HTTPException(403, 'Invalid image link')
        if not hmac.compare_digest(signature, asset_signature(path, expires)):
            raise HTTPException(403, 'Invalid image link')
        target = (root / path).resolve()
        if not target.is_relative_to(root / 'assets') or not target.is_file():
            raise HTTPException(404, 'Image not found')
        return FileResponse(target, headers={'Cache-Control': 'private, max-age=300', 'X-Content-Type-Options': 'nosniff'})

    return app
