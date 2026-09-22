"""Check simultaneous real HTTP retrievals without printing credentials or signed URLs."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import threading
import time
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def verify(root):
    values = dict(line.split('=', 1) for line in (root / '.env').read_text().splitlines()
                  if '=' in line and not line.startswith('#'))
    barrier = threading.Barrier(2)

    def call():
        request = Request(values['LOCAL_RETRIEVAL_URL'].rstrip('/') + '/search-form', method='POST',
                          headers={'Content-Type': 'application/x-www-form-urlencoded',
                                   'Authorization': 'Bearer ' + values['LOCAL_RETRIEVAL_API_KEY']},
                          data=urlencode({'query': '项目结转后怎么撤销？',
                                          'route': 'projects_finance', 'top_k': 6}).encode())
        barrier.wait(timeout=10)
        started = time.monotonic()
        try:
            with urlopen(request, timeout=120) as response:
                data = json.load(response)
            top = data['results'][0]
            return {'status': 200, 'correct_source': top['id'] == '2519c00a7aa329e5-projects-002',
                    'page_17': 17 in top['pages'], 'cj88': 'CJ88' in top['content'],
                    'has_image': top.get('image_count', 0) > 0,
                    'seconds': round(time.monotonic() - started, 2)}
        except HTTPError as exc:
            return {'status': exc.code, 'seconds': round(time.monotonic() - started, 2)}

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(lambda _: call(), range(2)))
    return {'passed': all(r['status'] == 200 and all(r[k] for k in
                         ('correct_source', 'page_17', 'cj88', 'has_image')) for r in results),
            'requests': results}


if __name__ == '__main__':
    result = verify(Path(__file__).resolve().parents[1])
    print(json.dumps(result, ensure_ascii=True))
    raise SystemExit(0 if result['passed'] else 1)
