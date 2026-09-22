"""Export one verified retrieval snapshot, models and referenced images; exclude all secrets."""
import argparse
import hashlib
import io
import json
from pathlib import Path
import tarfile
import time
import yaml
from ops_rag.common import config, digest_file, read_json, signature
from ops_rag.hybrid import input_fingerprint, settings

ROOT = Path(__file__).resolve().parents[1]


def plan(root):
    cfg = config(root / 'config.yaml')
    data = Path(cfg['data_dir'])
    current = read_json(data / 'local-index/current.json')
    if current['settings'] != settings(cfg) or current['input_fingerprint'] != input_fingerprint(data):
        raise ValueError('Index is stale; run ops-rag index before packaging')
    snapshot = current['snapshot']
    if len(snapshot) != 32 or any(c not in '0123456789abcdef' for c in snapshot):
        raise ValueError('Invalid snapshot ID')
    corpus = read_json(data / 'local-index' / snapshot / 'corpus.json')
    if signature(corpus['documents']) != current['document_fingerprint']:
        raise ValueError('Corpus fingerprint mismatch')
    paths = {}
    def add(relative, path):
        path = Path(path)
        if not path.is_file():
            raise ValueError(f'Missing bundle input: {relative}')
        paths[relative] = path
    for source in (root / 'src').rglob('*.py'):
        add(source.relative_to(root).as_posix(), source)
    for name in ('Dockerfile', '.dockerignore', 'compose.yaml', 'configure.py', 'smoke_test.py', 'verify_bundle.py'):
        add(name, root / 'deploy/linux' / name)
    add('requirements.lock.txt', root / 'requirements.lock.txt')
    add('DEPLOY.md', root / 'docs/server-deployment.md')
    for name in ('full-export/manifest.json', 'process-navigation/catalog.json', 'local-index/current.json',
                 f'local-index/{snapshot}/corpus.json', f'local-index/{snapshot}/vectors.npy'):
        add('data/' + name, data / name)
    for source in (data / 'models').rglob('*'):
        if source.is_file() and not any(part.startswith('.') for part in source.relative_to(data / 'models').parts):
            add('data/' + source.relative_to(data).as_posix(), source)
    assets = {im['path'] for doc in corpus['documents'] for im in doc['images']}
    for asset in sorted(assets):
        target = (data / asset).resolve()
        if not target.is_relative_to((data / 'assets').resolve()):
            raise ValueError('Image path escapes data/assets')
        add('data/' + Path(asset).as_posix(), target)
    if not any(name.startswith('data/models/') and name.endswith('.onnx') for name in paths):
        raise ValueError('No cached ONNX model files')
    # JSON encoding keeps template usable by the stdlib-only server configurator.
    dsl = yaml.safe_load((root / 'dify/chatflow-local.yml').read_text(encoding='utf-8'))
    for var in dsl['workflow'].get('environment_variables', []):
        if var.get('value_type') == 'secret':
            var['value'] = ''
    generated = {
        'config.yaml': yaml.safe_dump({'data_dir': 'data', 'local_retrieval': settings(cfg),
                                      'retrieval_service': cfg.get('retrieval_service', {})}, allow_unicode=True).encode(),
        'dify/chatflow-server-template.json': json.dumps(dsl, ensure_ascii=False).encode(),
    }
    return current, paths, generated


def package(root, target):
    current, paths, generated = plan(root)
    target = target.resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    temporary = target.with_suffix(target.suffix + '.partial')
    if target.exists() or temporary.exists():
        raise FileExistsError('Output already exists; use a new output name')
    manifest = {'snapshot': current['snapshot'], 'sources': current['source_count'],
                'documents': current['documents'], 'passages': current['passages'], 'files': {}}
    def add_bytes(archive, name, payload):
        info = tarfile.TarInfo(name)
        info.size, info.mode, info.mtime = len(payload), 0o644, int(time.time())
        archive.addfile(info, io.BytesIO(payload))
        manifest['files'][name] = {'bytes': len(payload), 'sha256': hashlib.sha256(payload).hexdigest()}
    # All entries are regular files: model cache symlinks are dereferenced for portability.
    with tarfile.open(temporary, 'w:gz', compresslevel=1) as archive:
        for i, (name, source) in enumerate(sorted(paths.items()), 1):
            before = source.stat()
            info = tarfile.TarInfo(name)
            info.size, info.mode, info.mtime = before.st_size, 0o644, int(before.st_mtime)
            hasher = hashlib.sha256()
            class Reader:
                def read(self, size=-1):
                    block = stream.read(size)
                    hasher.update(block)
                    return block
            with source.open('rb') as stream:
                archive.addfile(info, Reader())
            after = source.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError(f'Input changed while packaging: {name}')
            manifest['files'][name] = {'bytes': info.size, 'sha256': hasher.hexdigest()}
            if i % 1000 == 0:
                print(json.dumps({'packaged_files': i, 'total_files': len(paths)}), flush=True)
        for name, payload in generated.items():
            add_bytes(archive, name, payload)
        data_root = Path(config(root / 'config.yaml')['data_dir'])
        if read_json(data_root / 'local-index/current.json') != current or input_fingerprint(data_root) != current['input_fingerprint']:
            raise ValueError('Index changed during export; do not publish partial bundle')
        payload = json.dumps(manifest, ensure_ascii=False, indent=2).encode()
        info = tarfile.TarInfo('bundle-manifest.json')
        info.size, info.mode = len(payload), 0o644
        archive.addfile(info, io.BytesIO(payload))
    temporary.rename(target)
    checksum = digest_file(target)
    target.with_suffix(target.suffix + '.sha256').write_text(f'{checksum}  {target.name}\n', encoding='utf-8')
    return {'archive': str(target), 'archive_bytes': target.stat().st_size,
            'files': len(manifest['files']), 'snapshot': current['snapshot'], 'sha256': checksum}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=ROOT / 'data/deploy' / ('ops-retrieval-server-' + time.strftime('%Y%m%d-%H%M%S') + '.tar.gz'))
    parser.add_argument('--plan', action='store_true')
    args = parser.parse_args()
    if args.plan:
        current, paths, generated = plan(ROOT)
        result = {'files': len(paths) + len(generated), 'input_bytes': sum(p.stat().st_size for p in paths.values()),
                  'sources': current['source_count'], 'documents': current['documents'], 'snapshot': current['snapshot']}
    else:
        result = package(ROOT, args.output)
    print(json.dumps(result, ensure_ascii=False, indent=2))
