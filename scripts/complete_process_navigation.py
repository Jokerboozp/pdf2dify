"""Finish deferred navigation updates, wait for indexing, then audit every card."""
import json
import msvcrt
import time
from pathlib import Path
from ops_rag.common import config, write_json, now
from ops_rag import full_sync
from process_navigation import nav_config, status


def main():
    cfg = config()
    report = Path(cfg['data_dir'])/'reports/process-navigation-coordinator.json'
    lock_path = report.with_suffix('.lock')
    with lock_path.open('a+b') as lock:
        lock.seek(0)
        if not lock.read(1): lock.write(b'0'); lock.flush()
        lock.seek(0)
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        started, deadline, previous = now(), time.monotonic() + 3600, None
        while time.monotonic() < deadline:
            if (report.parent/'stop-process-navigation').exists():
                write_json(report, {'started_at': started, 'checked_at': now(), 'phase': 'stopped'})
                print('Stopped between sync passes; remote indexing continues.', flush=True)
                return
            result = status(cfg)
            snapshot = {'started_at': started, 'checked_at': now(), 'phase': 'indexing', 'counts': result['counts']}
            write_json(report, snapshot)
            if snapshot['counts'] != previous:
                print(json.dumps(snapshot, ensure_ascii=False), flush=True)
                previous = snapshot['counts']
            if any(p.get('error') or p['status'] == 'error' for p in result['pending']):
                raise RuntimeError('Navigation indexing reported an error; inspect process-navigation-status.json')
            if result['passed']:
                final = status(cfg, audit=True)
                if not final['passed']: raise RuntimeError('Navigation remote content audit failed')
                write_json(report, {**snapshot, 'phase': 'completed', 'finished_at': now(), 'audit_passed': True})
                print('All navigation parents indexed and audited.', flush=True)
                return
            if result['counts']['current'] < result['counts']['total']:
                full_sync.upload(nav_config(cfg), workers=2)
            time.sleep(30)
        raise TimeoutError('Navigation indexing did not finish within one hour; receipts are resumable')


if __name__ == '__main__': main()
