from copy import deepcopy
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
import threading
import numpy as np
import pytest
from fastapi.testclient import TestClient
from ops_rag import hybrid
from ops_rag.common import write_json
from ops_rag.search_api import create_app


class Encoder:
    calls = 0
    def embed(self, texts, **kwargs):
        for text in texts:
            self.calls += 1
            yield np.array([1., 0.]) if '维修' in text else np.array([0., 1.])
    def query_embed(self, query):
        yield np.array([1., 0.])


class Reranker:
    def rerank(self, query, documents, **kwargs):
        return [6. if '维修' in d else -2. for d in documents]


def test_semantic_only_top_hit_is_not_lost_at_fusion_cutoff():
    lexical = list(range(60))
    semantic = [999] + list(range(59))
    fused, _ = hybrid.rrf([lexical, semantic])
    assert fused.index(999) >= 24  # The original failure: weak dual hits crowd it out.
    candidates = hybrid.rerank_candidates(fused, lexical, semantic, 24)
    assert 999 in candidates and set(lexical[:3]).issubset(candidates)
    assert len(candidates) == len(set(candidates)) == 24


@pytest.fixture
def fixture(tmp_path, monkeypatch):
    root = tmp_path
    for path, value in [('full-export/manifest.json', {'documents': []}),
                         ('process-navigation/catalog.json', {'records': []})]:
        write_json(root/path, value)
    docs = [
        {'id': 'a', 'title': '1.1.普通结转', 'topic': '项目', 'content': '普通项目结转', 'source_id': 'a', 'domains': ['projects'],
         'metadata': {'section_title': '1.1.普通结转'}, 'source_name': 'a.pdf', 'pages': [1], 'kind': 'detail', 'images': []},
        {'id': 'b', 'title': '1.2.维修冲销', 'topic': '设备', 'content': '维修工单结算后撤销', 'source_id': 'b', 'domains': ['equipment'],
         'metadata': {'section_title': '1.2.维修冲销'}, 'source_name': 'b.pdf', 'pages': [2], 'kind': 'detail',
         'images': [{'path': 'assets/b/image.png', 'page': 2, 'image_id': 'b-image'}]},
    ]
    monkeypatch.setattr(hybrid, 'load_documents', lambda cfg: deepcopy(docs))
    cfg = {'data_dir': str(root), 'project_root': str(root)}
    encoder = Encoder()
    hybrid.build_index(cfg, embedder=encoder)
    return cfg, docs, encoder


def test_semantic_candidate_survives_and_reranker_promotes_it(fixture):
    cfg, _, encoder = fixture
    search = hybrid.HybridSearch(cfg, encoder=encoder, reranker=Reranker())
    assert search.search('普通项目结转', mode='bm25')['results'][0]['id'] == 'a'
    ranked = search.search('普通项目结转', mode='hybrid')['results']
    assert ranked[0]['id'] == 'b'
    assert ranked[0]['content'] == '维修工单结算后撤销'
    assert ranked[0]['images'][0]['page'] == 2


def test_filters_apply_before_both_recalls_and_never_expand(fixture):
    cfg, _, encoder = fixture
    search = hybrid.HybridSearch(cfg, encoder=encoder, reranker=Reranker())
    for mode in ('bm25', 'vector', 'fusion', 'hybrid'):
        assert search.search('项目', mode=mode, source_id='missing')['results'] == []
        hits = search.search('项目', mode=mode, domains=['projects'], section_prefix='1.1.')['results']
        assert hits and all(h['id'] == 'a' for h in hits)


def test_incremental_cache_removal_and_stale_detection(fixture):
    cfg, docs, encoder = fixture
    initial_calls = encoder.calls
    initial_snapshot = hybrid.HybridSearch(cfg).info['snapshot']
    result = hybrid.build_index(cfg, embedder=encoder)
    assert encoder.calls == initial_calls
    assert result['unchanged'] and result['snapshot'] == initial_snapshot
    docs.pop(0)
    hybrid.build_index(cfg, embedder=encoder)
    assert [d['id'] for d in hybrid.HybridSearch(cfg).docs] == ['b']
    write_json(Path(cfg['data_dir'])/'full-export/manifest.json', {'documents': [{'new': True}]})
    with pytest.raises(ValueError, match='stale'):
        hybrid.HybridSearch(cfg)


def test_failed_build_does_not_publish_partial_index(fixture):
    cfg, docs, _ = fixture
    before = hybrid.HybridSearch(cfg).info['snapshot']
    docs[0]['content'] = 'Changed input'
    class Failing:
        def embed(self, texts, **kwargs): raise RuntimeError('interrupted')
    with pytest.raises(RuntimeError): hybrid.build_index(cfg, embedder=Failing())
    assert hybrid.HybridSearch(cfg).info['snapshot'] == before


