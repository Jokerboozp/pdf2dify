"""Resumable Dify service API ingestion. Does not use browser credentials."""
import os
import json
from pathlib import Path
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock
from .common import read_json, write_json, load_env, now
from .dify import DifyClient
from .corpus import DOMAINS, SEPARATOR


def retrieval_model(domain=None):
    return {'search_method': 'hybrid_search', 'reranking_enable': False,
        'reranking_mode': 'weighted_score', 'top_k': 20 if domain == 'finance' else 6, 'score_threshold_enabled': False,
        'weights': {'weight_type': 'customized',
            'vector_setting': {'vector_weight': .7, 'embedding_provider_name': os.getenv('DIFY_EMBEDDING_PROVIDER', 'langgenius/ollama/ollama'),
                               'embedding_model_name': os.getenv('DIFY_EMBEDDING_MODEL', 'nomic-embed-text:latest')},
            'keyword_setting': {'keyword_weight': .3}}}


def payload(domain=None):
    return {'indexing_technique': 'high_quality', 'doc_form': 'hierarchical_model',
        'doc_language': 'Chinese Simplified',
        'embedding_model_provider': os.getenv('DIFY_EMBEDDING_PROVIDER', 'langgenius/ollama/ollama'),
        'embedding_model': os.getenv('DIFY_EMBEDDING_MODEL', 'nomic-embed-text:latest'),
        'retrieval_model': retrieval_model(domain),
        'process_rule': {'mode': 'hierarchical', 'rules': {
            'pre_processing_rules': [{'id': 'remove_extra_spaces', 'enabled': False}, {'id': 'remove_urls_emails', 'enabled': False}],
            'parent_mode': 'full-doc', 'segmentation': {'separator': SEPARATOR, 'max_tokens': 4000, 'chunk_overlap': 0},
            'subchunk_segmentation': {'separator': '<OPS_CHILD_BOUNDARY>', 'max_tokens': 500, 'chunk_overlap': 60}}}}


def connect(cfg):
    load_env(cfg['project_root'])
    base = os.getenv('DIFY_BASE_URL', '').rstrip('/')
    if not base: raise ValueError('DIFY_BASE_URL missing')
    return DifyClient(base, os.getenv('DIFY_DATASET_API_KEY', ''))


def setup(cfg):
    client = connect(cfg)
    root = Path(cfg['data_dir'])
    path = root / 'dify/full-state.json'
    state = read_json(path) if path.exists() else {'datasets': {}, 'documents': {}}
    base = os.getenv('DIFY_BASE_URL')
    if state.get('base_url', base) != base: raise ValueError('Wrong server for state file')
    state['base_url'] = base
    existing, page = [], 1
    while True:
        result = client.call('GET', 'datasets', params={'page': page, 'limit': 100})
        existing.extend(result.get('data', []))
        if not result.get('has_more'): break
        page += 1
    for domain, title in DOMAINS.items():
        name = 'ERP运维-' + title + '-全量演示'
        matches = [d for d in existing if d['name'] == name]
        if len(matches) > 1: raise ValueError('Duplicate dataset name: ' + name)
        if matches:
            dataset = matches[0]
        else:
            dataset = client.call('POST', 'datasets', json={'name': name,
                'description': f'本地PDF解析与OCR；{title}。保留原文图片和页码；业务版本待复核，用于功能演示。',
                'permission': 'only_me', 'indexing_technique': 'high_quality',
                'embedding_model': os.getenv('DIFY_EMBEDDING_MODEL', 'nomic-embed-text:latest'),
                'embedding_model_provider': os.getenv('DIFY_EMBEDDING_PROVIDER', 'langgenius/ollama/ollama'),
                'retrieval_model': retrieval_model(domain)})
        state['datasets'][domain] = {'id': dataset['id'], 'name': name}
        write_json(path, state)
    return {'datasets': state['datasets']}


