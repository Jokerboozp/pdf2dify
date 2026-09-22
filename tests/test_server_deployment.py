import importlib.util
import json
from pathlib import Path
import tarfile

import pytest
import yaml
from ops_rag.common import signature, write_json
from ops_rag.hybrid import DEFAULTS, input_fingerprint

ROOT = Path(__file__).resolve().parents[1]


def module(path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


configure = module(ROOT / 'deploy/linux/configure.py').configure
packager = module(ROOT / 'scripts/package_retrieval_server.py')
verify = module(ROOT / 'deploy/linux/verify_bundle.py').verify


def template():
    return yaml.safe_load((ROOT / 'dify/chatflow-local.yml').read_text(encoding='utf-8'))


def test_configure_server_preserves_key_and_routes_without_touching_client(tmp_path):
    (tmp_path / 'dify').mkdir()
    dsl = template()
    write_json(tmp_path / 'dify/chatflow-server-template.json', dsl)
    result = configure(tmp_path, 'http://192.168.24.133:8765', '192.168.24.133')
    first_env = (tmp_path / '.env').read_text()
    assert result['updated_http_nodes'] == 15
    configured = read_private(tmp_path)
    new_nodes = {n['id']: n['data'] for n in configured['workflow']['graph']['nodes']}
    for node in dsl['workflow']['graph']['nodes']:
        actual = new_nodes[node['id']]
        if actual['type'] == 'http-request':
            assert actual['url'] == 'http://192.168.24.133:8765/search-form'
            assert actual['body'] == node['data']['body']
        else:
            assert actual == node['data']
    configure(tmp_path, 'http://192.168.24.133:8765', '192.168.24.133')
    assert first_env == (tmp_path / '.env').read_text()
    secret = configured['workflow']['environment_variables'][0]['value']
    assert len(secret) >= 32 and secret in first_env
    assert secret not in json.dumps(result)
    with pytest.raises(ValueError):
        configure(tmp_path, 'http://user:password@host:8765', '192.168.24.133')
    assert first_env == (tmp_path / '.env').read_text()


def read_private(root):
    return yaml.safe_load((root / 'dify/chatflow-server-private.yml').read_text(encoding='utf-8'))


def test_bundle_roundtrip_excludes_secrets_unused_images_and_old_snapshots(tmp_path):
    root = tmp_path / 'source'
    root.mkdir()
    queue_config = {'max_pending_requests': 8, 'queue_wait_seconds': 60}
    write_json(root / 'config.yaml', {'data_dir': 'data', 'local_retrieval': DEFAULTS,
                                    'retrieval_service': queue_config})
    data = root / 'data'
    write_json(data / 'full-export/manifest.json', {'documents': []})
    write_json(data / 'process-navigation/catalog.json', {'records': []})
    doc = {'images': [{'path': 'assets/page.png'}]}
    current = {'settings': DEFAULTS, 'snapshot': 'a' * 32, 'input_fingerprint': input_fingerprint(data),
               'document_fingerprint': signature([doc]), 'source_count': 1, 'documents': 1, 'passages': 1}
    write_json(data / 'local-index/current.json', current)
    write_json(data / 'local-index' / ('a' * 32) / 'corpus.json', {'documents': [doc]})
    payloads = {'src/ops_rag/app.py': b'# source', 'requirements.lock.txt': b'',
                'docs/server-deployment.md': b'guide', 'data/models/test/model.onnx': b'model',
                'data/assets/page.png': b'used image', 'data/assets/unused.png': b'unused image',
                'data/local-index/' + 'a' * 32 + '/vectors.npy': b'vector',
                'data/local-index/old/private.txt': b'old', '.env': b'SUPER_PRIVATE_SECRET'}
    for name in ('Dockerfile', '.dockerignore', 'compose.yaml', 'configure.py', 'smoke_test.py', 'verify_bundle.py'):
        payloads['deploy/linux/' + name] = (ROOT / 'deploy/linux' / name).read_bytes()
    for name, value in payloads.items():
        dest = root / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(value)
    dsl = template()
    dsl['workflow']['environment_variables'][0]['value'] = 'SUPER_PRIVATE_SECRET'
    write_json(root / 'dify/chatflow-local.yml', dsl)
    archive_path = tmp_path / 'bundle.tar.gz'
    packager.package(root, archive_path)
    extracted = tmp_path / 'extracted'
    with tarfile.open(archive_path) as archive:
        names = archive.getnames()
        assert '.env' not in names and 'data/assets/unused.png' not in names
        assert not any('/old/' in name for name in names)
        assert all(m.isfile() for m in archive.getmembers())
        assert b'SUPER_PRIVATE_SECRET' not in archive.extractfile('dify/chatflow-server-template.json').read()
        packaged_config = yaml.safe_load(archive.extractfile('config.yaml').read())
        assert packaged_config['retrieval_service'] == queue_config
        assert packaged_config['local_retrieval'] == DEFAULTS
        archive.extractall(extracted, filter='data')
    assert verify(extracted)['passed']
    (extracted / 'data/assets/page.png').write_bytes(b'changed')
    with pytest.raises(ValueError):
        verify(extracted)
    # A partial build must never overwrite a ready bundle.
    with pytest.raises(FileExistsError):
        packager.package(root, archive_path)
