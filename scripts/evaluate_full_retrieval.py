"""Nine-domain source recall smoke checks against actual Dify retrieval."""
import json
import argparse
import sys
import time
from pathlib import Path
import yaml
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect, retrieval_model

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser=argparse.ArgumentParser()
    parser.add_argument('--raw',action='store_true',help='Bypass app document scope to measure the unscoped baseline')
    args=parser.parse_args()
    cfg = config(); root = Path(cfg['data_dir']); client = connect(cfg)
    manifest = read_json(root/'full-export/manifest.json')
    state = read_json(root/'dify/full-state.json')
    cases = yaml.safe_load((ROOT/'evaluation/full-smoke.yaml').read_text(encoding='utf-8'))
    known = {d['source_id'] for d in read_json(root/'inventory.json')['documents']}
    assert all(set(x['expected_sources']) <= known for x in cases), 'Unknown expected source'
    report_path=root/'reports'/('full-retrieval-raw.json' if args.raw else 'full-retrieval-smoke.json')
    output = {'started_at': now(), 'scope': 'retrieval-node source recall; catalog selection and answer accuracy require separate UI checks',
              'raw_unscoped':args.raw,
              'full_corpus_built': not manifest['pending_sources'], 'cases': []}
    for case in cases:
        t = time.monotonic(); domain = case['domain']; ds = state['datasets'][domain]['id']
        try:
            model=retrieval_model()
            conditions=[{'name':'validity_status','comparison_operator':'is not','value':'retired'}]
            if case.get('source_scope') and not args.raw:
                conditions.append({'name':'source_id','comparison_operator':'contains','value':case['source_scope']})
            model['metadata_filtering_conditions']={'logical_operator':'and','conditions':conditions}
            response = client.call('POST', f'datasets/{ds}/retrieve', timeout=180,
                json={'query': case['query'], 'retrieval_model': model})
            records = response.get('records', [])
            names = [r.get('segment', {}).get('document', {}).get('name', '') for r in records]
            ranks = [i+1 for i,name in enumerate(names) if any(s in name for s in case['expected_sources'])]
            row = {**case, 'seconds': round(time.monotonic()-t, 3), 'first_expected_rank': min(ranks) if ranks else None,
                   'hit_at_6': bool(ranks), 'records': records}
        except Exception as exc:
            row = {**case, 'seconds': round(time.monotonic()-t, 3), 'hit_at_6': False, 'error': str(exc)}
        output['cases'].append(row)
        write_json(report_path, output)
        print(json.dumps({k:v for k,v in row.items() if k != 'records'}, ensure_ascii=False), flush=True)
    output['finished_at'] = now()
    output['hits'] = sum(x['hit_at_6'] for x in output['cases'])
    write_json(report_path, output)
    if output['hits'] != len(cases): raise SystemExit(1)