def upload(cfg, limit=None, workers=4):
    if not 1 <= workers <= 4: raise ValueError('Upload workers must be 1..4')
    client = connect(cfg)
    root = Path(cfg['data_dir'])
    path = root / 'dify/full-state.json'
    state = read_json(path)
    if state['base_url'] != os.getenv('DIFY_BASE_URL'): raise ValueError('Wrong server')
    manifest = read_json(root / 'full-export/manifest.json')
    remote, fields = {}, {}
    jobs = []; deferred = []
    for item in manifest['documents']:
        domain = item['domain']; dataset = state['datasets'][domain]['id']
        if domain not in remote:
            remote[domain] = client.documents(dataset)
            meta = client.call('GET', f'datasets/{dataset}/metadata')
            fields[domain] = {m['name']: m['id'] for m in meta.get('doc_metadata', [])}
            for name in item['metadata']:
                if name not in fields[domain]:
                    result = client.call('POST', f'datasets/{dataset}/metadata', json={'name': name, 'type': 'string'})
                    fields[domain][name] = result['id']
        matches = [d for d in remote[domain] if d['name'] == Path(item['path']).name]
        if len(matches) > 1: raise ValueError('Remote document name collision: ' + item['key'])
        old = state['documents'].get(item['key'], {})
        doc_id = matches[0]['id'] if matches else None
        if old.get('hash') == item['content_hash'] and old.get('document_id') == doc_id and old.get('metadata_applied') and not old.get('retired_at'):
            continue
        if doc_id and old.get('hash') != item['content_hash'] and matches[0].get('display_status') != 'available':
            deferred.append({'key': item['key'], 'status': matches[0].get('display_status'),
                             'indexing_status': matches[0].get('indexing_status')})
            continue
        if limit is not None and len(jobs) >= limit: break
        jobs.append((item, dataset, doc_id, old))
    lock = Lock()

    def submit_one(job):
        item, dataset, doc_id, old = job
        domain = item['domain']
        if not (old.get('hash') == item['content_hash'] and old.get('document_id') == doc_id):
            endpoint = f'datasets/{dataset}/documents/{doc_id}/update-by-file' if doc_id else f'datasets/{dataset}/document/create-by-file'
            with Path(item['path']).open('rb') as stream:
                result = client.call('POST', endpoint, timeout=180,
                    data={'data': json.dumps(payload(item['domain']), ensure_ascii=False)},
                    files={'file': (Path(item['path']).name, stream, 'application/vnd.openxmlformats-officedocument.wordprocessingml.document')})
            doc_id = result['document']['id']
            with lock:
                state['documents'][item['key']] = {'document_id': doc_id, 'dataset_id': dataset,
                    'hash': item['content_hash'], 'batch': result.get('batch'), 'metadata_applied': False,
                    'source_id': item['source_id'], 'submitted_at': now()}
                write_json(path, state)
        client.call('POST', f'datasets/{dataset}/documents/metadata', json={'operation_data': [{
            'document_id': doc_id, 'metadata_list': [{'id': fields[domain][k], 'name': k, 'value': v} for k,v in item['metadata'].items()]}]})
        with lock:
            state['documents'][item['key']]['metadata_applied'] = True
            state['documents'][item['key']].pop('retired_at', None)
            write_json(path, state)
        print(f"Submitted {domain} {item['source_name']} ({item['key']})", flush=True)
        return item['key']

    errors = []; submitted = 0
    # Only bounded requests are in flight; receipts are committed before metadata
    # updates so an interrupted run can resume without duplicate documents.
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0, len(jobs), 20):
            futures = {pool.submit(submit_one, job): job[0]['key'] for job in jobs[start:start+20]}
            for future in as_completed(futures):
                try:
                    future.result(); submitted += 1
                except Exception as exc:
                    errors.append({'key': futures[future], 'error': type(exc).__name__ + ': ' + str(exc)})
            if errors: break
    if errors:
        write_json(root/'reports/full-upload-errors.json', {'created_at': now(), 'errors': errors})
        raise RuntimeError(f'{len(errors)} upload failures; see data/reports/full-upload-errors.json; completed receipts retained')
    result = {'checked_at': now(), 'submitted_now': submitted, 'tracked_documents': len(state['documents']),
              'deferred_updates': deferred, 'note': 'Deferred updates need another upload pass after indexing completes'}
    write_json(root/'reports/full-upload.json', result)
    return result


