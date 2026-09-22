from concurrent.futures import ThreadPoolExecutor
import importlib.util
from pathlib import Path
from ops_rag.common import write_json, read_json
from ops_rag.corpus import classify, chunk_sections, DOMAINS, xml_text
from ops_rag.full_sync import payload
import pytest


def test_finance_faq_routes_by_actual_business_object():
    doc = {'name': '财务模块常见问题.pdf', 'relative_path': '培训/财务模块常见问题.pdf'}
    assert classify(doc, 17) == 'projects'
    assert classify(doc, 18) == 'equipment'
    assert classify(doc, 30) == 'funds'
    assert classify(doc, 52) == 'internal'
    assert classify(doc, 24) == 'finance'


def test_standard_not_misrouted_as_master_operation():
    doc = {'name': '物料标准.pdf', 'relative_path': '手册/主数据管理/3.公共数据管理标准/物料标准.pdf'}
    assert classify(doc) == 'master_rules'


def test_xml_controls_are_marked_without_losing_negation_or_codes():
    assert xml_text('不得\x00冲销\nCJ88\t01') == '不得\ufffd冲销\nCJ88\t01'


def test_continuation_preserves_pages_and_all_images():
    doc = {'name': '设备.pdf', 'source_id': 's'}
    regions = [{'page': n, 'text': '操作前提\n不得重复提交',
                'images': [{'image_id': f'{n}-{i}'} for i in range(7)]} for n in range(1, 4)]
    chunks = chunk_sections(doc, [{'title':'维修流程','domain':'equipment','regions':regions}])
    assert len(chunks) == 3
    assert all(c['parts'] == 3 and c['notes'] for c in chunks)
    assert [r['page'] for c in chunks for r in c['regions']] == [1,2,3]
    assert sum(len(r['images']) for c in chunks for r in c['regions']) == 21
    assert all('不得重复提交' in r['text'] for c in chunks for r in c['regions'])


def test_slide_page_numbers_do_not_break_the_procedure():
    from ops_rag.corpus import section_boundaries
    class PDF:
        def get_toc(self): return []
    pages=[{'page':1,'text':'采购培训\n1'},
           {'page':2,'text':'6、退料申请操作\n79 79'},
           {'page':3,'text':'80 80'},
           {'page':4,'text':'81 / 81'},
           {'page':5,'text':'7、退货流程\n82'}]
    boundaries=section_boundaries({'name':'培训.pdf'},PDF(),pages)
    assert [(b['page'],b['title']) for b in boundaries]==[
        (1,'资料说明与适用范围'),(2,'6、退料申请操作'),(5,'7、退货流程')]


def test_concurrent_cache_writes_remain_atomic(tmp_path):
    target = tmp_path / 'cache.json'
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: write_json(target, {'n': n, 'payload': str(n)*1000}), range(30)))
    result = read_json(target)
    assert result['payload'] == str(result['n'])*1000
    assert not list(tmp_path.glob('*.tmp'))


def test_full_doc_parent_and_local_embedding():
    config = payload()
    assert config['doc_form'] == 'hierarchical_model'
    assert config['process_rule']['rules']['parent_mode'] == 'full-doc'
    assert config['process_rule']['rules']['subchunk_segmentation']['max_tokens'] <= 500


def test_search_anchor_uses_source_question_without_invented_answers():
    from ops_rag.search_anchors import anchor_text
    item={'source_name':'财务模块常见问题.pdf','metadata':{'section_title':'项目结转后如何取消结转'}}
    assert anchor_text(item)=='检索主题：项目结转后如何取消结转。'
    item['metadata']['section_title']='目录'
    assert anchor_text(item) is None


def test_uncertain_child_create_reconciles_without_duplicate_post():
    from ops_rag.search_anchors import ensure_child
    class Client:
        def __init__(self): self.created=False; self.calls=[]
        def call(self, method, path, **kwargs):
            self.calls.append(method)
            if method=='GET':
                return {'data':[{'id':'existing','content':'topic'}] if self.created else [],'total_pages':1}
            if method=='POST':
                self.created=True
                raise RuntimeError('HTTP 400 after server commit')
            assert method=='PATCH' and path.endswith('/existing')
            return {'data':{'id':'existing','content':'topic'}}
    client=Client()
    assert ensure_child(client,'children','topic')['id']=='existing'
    assert client.calls==['GET','POST','GET','PATCH']


def test_failed_child_create_without_server_record_remains_failed():
    from ops_rag.search_anchors import ensure_child
    class Client:
        def call(self, method, path, **kwargs):
            if method=='GET': return {'data':[],'total_pages':1}
            raise RuntimeError('HTTP 400 before commit')
    with pytest.raises(RuntimeError,match='before commit'):
        ensure_child(Client(),'children','topic')


def test_partial_corpus_never_retires_existing_documents(tmp_path):
    from ops_rag.full_sync import retire_stale
    write_json(tmp_path/'full-export/manifest.json', {
        'built_sources': 1, 'source_count': 2, 'pending_sources': ['still-processing'], 'documents': []})
    with pytest.raises(ValueError, match='complete corpus'):
        retire_stale({'data_dir': str(tmp_path)}, apply=True)


