"""Exercise authenticated retrieval and a real returned image without printing secrets."""
import argparse
import json
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen


def smoke(root, url=None):
    values = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines()
                  if '=' in line and not line.startswith('#'))
    base = (url or values['LOCAL_RETRIEVAL_URL']).rstrip('/')
    request = Request(base + '/search', method='POST',
                      headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + values['LOCAL_RETRIEVAL_API_KEY']},
                      data=json.dumps({'query': '项目结转后怎么撤销？', 'route': 'projects_finance', 'top_k': 6}).encode())
    with urlopen(request, timeout=120) as response:
        data = json.load(response)
    assert data['engine'] == 'hybrid' and data['results'], 'No hybrid results'
    top = data['results'][0]
    assert top['id'] == '2519c00a7aa329e5-projects-002', 'Expected source was not ranked first'
    assert 17 in top['pages'] and 'CJ88' in top['content'], 'Missing original page or transaction code'
    urls = re.findall(r'!\[[^\]]*\]\((https?://[^\s)]+)\)', top['content'])
    assert urls, 'No original image in first result'
    parsed = urlsplit(urls[0])
    origin = urlsplit(values['LOCAL_RETRIEVAL_URL'])
    assert (parsed.scheme, parsed.netloc) == (origin.scheme, origin.netloc), 'Image origin differs from configured server'
    with urlopen(urls[0], timeout=20) as response:
        assert response.headers.get('Content-Type', '').startswith('image/'), 'Not an image'
        assert len(response.read()) > 100, 'Image is empty'
    return {'passed': True, 'engine': data['engine'], 'snapshot': data['snapshot'],
            'top_source': top['source_name'], 'pages': top['pages'], 'image_readable': True,
            'elapsed_ms': data['elapsed_ms']}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--url', help='Optional request origin override; image still uses configured URL')
    args = parser.parse_args()
    try:
        print(json.dumps(smoke(Path(__file__).resolve().parent, args.url), ensure_ascii=False, indent=2))
    except Exception as exc:
        # HTTP exceptions can contain signed URLs. Report type and sanitized reason only.
        print(json.dumps({'passed': False, 'error_type': type(exc).__name__,
                          'detail': str(exc) if isinstance(exc, AssertionError) else 'Check server health, address and credentials'}))
        raise SystemExit(1)
