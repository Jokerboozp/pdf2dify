import argparse
import json
import sys
from ops_rag.common import config
from ops_rag.corpus import build

if __name__ == '__main__':
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser()
    parser.add_argument('--limit', type=int)
    args = parser.parse_args()
    result = build(config(), args.limit)
    result['pending_sources'] = len(result['pending_sources'])
    print(json.dumps(result, ensure_ascii=False, indent=2))
