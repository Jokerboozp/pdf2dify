"""Read-only checks of native Dify configuration, recall and managed images."""
from concurrent.futures import ThreadPoolExecutor
import json
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
import httpx
import yaml
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect, retrieval_model


def main():
    cfg = config()
    root = Path(cfg['data_dir'])
    client = connect(cfg)
    state = read_json(root / 'dify/full-state.json')
    nav = read_json(root / 'process-navigation/dify/full-state.json')
    datasets = {**state['datasets'], **nav['datasets']}

    def inspect(item):
        domain, entry = item
        detail = client.call('GET', f"datasets/{entry['id']}")
        model = detail['retrieval_model_dict']
        return {'domain': domain, 'id': entry['id'], 'name': entry['name'],
                'indexing_technique': detail['indexing_technique'],
                'embedding_provider': detail['embedding_model_provider'],
                'embedding_model': detail['embedding_model'], 'retrieval': model,
                'documents': detail.get('document_count'), 'segments': detail.get('segment_count'),
                'passed': detail['indexing_technique'] == 'high_quality'
                    and model['search_method'] == 'hybrid_search'
                    and model.get('reranking_mode') == 'weighted_score'}

    with ThreadPoolExecutor(max_workers=3) as pool:
        settings = list(pool.map(inspect, datasets.items()))
    ds = state['datasets']['projects']['id']
    rows = []
    image_url = None
    for query in ('项目结转后怎么撤销？', '项目结转后如何取消结转', '项目已经结转，如何冲销撤销？'):
        result = client.call('POST', f'datasets/{ds}/retrieve', timeout=180,
                             json={'query': query, 'retrieval_model': retrieval_model()})
        records = result.get('records', [])
        hits = [r['segment'] for r in records
                if r['segment']['document']['name'] == 'ops-2519c00a7aa329e5-projects-002.docx']
        urls = re.findall(r'!\[[^\]]*\]\(([^)]+)\)', hits[0]['content']) if hits else []
        if urls:
            image_url = urls[0]
        rows.append({'query': query, 'hit': bool(hits), 'has_images': bool(urls),
                     'cj88': bool(hits and 'CJ88' in hits[0]['content']),
                     'all_images_managed_by_dify': all('/files/' in u and 'file-preview' in u
                         and ':8765' not in u for u in urls)})
    base = str(client.client.base_url)
    origin = urlsplit(base)
    image_ok = False
    if image_url:
        url = urljoin(f'{origin.scheme}://{origin.netloc}/', image_url)
        assert urlsplit(url).netloc == origin.netloc
        response = httpx.get(url, timeout=30)
        image_ok = response.status_code == 200 and response.headers.get('content-type', '').startswith('image/')
    dsl = yaml.safe_load((Path(cfg['project_root']) / 'dify/chatflow-full.yml').read_text(encoding='utf-8'))
    nodes = dsl['workflow']['graph']['nodes']
    native = not any(n['data']['type'] in ('http-request', 'code') for n in nodes)
    native = native and ':8765' not in json.dumps(dsl) and not dsl['workflow']['environment_variables']
    report = {'checked_at': now(), 'datasets': settings, 'project_queries': rows,
              'dify_image_http_ok': image_ok,
              'image_response': {'status': response.status_code, 'type': response.headers.get('content-type'),
                                 'path': urlsplit(url).path} if image_url else None,
              'native_workflow_only': native,
              'retrieval_nodes': sum(n['data']['type'] == 'knowledge-retrieval' for n in nodes)}
    # Dataset Service API returns stored unsigned references. The native workflow
    # creates signed preview URLs; image rendering must be checked in its real UI.
    report['ui_image_acceptance_required'] = True
    report['passed'] = all(x['passed'] for x in settings) and all(all(x[k] for k in
                        ('hit', 'has_images', 'cj88', 'all_images_managed_by_dify')) for x in rows) and native
    report['scope'] = 'Knowledge configuration, source recall and managed image references; actual signed image display requires UI acceptance'
    write_json(root / 'reports/native-readiness.json', report)
    print(json.dumps({k: v for k, v in report.items() if k != 'datasets'}, ensure_ascii=True))
    if not report['passed']:
        raise SystemExit(1)


if __name__ == '__main__':
    main()
