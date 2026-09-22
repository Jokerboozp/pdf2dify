"""Read-only live retrieval probe. Save source evidence locally, never credentials."""
import argparse
import json
import time
import sys
from pathlib import Path
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect, retrieval_model

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('domain')
    parser.add_argument('query')
    args = parser.parse_args()
    cfg = config(); root = Path(cfg['data_dir'])
    state = read_json(root/'dify/full-state.json')
    client = connect(cfg); ds = state['datasets'][args.domain]['id']
    started = time.monotonic()
    result = client.call('POST', f'datasets/{ds}/retrieve', timeout=180,
        json={'query': args.query, 'retrieval_model': retrieval_model()})
    elapsed = round(time.monotonic()-started, 3)
    write_json(root/'reports'/f'retrieval-{args.domain}.json',
        {'checked_at': now(), 'query': args.query, 'seconds': elapsed, 'response': result})
    print(json.dumps({'seconds': elapsed, 'records': len(result.get('records', [])),
        'results': [{'score': x.get('score'), 'document': x.get('segment', {}).get('document', {}).get('name'),
            'preview': x.get('segment', {}).get('content', '')[:180]} for x in result.get('records', [])]}, ensure_ascii=False))