def test_api_auth_form_and_signed_allowlisted_images(fixture, monkeypatch):
    cfg, _, encoder = fixture
    monkeypatch.setenv('LOCAL_RETRIEVAL_API_KEY', 'x'*40)
    monkeypatch.setenv('LOCAL_RETRIEVAL_URL', 'http://testserver')
    path = Path(cfg['data_dir'])/'assets/b/image.png'
    path.parent.mkdir(parents=True)
    path.write_bytes(b'local image fixture')
    engine = hybrid.HybridSearch(cfg, encoder=encoder, reranker=Reranker())
    with TestClient(create_app(cfg, engine=engine)) as client:
        assert client.post('/search', json={'query': '维修'}).status_code == 401
        headers = {'Authorization': 'Bearer ' + 'x'*40}
        assert client.post('/search', headers=headers, json={'query': '维修', 'route': 'unknown'}).status_code == 422
        response = client.post('/search-form', headers=headers, data={'query': '维修"\n怎么办', 'route': 'equipment'})
        assert response.status_code == 200
        content = response.json()['results'][0]['content']
        url = content[content.index('http://'):].split(')')[0]
        assert client.get(url).status_code == 200
        assert client.get(url.replace('signature=', 'signature=bad')).status_code == 403
        assert client.get('/assets/assets/b/image.png?expires=0&signature=x').status_code == 403


def test_overlapping_form_requests_wait_for_running_inference(fixture, monkeypatch):
    cfg, _, encoder = fixture
    monkeypatch.setenv('LOCAL_RETRIEVAL_API_KEY', 'x'*40)
    monkeypatch.setenv('LOCAL_RETRIEVAL_URL', 'http://testserver')
    engine = hybrid.HybridSearch(cfg, encoder=encoder, reranker=Reranker())
    original = engine.search
    entered, release = threading.Event(), threading.Event()

    def slow_search(*args, **kwargs):
        entered.set()
        assert release.wait(10)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, 'search', slow_search)
    with TestClient(create_app(cfg, engine=engine)) as client, ThreadPoolExecutor(2) as pool:
        def call():
            return client.post('/search-form', headers={'Authorization': 'Bearer ' + 'x'*40},
                               data={'query': '维修', 'route': 'equipment'})
        first = pool.submit(call)
        assert entered.wait(5)
        second = pool.submit(call)
        # Real request overlap exceeds the old two-second lock deadline.
        timer = threading.Timer(2.5, release.set)
        timer.start()
        try:
            responses = [first.result(10), second.result(10)]
            assert [r.status_code for r in responses] == [200, 200]
            assert all(r.json()['results'][0]['id'] == 'b' for r in responses)
        finally:
            release.set()
            timer.cancel()


@pytest.mark.parametrize('capacity', [1, 2])
def test_queue_limits_release_slots_and_keep_health_available(fixture, monkeypatch, capacity):
    cfg, _, encoder = fixture
    cfg['retrieval_service'] = {'max_pending_requests': capacity, 'queue_wait_seconds': 0.05}
    monkeypatch.setenv('LOCAL_RETRIEVAL_API_KEY', 'x'*40)
    monkeypatch.setenv('LOCAL_RETRIEVAL_URL', 'http://testserver')
    engine = hybrid.HybridSearch(cfg, encoder=encoder, reranker=Reranker())
    original = engine.search
    entered, release = threading.Event(), threading.Event()

    def slow_search(*args, **kwargs):
        entered.set()
        assert release.wait(5)
        return original(*args, **kwargs)

    monkeypatch.setattr(engine, 'search', slow_search)
    with TestClient(create_app(cfg, engine=engine)) as client, ThreadPoolExecutor(1) as pool:
        def call():
            return client.post('/search', headers={'Authorization': 'Bearer ' + 'x'*40},
                               json={'query': '维修', 'route': 'equipment'})
        first = pool.submit(call)
        try:
            assert entered.wait(5)
            rejected = call()
            assert rejected.status_code == 429
            assert rejected.headers['Retry-After'] == '5'
            assert ('full' if capacity == 1 else 'timed out') in rejected.json()['detail']
            assert client.get('/health').json()['status'] == 'ready'
        finally:
            release.set()
        assert first.result(5).status_code == 200
        # An overflow or timeout must not leak a slot or the inference lock.
        assert call().status_code == 200


def test_local_dsl_preserves_scope_and_guards_answers():
    import yaml
    root = Path(__file__).resolve().parents[1]
    dsl = yaml.safe_load((root/'dify/chatflow-local.yml').read_text(encoding='utf-8'))
    nodes = {n['id']: n['data'] for n in dsl['workflow']['graph']['nodes']}
    assert dsl['workflow']['environment_variables'][0]['value'] == ''
    assert nodes['retrieve_process']['type'] == 'knowledge-retrieval'
    assert not any(n['type'] == 'code' for n in nodes.values())
    for nid, node in nodes.items():
        if node['type'] != 'http-request': continue
        fields = {f['key']: f['value'] for f in node['body']['data']}
        assert fields['query'] == '{{#normalize.structured_output.query#}}'
        if fields['route'] == 'finance':
            assert 'section_prefix' in fields and 'source_id' in fields
        llm = nodes[nid.replace('retrieve_', 'grounded_', 1)]
        assert '{{#'+nid+'.body#}}' in llm['prompt_template'][0]['text']
        assert nodes[nid+'_available']['cases'][0]['conditions'][0]['value'] == '200'
    for e in dsl['workflow']['graph']['edges']:
        assert e['source'] in nodes and e['target'] in nodes
        assert e['data']['sourceType'] == nodes[e['source']]['type']
        assert e['data']['targetType'] == nodes[e['target']]['type']
