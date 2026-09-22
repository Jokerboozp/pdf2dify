import argparse
import json
import sys
from ops_rag.common import config
from ops_rag.full_sync import setup, upload, status, retire_stale

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['setup', 'upload', 'status', 'retire-stale'])
    parser.add_argument('--apply', action='store_true', help='Apply retirement instead of showing the plan')
    parser.add_argument('--limit', type=int)
    parser.add_argument('--workers', type=int, default=4)
    parser.add_argument('--compact', action='store_true', help='Only print totals; detailed status is still saved locally')
    args = parser.parse_args()
    if args.action == 'upload': result = upload(config(), args.limit, args.workers)
    elif args.action == 'retire-stale': result = retire_stale(config(), args.apply)
    else: result = {'setup': setup, 'status': status}[args.action](config())
    if args.action == 'status' and args.compact:
        result = {k: {'remote_total': v['total'], 'counts': v['counts'], 'target':v['target']['counts']} for k, v in result.items()}
    print(json.dumps(result, ensure_ascii=False, indent=2))