def status(cfg):
    client = connect(cfg); root = Path(cfg['data_dir'])
    state = read_json(root / 'dify/full-state.json')
    manifest = read_json(root/'full-export/manifest.json')
    anchors_path = root/'dify/search-anchors.json'
    anchors = read_json(anchors_path).get('documents', {}) if anchors_path.exists() else {}
    results = {}
    for domain, dataset in state['datasets'].items():
        docs = client.documents(dataset['id'])
        target = audit_target([x for x in manifest['documents'] if x['domain']==domain], state['documents'], docs, anchors)
        results[domain] = {'dataset_id': dataset['id'], 'total': len(docs), 'target': target,
            'counts': dict(Counter(d['indexing_status'] for d in docs)),
            'unavailable': [{'id': d['id'], 'name': d['name'], 'status': d['indexing_status'], 'error': d.get('error')} for d in docs if d['indexing_status'] != 'completed' or not d.get('enabled')]}
    write_json(root / 'reports/full-indexing.json', {'checked_at': now(), 'domains': results})
    return results


def audit_target(items, receipts, remote_docs, anchors):
    """Count current content only; retained old sections must not inflate readiness."""
    from .search_anchors import anchor_text
    from .common import signature
    by_id = {d['id']:d for d in remote_docs}
    counts = Counter(); pending = []
    for item in items:
        old = receipts.get(item['key'], {}); doc = by_id.get(old.get('document_id'))
        current = bool(doc and old.get('hash')==item['content_hash'] and old.get('metadata_applied') and not old.get('retired_at'))
        ready = bool(current and doc.get('indexing_status')=='completed' and doc.get('enabled'))
        counts['total'] += 1; counts['submitted_current'] += int(current); counts['ready'] += int(ready)
        text = anchor_text(item)
        if text:
            counts['anchor_required'] += 1
            counts['anchor_ready'] += int(ready)
            anchor = anchors.get(item['key'], {})
            matched = ready and anchor.get('document_id')==old.get('document_id') and anchor.get('fingerprint')==signature({'parent_hash':item['content_hash'],'text':text})
            counts['anchors_current'] += int(bool(matched))
        if not ready:
            pending.append({'key':item['key'],'submitted_current':current,
                            'status':doc.get('indexing_status') if doc else 'missing',
                            'enabled':doc.get('enabled') if doc else False})
    return {'counts':dict(counts),'pending':pending}


def retire_stale(cfg, apply=False):
    """Retire obsolete managed sections only after a complete corpus build.

    Partial builds must never hide documents merely because OCR is still running.
    Keep the remote documents for audit and rollback; retrieval excludes retired.
    """
    root = Path(cfg['data_dir'])
    manifest = read_json(root/'full-export/manifest.json')
    if manifest.get('pending_sources') or manifest['built_sources'] != manifest['source_count']:
        raise ValueError('Retirement requires a complete corpus; pending sources remain')
    state_path = root/'dify/full-state.json'
    state = read_json(state_path)
    current = {x['key'] for x in manifest['documents']}
    stale = {k:v for k,v in state['documents'].items() if k not in current and not v.get('retired_at')}
    result = {'apply': apply, 'obsolete_managed_sections': list(stale)}
    if not apply or not stale:
        return result
    client = connect(cfg)
    if state['base_url'] != os.getenv('DIFY_BASE_URL'):
        raise ValueError('Wrong server')
    affected = {d['dataset_id'] for d in stale.values()}
    available = {d['id'] for ds in affected for d in client.documents(ds)
                 if d.get('indexing_status')=='completed' and d.get('enabled')}
    for item in manifest['documents']:
        receipt = state['documents'].get(item['key'], {})
        if receipt.get('dataset_id') not in affected:
            continue
        if (receipt.get('hash') != item['content_hash'] or not receipt.get('metadata_applied')
                or receipt.get('document_id') not in available):
            raise ValueError('Replacement documents must be current and indexed before retiring old sections')
    for key, doc in stale.items():
        ds = doc['dataset_id']
        fields = client.call('GET', f'datasets/{ds}/metadata')['doc_metadata']
        field = next(x for x in fields if x['name'] == 'validity_status')
        detail = client.call('GET', f"datasets/{ds}/documents/{doc['document_id']}", params={'metadata': 'only'})
        values = [{k: m[k] for k in ('id', 'name', 'value')} for m in detail.get('doc_metadata', [])
                  if m['id'] != 'built-in' and m['name'] != 'validity_status']
        values.append({'id': field['id'], 'name': 'validity_status', 'value': 'retired'})
        client.call('POST', f'datasets/{ds}/documents/metadata', json={'operation_data': [{
            'document_id': doc['document_id'], 'metadata_list': values}]})
        doc['retired_at'] = now()
        write_json(state_path, state)
    return result
