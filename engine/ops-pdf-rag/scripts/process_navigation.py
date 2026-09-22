"""Build and sync an isolated navigation index using the authorized dataset API."""
import argparse
import json
import os
from pathlib import Path
from collections import Counter
from ops_rag.common import config, read_json, write_json, now
from ops_rag import process_catalog, full_sync

NAME = 'ERP运维-流程导航-全量演示'


def nav_config(cfg):
    return {**cfg, 'data_dir': str(Path(cfg['data_dir'])/'process-navigation')}


def setup(cfg):
    client = full_sync.connect(cfg)
    cfg = nav_config(cfg)
    path = Path(cfg['data_dir'])/'dify/full-state.json'
    state = read_json(path) if path.exists() else {'datasets': {}, 'documents': {}}
    base = os.getenv('DIFY_BASE_URL')
    if state.get('base_url', base) != base:
        raise ValueError('Navigation state belongs to another server')
    all_datasets, page = [], 1
    while True:
        result = client.call('GET', 'datasets', params={'page': page, 'limit': 100})
        all_datasets.extend(result.get('data', []))
        if not result.get('has_more'): break
        page += 1
    matches = [d for d in all_datasets if d['name'] == NAME]
    if len(matches) > 1: raise ValueError('Duplicate navigation dataset names')
    ds = matches[0] if matches else client.call('POST', 'datasets', json={
        'name': NAME, 'description': '原文流程名称、文件主题与全书章节导航；本地抽取，不生成业务规则。',
        'permission': 'only_me', 'indexing_technique': 'high_quality',
        'embedding_model': os.getenv('DIFY_EMBEDDING_MODEL', 'nomic-embed-text:latest'),
        'embedding_model_provider': os.getenv('DIFY_EMBEDDING_PROVIDER', 'langgenius/ollama/ollama'),
        'retrieval_model': full_sync.retrieval_model()})
    state.update(base_url=base, datasets={'process_navigation': {'id': ds['id'], 'name': NAME}})
    write_json(path, state)
    return state['datasets']


def status(cfg, audit=False):
    client = full_sync.connect(cfg)
    root = Path(nav_config(cfg)['data_dir'])
    state = read_json(root/'dify/full-state.json')
    if state['base_url'] != os.getenv('DIFY_BASE_URL'): raise ValueError('Wrong server')
    ds = state['datasets']['process_navigation']['id']
    remote = {d['id']: d for d in client.documents(ds)}
    manifest = read_json(root/'full-export/manifest.json')['documents']
    catalog = {r['key']: r for r in read_json(root/'catalog.json')['records']}
    counts, pending, errors = Counter(), [], []
    for item in manifest:
        receipt = state['documents'].get(item['key'], {})
        doc = remote.get(receipt.get('document_id'), {})
        current = receipt.get('hash') == item['content_hash'] and receipt.get('metadata_applied') and not receipt.get('retired_at')
        ready = current and doc.get('indexing_status') == 'completed' and doc.get('enabled')
        counts['total'] += 1
        counts['current'] += int(bool(current))
        counts['ready'] += int(bool(ready))
        if not ready: pending.append({'key': item['key'], 'status': doc.get('indexing_status', 'missing'), 'error': doc.get('error')})
        elif audit:
            detail = client.call('GET', f"datasets/{ds}/documents/{doc['id']}", params={'metadata': 'only'})
            meta = {x['name']: x['value'] for x in detail.get('doc_metadata', [])}
            if any(meta.get(k) != v for k, v in item['metadata'].items()):
                errors.append({'key': item['key'], 'error': 'metadata_mismatch'})
            segments = client.call('GET', f"datasets/{ds}/documents/{doc['id']}/segments", params={'limit': 100})['data']
            text = '\n'.join(s.get('content', '') for s in segments)
            if item['source_name'] not in text or '全书章节导航' not in text:
                errors.append({'key': item['key'], 'error': 'missing_navigation_content'})
            record = catalog[item['key']]
            for heading in record['outline']:
                expected = f"{heading['title']}｜来源：{item['source_name']}，PDF 第{process_catalog.page_label(heading['pages'])}页"
                if expected not in text:
                    errors.append({'key': item['key'], 'error': 'missing_outline_heading', 'heading': heading['title']})
            if text.count('![') != item['image_count']:
                errors.append({'key': item['key'], 'error': 'image_count_mismatch'})
    result = {'checked_at': now(), 'dataset_id': ds, 'counts': dict(counts), 'pending': pending, 'errors': errors,
              'remote_audit': audit, 'passed': not pending and not errors}
    write_json(Path(cfg['data_dir'])/'reports'/('process-navigation-audit.json' if audit else 'process-navigation-status.json'), result)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('command', choices=['build', 'setup', 'upload', 'status', 'audit', 'retire-stale'])
    p.add_argument('--workers', type=int, default=2)
    p.add_argument('--apply', action='store_true')
    args = p.parse_args()
    cfg = config()
    if args.command == 'build': result = process_catalog.build(cfg)
    elif args.command == 'setup': result = setup(cfg)
    elif args.command == 'upload': result = full_sync.upload(nav_config(cfg), workers=args.workers)
    elif args.command == 'retire-stale': result = full_sync.retire_stale(nav_config(cfg), apply=args.apply)
    else: result = status(cfg, audit=args.command == 'audit')
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'audit' and not result['passed']: raise SystemExit(1)