def test_retirement_preserves_provenance_metadata(tmp_path, monkeypatch):
    from ops_rag import full_sync
    write_json(tmp_path/'full-export/manifest.json', {
        'built_sources': 1, 'source_count': 1, 'pending_sources': [], 'documents': [{'key':'current','content_hash':'h'}]})
    write_json(tmp_path/'dify/full-state.json', {'base_url':'http://local/v1', 'documents': {
        'old': {'document_id':'doc','dataset_id':'ds'}, 'current': {'document_id':'keep','dataset_id':'ds','hash':'h','metadata_applied':True}}})
    calls=[]
    class Client:
        def documents(self, ds):
            return [{'id':'keep','indexing_status':'completed','enabled':True}]
        def call(self, method, path, **kwargs):
            calls.append((method,path,kwargs))
            if path.endswith('/metadata') and method=='GET':
                return {'doc_metadata':[{'id':'v','name':'validity_status'}]}
            if method=='GET': return {'doc_metadata':[
                {'id':'s','name':'source_id','value':'original'},
                {'id':'v','name':'validity_status','value':'unconfirmed'},
                {'id':'built-in','name':'document_name','value':'title'}]}
            return {'result':'success'}
    monkeypatch.setattr(full_sync,'connect',lambda cfg:Client())
    monkeypatch.setenv('DIFY_BASE_URL','http://local/v1')
    full_sync.retire_stale({'data_dir':str(tmp_path)},apply=True)
    posted=[c for c in calls if c[0]=='POST'][0][2]['json']['operation_data'][0]
    assert posted['metadata_list']==[{'id':'s','name':'source_id','value':'original'},
                                    {'id':'v','name':'validity_status','value':'retired'}]
    assert read_json(tmp_path/'dify/full-state.json')['documents']['old']['retired_at']


def test_workflow_routes_are_bounded_and_reachable():
    path = Path(__file__).parents[1] / 'scripts/build_full_chatflow.py'
    spec = importlib.util.spec_from_file_location('build_full_chatflow', path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    dsl = module.build({k: 'id-'+k for k in DOMAINS})
    graph = dsl['workflow']['graph']
    nodes = {n['id']: n['data'] for n in graph['nodes']}
    assert len(nodes) == len(graph['nodes'])
    assert not any(n['type'] == 'code' for n in nodes.values())
    for node in nodes.values():
        if node['type'] == 'knowledge-retrieval':
            assert 1 <= len(node['dataset_ids']) <= 2
        if node['type'] == 'llm':
            assert not node['vision']['enabled']
    reachable = {'start'}
    for _ in nodes:
        for e in graph['edges']:
            assert e['source'] in nodes and e['target'] in nodes
            if e['source'] in reachable: reachable.add(e['target'])
    assert reachable == nodes.keys()
    route = nodes['route']
    for case in route['cases']:
        assert any(e['source']=='route' and e['sourceHandle']==case['case_id'] for e in graph['edges'])


def test_target_audit_does_not_count_old_content_as_ready():
    from ops_rag.full_sync import audit_target
    item={'key':'a','content_hash':'new','source_name':'常见问题.pdf','metadata':{'section_title':'如何冲销'}}
    result=audit_target([item], {'a':{'document_id':'doc','hash':'old','metadata_applied':True}},
                        [{'id':'doc','indexing_status':'completed','enabled':True}], {})
    assert result['counts']['ready']==0
    assert result['counts']['submitted_current']==0
    assert result['pending'][0]['status']=='completed'


def test_upload_defers_queued_document_replacement(tmp_path, monkeypatch):
    from ops_rag import full_sync
    write_json(tmp_path/'full-export/manifest.json', {'documents':[
        {'key':'a','domain':'projects','content_hash':'new','path':'a.docx','metadata':{},'source_id':'s'}]})
    write_json(tmp_path/'dify/full-state.json', {'base_url':'http://local/v1',
        'datasets':{'projects':{'id':'ds'}},'documents':{
        'a':{'document_id':'doc','hash':'old','metadata_applied':True}}})
    class Client:
        def documents(self, ds):
            return [{'id':'doc','name':'a.docx','display_status':'queuing','indexing_status':'waiting'}]
        def call(self, method, path, **kwargs):
            assert method=='GET' and path.endswith('/metadata')
            return {'doc_metadata':[]}
    monkeypatch.setattr(full_sync,'connect',lambda cfg:Client())
    monkeypatch.setenv('DIFY_BASE_URL','http://local/v1')
    result=full_sync.upload({'data_dir':str(tmp_path)})
    assert result['submitted_now']==0
    assert result['deferred_updates'][0]['key']=='a'


def test_search_context_keeps_listed_and_unlisted_procedures_separate(tmp_path):
    from ops_rag.search_anchors import _condition_contexts
    p=tmp_path/'source.json'
    write_json(p,{'chunks':[
        {'chunk_id':'a','title':'1.1 制造费用分摊（上市）'},
        {'chunk_id':'b','title':'1.1.4 制造费用分摊-成本核算岗'},
        {'chunk_id':'c','title':'1.2 制造费用分摊（未上市）'},
        {'chunk_id':'d','title':'1.2.2 制造费用分摊执行'}]})
    result=_condition_contexts(str(p),p.stat().st_mtime_ns)
    assert result['b']=='1.1 制造费用分摊（上市）'
    assert result['d']=='1.2 制造费用分摊（未上市）'
