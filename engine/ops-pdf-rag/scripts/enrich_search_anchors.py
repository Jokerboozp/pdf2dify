import argparse
import json
from ops_rag.common import config
from ops_rag.search_anchors import enrich

if __name__ == '__main__':
    p=argparse.ArgumentParser();p.add_argument('--workers',type=int,default=2);p.add_argument('--limit',type=int)
    a=p.parse_args()
    print(json.dumps(enrich(config(),a.workers,a.limit),ensure_ascii=False))
