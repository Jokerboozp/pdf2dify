import argparse
import json
import sys
from pathlib import Path
from .common import config, load_env


def main():
    if hasattr(sys.stdout, 'reconfigure'):
        sys.stdout.reconfigure(encoding='utf-8', errors='replace')
    parser = argparse.ArgumentParser(description='Local PDF to Dify operations knowledge')
    parser.add_argument('--config', default='config.yaml')
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('scan')
    p = sub.add_parser('plan')
    p.add_argument('--full', action='store_true')
    p = sub.add_parser('native')
    p.add_argument('--all', action='store_true')
    p = sub.add_parser('process')
    p.add_argument('--manifest')
    p.add_argument('--limit', type=int)
    p.add_argument('--force', action='store_true')
    sub.add_parser('report')
    sub.add_parser('cards')
    sub.add_parser('procedures')
    p = sub.add_parser('search')
    p.add_argument('query')
    p.add_argument('--top-k', type=int, default=5)
    p.add_argument('--engine', choices=['hybrid', 'fusion', 'vector', 'bm25', 'pilot'], default='hybrid')
    p.add_argument('--domain', action='append')
    p.add_argument('--source-id', default='')
    p.add_argument('--section-prefix', default='')
    p.add_argument('--kind', choices=['detail', 'overview'])
    p = sub.add_parser('index')
    p = sub.add_parser('download-models')
    p = sub.add_parser('serve')
    p.add_argument('--host', default='127.0.0.1')
    p.add_argument('--port', type=int, default=8765)
    p = sub.add_parser('export')
    p.add_argument('--include-drafts', action='store_true')
    p = sub.add_parser('dify-sync')
    p.add_argument('--apply', action='store_true')
    p = sub.add_parser('evaluate')
    p.add_argument('--mode', choices=['local','dify'], default='local')
    args = parser.parse_args()
    cfg = config(args.config)
    load_env(cfg['project_root'])
    if args.command == 'scan':
        from .inventory import scan
        r = scan(cfg)
        result = {k:v for k,v in r.items() if k != 'documents'}
    elif args.command == 'plan':
        from .inventory import make_manifest
        r = make_manifest(cfg, args.full)
        result = dict(kind=r['kind'], planned_pages=len(r['pages']))
    elif args.command == 'native':
        from .pipeline import native_extract
        result = native_extract(cfg, all_sources=args.all)
    elif args.command == 'process':
        from .pipeline import process
        result = process(cfg, args.manifest, args.limit, args.force)
    elif args.command == 'cards':
        from .cards import build_cards
        result = build_cards(cfg)
    elif args.command == 'procedures':
        from .procedures import make_packets
        result = make_packets(cfg)
    elif args.command == 'search':
        if args.engine == 'pilot':
            from .retrieval import search
            result = search(cfg, args.query, args.top_k)
        else:
            from .hybrid import HybridSearch
            result = HybridSearch(cfg).search(args.query, args.top_k, mode=args.engine,
                domains=args.domain, source_id=args.source_id, section_prefix=args.section_prefix, kind=args.kind)
    elif args.command == 'index':
        from .hybrid import build_index
        result = build_index(cfg, progress=lambda r: print(json.dumps(r), file=sys.stderr, flush=True))
    elif args.command == 'download-models':
        from .hybrid import models
        for rerank in (False, True):
            model = models(cfg, rerank=rerank, download=True)
            del model
        result = {'status': 'models_cached_locally'}
    elif args.command == 'serve':
        import uvicorn
        from .search_api import create_app
        uvicorn.run(create_app(cfg), host=args.host, port=args.port, access_log=False)
        return
    elif args.command == 'report':
        from .reports import build_report
        result = build_report(cfg)
    elif args.command == 'export':
        from .dify import export
        result = export(cfg, args.include_drafts)
    elif args.command == 'dify-sync':
        from .dify import sync
        result = sync(cfg, args.apply)
    else:
        from .evaluation import evaluate
        result = evaluate(cfg, args.mode)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    if args.command == 'process' and result.get('failed'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
