from pathlib import Path
from contextlib import closing
import pypdfium2 as pdfium
from .common import digest_file, now, read_json, write_json, parse_pages


def scan(cfg):
    root = Path(cfg['source_root'])
    if not root.is_dir():
        raise ValueError(f'Source directory not found: {root}')
    docs = []
    for path in sorted(root.rglob('*')):
        if not path.is_file() or path.suffix.lower() != '.pdf':
            continue
        sha = digest_file(path)
        item = dict(source_id=sha[:16], sha256=sha, path=str(path),
                    relative_path=path.relative_to(root).as_posix(),
                    name=path.name, bytes=path.stat().st_size, business_version='unknown')
        try:
            with closing(pdfium.PdfDocument(str(path))) as doc:
                item['pages'] = len(doc)
            item['status'] = 'ok'
        except Exception as exc:
            item.update(status='error', error=type(exc).__name__ + ': ' + str(exc))
        docs.append(item)
    report = dict(created_at=now(), source_root=str(root), documents=docs,
                  file_count=len(docs), total_pages=sum(d.get('pages', 0) for d in docs),
                  total_bytes=sum(d['bytes'] for d in docs))
    write_json(Path(cfg['data_dir']) / 'inventory.json', report)
    return report


def make_manifest(cfg, full=False):
    inv = read_json(Path(cfg['data_dir']) / 'inventory.json')
    tasks = []
    if full:
        picks = [(d, list(range(1, d['pages'] + 1)), '') for d in inv['documents'] if d['status'] == 'ok']
    else:
        picks = []
        for item in cfg['pilot']:
            matches = [d for d in inv['documents'] if d['name'] == item['name']]
            if len(matches) != 1:
                raise ValueError(f"Expected one source for {item['name']}, got {len(matches)}")
            doc = matches[0]
            if doc['status'] != 'ok':
                raise ValueError(f"Cannot plan failed source: {doc['name']}: {doc.get('error')}")
            picks.append((doc, parse_pages(item['pages'], doc['pages']), item['module']))
    for doc, pages, module in picks:
        tasks.extend(dict(source_id=doc['source_id'], sha256=doc['sha256'], path=doc['path'],
                          name=doc['name'], page=p, total_pages=doc['pages'], module=module) for p in pages)
    result = dict(created_at=now(), kind='full' if full else 'pilot', pages=tasks)
    write_json(Path(cfg['data_dir']) / ('full-manifest.json' if full else 'pilot-manifest.json'), result)
    return result
