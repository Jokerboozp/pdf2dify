"""Run local OCR in bounded, disjoint source shards; resumes completed pages."""
from pathlib import Path
from concurrent.futures import ProcessPoolExecutor
import argparse
import sys
from ops_rag.common import config, read_json, write_json, now
from ops_rag.inventory import make_manifest


def worker(config_path, manifest_path, report_path, log_path):
    from ops_rag.pipeline import process
    cfg = config(config_path)
    cfg['ocr']['cpu_threads'] = 2
    with open(log_path, 'a', encoding='utf-8', buffering=1) as log:
        sys.stdout = sys.stderr = log
        return process(cfg, manifest_path, report_path=report_path)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--workers', type=int, default=4)
    args = parser.parse_args()
    if not 1 <= args.workers <= 4:
        raise ValueError('workers must be 1..4')
    cfg = config()
    root = Path(cfg['data_dir'])
    manifest = make_manifest(cfg, full=True)
    groups = {}
    for row in manifest['pages']:
        groups.setdefault(row['source_id'], []).append(row)
    shards = [[] for _ in range(args.workers)]
    for rows in sorted(groups.values(), key=len, reverse=True):
        min(shards, key=len).extend(rows)
    started = now()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futures = []
        for i, rows in enumerate(shards):
            path = root / 'full-workers' / f'manifest-{i}.json'
            write_json(path, {'pages': rows, 'kind': 'full-shard'})
            futures.append(pool.submit(worker, str(Path('config.yaml').resolve()), str(path),
                str(root / 'full-workers' / f'report-{i}.json'), str(root / 'full-workers' / f'worker-{i}.log')))
        reports = [f.result() for f in futures]
    summary = {'started_at': started, 'finished_at': now(), 'planned_pages': len(manifest['pages']),
               'completed': sum(r['completed'] for r in reports), 'skipped': sum(r['skipped'] for r in reports),
               'failed': [e for r in reports for e in r['failed']]}
    write_json(root / 'reports' / 'full-processing.json', summary)
    print(summary)
    if summary['failed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
