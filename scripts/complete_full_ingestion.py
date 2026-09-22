"""Resume the authorized ingestion until current documents and anchors are ready.

Run only one coordinator. Do not run separate upload/enrich/retire commands while
this process is active. A stop request is data/reports/stop-ingestion (any content).
"""
import argparse
import json
import msvcrt
import os
import sys
import time
from pathlib import Path
from ops_rag.common import config, write_json, now
from ops_rag.full_sync import status, upload, retire_stale
from ops_rag.search_anchors import enrich


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--max-hours',type=float,default=12)
    parser.add_argument('--interval',type=int,default=120)
    args=parser.parse_args()
    if args.max_hours<=0 or args.interval<30: parser.error('Use positive hours and interval >=30')
    cfg=config(); root=Path(cfg['data_dir']); report=root/'reports/ingestion-coordinator.json'
    lock_path=root/'dify/ingestion-coordinator.lock'
    with lock_path.open('a+b') as lock:
        lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
        try: msvcrt.locking(lock.fileno(),msvcrt.LK_NBLCK,1)
        except OSError: raise SystemExit('An ingestion coordinator is already running')
        started=now(); deadline=time.monotonic()+args.max_hours*3600
        while time.monotonic()<deadline:
            if (root/'reports/stop-ingestion').exists():
                write_json(report,{'started_at':started,'checked_at':now(),'pid':os.getpid(),'phase':'stopped'})
                return
            results=status(cfg)
            totals={k:sum(v['target']['counts'].get(k,0) for v in results.values())
                    for k in ('total','submitted_current','ready','anchor_required','anchor_ready','anchors_current')}
            record={'started_at':started,'checked_at':now(),'pid':os.getpid(),'phase':'indexing','counts':totals}
            write_json(report,record); print(json.dumps(record),flush=True)
            errors=[{'domain':domain,**d} for domain,value in results.items()
                    for d in value['unavailable'] if d['status']=='error']
            if errors:
                write_json(report,{**record,'phase':'needs_attention','errors':errors})
                raise RuntimeError('Dify indexing errors; inspect coordinator report')
            eligible=any(not d['submitted_current'] and d['status']=='completed' and d['enabled']
                         for value in results.values() for d in value['target']['pending'])
            missing=any(d['status']=='missing' for value in results.values() for d in value['target']['pending'])
            if eligible or missing:
                write_json(report,{**record,'phase':'updating_documents'})
                upload(cfg,workers=2)
                # Re-read indexes before adding anchors to replaced parents.
                continue
            if totals['anchor_ready']>totals['anchors_current']:
                write_json(report,{**record,'phase':'adding_search_anchors'})
                enrich(cfg,workers=2)
                continue
            if totals['ready']==totals['total'] and totals['anchors_current']==totals['anchor_required']:
                retired=retire_stale(cfg,apply=True)
                write_json(report,{**record,'phase':'completed','finished_at':now(),'retirement':retired,
                    'next':'Run source retrieval smoke and UI answer acceptance; ingestion alone is not final acceptance.'})
                print('All current documents and search anchors are indexed; retrieval acceptance still required.',flush=True)
                return
            time.sleep(args.interval)
        write_json(report,{**record,'phase':'time_limit','checked_at':now()})


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    main()
