"""Check operation-body recall; directory hits alone must not pass."""
import json
import sys
from pathlib import Path
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect, retrieval_model

CASES = [
    ('工作中心主数据创建、查询', '1500bced25fba85c-equipment-007', ('IR01', 'IR03')),
    ('工作中心怎么创建和查询', '1500bced25fba85c-equipment-007', ('IR01', 'IR03')),
    ('功能位置主数据创建、查询', '1500bced25fba85c-equipment-010', ('IL01', 'IL03')),
]


def main():
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    cfg = config(); root = Path(cfg['data_dir']); client = connect(cfg)
    state = read_json(root / 'dify/full-state.json')
    dataset = state['datasets']['equipment']['id']
    model = retrieval_model()
    model['metadata_filtering_conditions'] = {'logical_operator': 'and', 'conditions': [
        {'name': 'validity_status', 'comparison_operator': 'is not', 'value': 'retired'},
        {'name': 'section_title', 'comparison_operator': 'is not', 'value': '目录'}]}
    rows = []
    for query, key, codes in CASES:
        records = client.call('POST', f'datasets/{dataset}/retrieve', timeout=90,
                             json={'query': query, 'retrieval_model': model}).get('records', [])
        hits = []
        for i, record in enumerate(records, 1):
            segment = record.get('segment', {})
            name = segment.get('document', {}).get('name', '')
            content = segment.get('content', '')
            hits.append({'rank': i, 'name': name,
                         'expected_operation': key in name and all(c in content for c in codes)})
        rows.append({'query': query, 'passed': any(h['expected_operation'] for h in hits), 'hits': hits})
    report = {'checked_at': now(), 'scope': 'Actual Dify retrieval; LLM routing and final answers require UI acceptance',
              'cases': rows, 'passed': all(r['passed'] for r in rows)}
    write_json(root / 'reports/equipment-operation-recall.json', report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
