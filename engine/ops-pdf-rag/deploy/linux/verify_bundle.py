"""Verify every exported runtime file before starting the service."""
import hashlib
import json
from pathlib import Path


def verify(root):
    root = root.resolve()
    manifest = json.loads((root / 'bundle-manifest.json').read_text(encoding='utf-8'))
    for name, expected in manifest['files'].items():
        path = (root / name).resolve()
        if not path.is_relative_to(root) or not path.is_file() or path.stat().st_size != expected['bytes']:
            raise ValueError(f'Missing, unsafe or wrong-size file: {name}')
        digest = hashlib.sha256()
        with path.open('rb') as stream:
            for block in iter(lambda: stream.read(1024 * 1024), b''):
                digest.update(block)
        if digest.hexdigest() != expected['sha256']:
            raise ValueError(f'Checksum mismatch: {name}')
    return {'passed': True, 'verified_files': len(manifest['files']), 'snapshot': manifest['snapshot']}


if __name__ == '__main__':
    print(json.dumps(verify(Path(__file__).resolve().parent), indent=2))
