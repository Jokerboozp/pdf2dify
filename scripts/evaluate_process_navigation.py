"""Verify exact-source overview retrieval; UI separately checks name selection."""
import json
import time
from pathlib import Path
import yaml
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect, retrieval_model

ROOT = Path(__file__).resolve().parents[1]

if __name__ == '__main__':
    cfg = config()
    root = Path(cfg['data_dir'])
    state = read_json(root/'process-navigation/dify/full-state.json')
    ds = state['datasets']['process_navigation']['id']
    client = connect(cfg)
    cases = yaml.safe_load((ROOT/'evaluation/process-navigation.yaml').read_text(encoding='utf-8'))
    report = {'started_at': now(), 'scope': 'Filtered navigation retrieval, not LLM name-selection or answer accuracy', 'cases': []}
    for case in cases:
        model = retrieval_model()
        model['top_k'] = 1
        model['metadata_filtering_conditions'] = {'logical_operator': 'and', 'conditions': [
            {'name': 'process_key', 'comparison_operator': 'is', 'value': case['process_key']},
            {'name': 'validity_status', 'comparison_operator': 'is not', 'value': 'retired'}]}
        started = time.monotonic()
        result = client.call('POST', f'datasets/{ds}/retrieve', timeout=180,
                             json={'query': case['query'], 'retrieval_model': model})
        records = result.get('records', [])
        text = '\n'.join(r['segment']['content'] for r in records)
        names = [r['segment']['document']['name'] for r in records]
        missing = [s for s in case['must_contain'] if s not in text]
        passed = len(records) == 1 and names == [f"flow-{case['process_key']}.docx"] and not missing
        row = {**case, 'passed': passed, 'missing': missing, 'documents': names, 'seconds': round(time.monotonic()-started, 3)}
        report['cases'].append(row)
        print(json.dumps(row, ensure_ascii=False), flush=True)
    report.update(finished_at=now(), passed=all(c['passed'] for c in report['cases']))
    write_json(root/'reports/process-navigation-retrieval.json', report)
    if not report['passed']: raise SystemExit(1)
