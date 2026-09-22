import json
from pathlib import Path
from ops_rag.common import read_json, now

root=Path(__file__).resolve().parents[1]/'data'
reports=[read_json(p) for p in (root/'full-workers').glob('report-*.json')]
manifest=read_json(root/'full-export/manifest.json') if (root/'full-export/manifest.json').exists() else {}
print(json.dumps({'checked_at':now(),'ocr_completed_this_run':sum(x['completed'] for x in reports),
    'ocr_cached':sum(x['skipped'] for x in reports),'ocr_failures':sum(len(x['failed']) for x in reports),
    'exported_sources':manifest.get('built_sources',0),'exported_documents':len(manifest.get('documents',[])),
    'ocr_workers_finished':sum('finished_at' in x for x in reports)},ensure_ascii=False))
