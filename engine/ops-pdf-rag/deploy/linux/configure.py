"""Configure the extracted bundle; never read or modify the Windows project .env."""
import argparse
import ipaddress
import json
import os
from pathlib import Path
import re
import secrets
from urllib.parse import urlsplit


def configure(root, url, bind_ip, port=8765):
    parsed = urlsplit(url)
    if (parsed.scheme not in ('http', 'https') or not parsed.hostname
            or parsed.username or parsed.password or parsed.query or parsed.fragment
            or parsed.path not in ('', '/') or any(c.isspace() for c in url)):
        raise ValueError('URL must be an http(s) origin without credentials, path, query or fragment')
    if ipaddress.ip_address(bind_ip).version != 4 or bind_ip == '0.0.0.0':
        raise ValueError('Bind to one actual IPv4 address of this server')
    if not 1 <= port <= 65535:
        raise ValueError('Port must be 1..65535')
    url = url.rstrip('/')
    env_path = root / '.env'
    existing = {}
    if env_path.exists():
        for line in env_path.read_text(encoding='utf-8').splitlines():
            if '=' in line and not line.startswith('#'):
                key, value = line.split('=', 1)
                existing[key] = value
    token = existing.get('LOCAL_RETRIEVAL_API_KEY') or secrets.token_urlsafe(36)
    if not re.fullmatch(r'[A-Za-z0-9_-]{32,}', token):
        raise ValueError('Existing service key is invalid; do not replace it silently')
    # JSON is a YAML subset, accepted by Dify without needing PyYAML on the host.
    dsl = json.loads((root / 'dify/chatflow-server-template.json').read_text(encoding='utf-8'))
    changed = 0
    for node in dsl['workflow']['graph']['nodes']:
        data = node['data']
        if data['type'] == 'http-request' and node['id'].startswith('retrieve_'):
            data['url'] = url + '/search-form'
            changed += 1
    if not changed:
        raise ValueError('No local retrieval HTTP nodes in template')
    variables = [v for v in dsl['workflow']['environment_variables'] if v['name'] == 'LOCAL_RETRIEVAL_TOKEN']
    if len(variables) != 1:
        raise ValueError('Expected exactly one retrieval secret variable')
    variables[0]['value'] = token
    private_dsl = root / 'dify/chatflow-server-private.yml'
    old_umask = os.umask(0o077)
    try:
        env_path.write_text(f'RETRIEVAL_BIND_IP={bind_ip}\nRETRIEVAL_PORT={port}\n'
                           f'LOCAL_RETRIEVAL_URL={url}\nLOCAL_RETRIEVAL_API_KEY={token}\n', encoding='utf-8')
        private_dsl.write_text(json.dumps(dsl, ensure_ascii=False, indent=2), encoding='utf-8')
        env_path.chmod(0o600)
        private_dsl.chmod(0o600)
    finally:
        os.umask(old_umask)
    return {'url': url, 'updated_http_nodes': changed, 'key': 'preserved' if existing else 'created',
            'private_dsl': 'dify/chatflow-server-private.yml'}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', required=True, help='Address reachable by Dify AND user browsers')
    parser.add_argument('--bind-ip', required=True, help='One actual LAN IPv4 on the server')
    parser.add_argument('--port', type=int, default=8765)
    args = parser.parse_args()
    print(json.dumps(configure(Path(__file__).resolve().parent, args.url, args.bind_ip, args.port), ensure_ascii=False))
