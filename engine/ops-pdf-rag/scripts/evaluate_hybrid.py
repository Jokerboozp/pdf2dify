"""Compare full-corpus BM25 / vector / fusion / reranking on the same frozen queries."""
import json
import argparse
import os
import httpx
from pathlib import Path
import statistics
import sys
import yaml
from ops_rag.common import config, load_env, now, write_json
from ops_rag.hybrid import HybridSearch

ROOT = Path(__file__).resolve().parents[1]


def main():
    sys.stdout.reconfigure(encoding='utf-8')
    parser = argparse.ArgumentParser()
    parser.add_argument('--cases', default='evaluation/hybrid-cases.yaml')
    parser.add_argument('--output', default='data/reports/hybrid-evaluation.json')
    parser.add_argument('--via-api', action='store_true', help='Use the running local API for reranking; avoid loading another large model')
    args = parser.parse_args()
    cfg = config(ROOT/'config.yaml')
    engine = HybridSearch(cfg)
    client = None
    if args.via_api:
        load_env(cfg['project_root'])
        client = httpx.Client(base_url=os.environ['LOCAL_RETRIEVAL_URL'],
            headers={'Authorization': 'Bearer '+os.environ['LOCAL_RETRIEVAL_API_KEY']}, timeout=120, trust_env=False)
    else:
        engine.warm()
    cases = yaml.safe_load((ROOT/args.cases).read_text(encoding='utf-8'))['cases']
    rows = []
    for case in cases:
        for mode in ('bm25', 'vector', 'fusion', 'hybrid'):
            if client and mode == 'hybrid':
                response = client.post('/search', json={'query': case['query'], 'top_k': 5,
                    'kind': case.get('kind', 'detail'), 'route': case.get('domain', ''),
                    'source_id': case.get('source_id', ''), 'section_prefix': case.get('section_prefix', '')})
                response.raise_for_status()
                result = response.json()
            else:
                result = engine.search(case['query'], top_k=5, mode=mode,
                    kind=case.get('kind', 'detail'), domains=[case['domain']] if case.get('domain') else None,
                    source_id=case.get('source_id', ''), section_prefix=case.get('section_prefix', ''))
            rank = next((i for i, r in enumerate(result['results'], 1) if r['id'] in case['expected']), None)
            row = {'id': case['id'], 'split': case['split'], 'query': case['query'], 'mode': mode,
                   'rank': rank, 'elapsed_ms': result['elapsed_ms'],
                   'hits': [{'id': r['id'], 'title': r['title'], 'score': r['score']} for r in result['results']]}
            if case.get('forbidden_prefix'):
                row['condition_isolated'] = all(not r['metadata']['section_title'].startswith(case['forbidden_prefix']) for r in result['results'])
                assert row['condition_isolated']
            rows.append(row)
            print(json.dumps({k: row[k] for k in ('id', 'mode', 'rank', 'elapsed_ms')}, ensure_ascii=False), flush=True)
            write_json((ROOT/args.output).with_suffix('.progress.json'), rows)
    metrics = []
    for split in dict.fromkeys(case['split'] for case in cases):
        for mode in ('bm25', 'vector', 'fusion', 'hybrid'):
            sample = [r for r in rows if r['split'] == split and r['mode'] == mode]
            metrics.append({'split': split, 'mode': mode, 'n': len(sample),
                'hit_at_1': sum(r['rank'] == 1 for r in sample)/len(sample),
                'hit_at_5': sum(r['rank'] is not None for r in sample)/len(sample),
                'mrr_at_5': sum(1/r['rank'] if r['rank'] else 0 for r in sample)/len(sample),
                'median_ms': statistics.median(r['elapsed_ms'] for r in sample)})
    if client: client.close()
    report = {'created_at': now(), 'index': engine.info, 'via_api': args.via_api, 'metrics': metrics, 'cases': rows,
              'scope': 'Small source-checked retrieval sample; not all-document or final-answer acceptance.'}
    write_json(ROOT/args.output, report)
    print(json.dumps(metrics, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
