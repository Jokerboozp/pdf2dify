import importlib.util
from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_cover_name_can_be_in_a_later_chunk_on_page_one():
    from ops_rag.process_catalog import names_from_source
    chunks = [{'regions': [{'page': 1, 'text': '', 'tables': []}]},
              {'regions': [{'page': 1, 'text': '流程名称 财务月结业务流程', 'tables': []}]}]
    names = names_from_source({'name': '0.财务月结操作手册.pdf'}, chunks)
    assert names['title'] == '财务月结业务流程'
    assert '财务月结' in names['aliases']


def test_missing_cover_uses_filename_without_claiming_a_formal_process_name():
    from ops_rag.process_catalog import names_from_source
    names = names_from_source({'name': '1.原油生产入库.pdf'}, [{'regions': [{'page': 1, 'text': '培训资料'}]}])
    assert names['name_basis'] == 'filename'
    assert names['title'] == '原油生产入库'
    assert names['name_evidence'] == []


def test_duplicate_cover_names_preserve_specific_file_topic():
    from ops_rag.process_catalog import names_from_source
    names = names_from_source({'name': '2.财务月结-项目结转操作手册-成本核算岗.pdf'},
                             [{'regions': [{'page': 1, 'text': '流程名称 财务月结业务流程'}]}])
    assert '项目结转' in names['filename_topic']
    assert names['title'] == '财务月结业务流程'


def test_continuation_pages_merge_in_full_outline_without_changing_order():
    from ops_rag.process_catalog import outline_from_chunks
    result = outline_from_chunks([
        {'section_index': 1, 'title': '2.维修工单结转', 'pages': [24, 25], 'chunk_id': 'a'},
        {'section_index': 1, 'title': '2.维修工单结转', 'pages': [26, 27], 'chunk_id': 'b'},
        {'section_index': 2, 'title': '3.项目成本结转', 'pages': [41], 'chunk_id': 'c'}])
    assert [r['title'] for r in result] == ['2.维修工单结转', '3.项目成本结转']
    assert result[0]['pages'] == [24, 25, 26, 27]


def test_real_month_close_overview_covers_all_major_branches():
    from ops_rag.process_catalog import make_record, paragraphs
    from ops_rag.common import read_json
    record = make_record(read_json(ROOT/'data/corpus/6531b3feb04af8c5.json'))
    text = '\n'.join(paragraphs(record))
    for name in ['维修工单结转', '项目成本结转', '制造费用分摊', '主营及其他业务成本结转',
                 '油气生产成本', '输油输气业务月末结转']:
        assert name in text
    assert '不代表所有环节必须依次执行' in text
    assert 'PDF 第148–152页' in text


def test_short_manual_keeps_native_steps_when_no_summary_section_exists():
    from ops_rag.process_catalog import make_record, paragraphs
    from ops_rag.common import read_json
    record = make_record(read_json(ROOT/'data/corpus/de5029274b6e30c6.json'))
    assert not record['has_process_description']
    assert record['overview_evidence']
    text = '\n'.join(paragraphs(record))
    assert 'MMBE' in text and 'MB5B' in text
    assert '创建表格' in text, 'Step 1 on PDF page 2 must not be dropped as a presumed cover'
    assert '不把局部操作声称为全部流程' in text


def test_flow_name_has_a_dedicated_overview_path():
    spec = importlib.util.spec_from_file_location('flow_builder', ROOT/'scripts/build_full_chatflow.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from ops_rag.corpus import DOMAINS
    graph = module.build({key: key for key in DOMAINS})['workflow']['graph']
    nodes = {n['id']: n['data'] for n in graph['nodes']}
    # The original failure returned cover fragments from ordinary Top K retrieval.
    assert 'select_process' in nodes, 'Bare process names must resolve against the full source catalog'
    assert 'retrieve_process' in nodes, 'Overview must retrieve the source-wide navigation parent'
    assert nodes['retrieve_process']['metadata_filtering_mode'] == 'manual'
    assert nodes['retrieve_process']['multiple_retrieval_config']['top_k'] == 1
    assert nodes['process_found']['cases'][0]['conditions'][0]['comparison_operator'] == 'not empty'
    assert nodes['process_has_content']['cases'][0]['conditions'][0]['variable_selector'] == ['retrieve_process','result']
    assert any(e['source']=='process_has_content' and e['sourceHandle']=='false' and e['target']=='process_unavailable' for e in graph['edges'])


def test_finance_followup_restricts_source_and_condition_branch():
    spec = importlib.util.spec_from_file_location('flow_scope_builder', ROOT/'scripts/build_full_chatflow.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    from ops_rag.corpus import DOMAINS
    graph = module.build({key: key for key in DOMAINS})['workflow']['graph']
    nodes = {n['id']: n['data'] for n in graph['nodes']}
    assert 'select_source_finance' in nodes
    filters = nodes['retrieve_finance']['metadata_filtering_conditions']['conditions']
    assert any(c['name'] == 'section_title' and 'section_prefix' in c['value'] for c in filters)
    assert nodes['retrieve_finance']['multiple_retrieval_config']['top_k']==6
    assert nodes['retrieve_finance_scoped']['multiple_retrieval_config']['top_k']==20
    assert {c['variable_selector'][-1] for c in nodes['finance_scope']['cases'][0]['conditions']}=={'source_id','section_prefix'}
    assert nodes['grounded_finance_scoped']['context']['variable_selector']==['retrieve_finance_scoped','result']
    scopes = module.finance_scopes(module.json.loads((ROOT/'data/process-navigation/catalog.json').read_text(encoding='utf-8'))['records'])
    listed = [s for s in scopes if s['source_id']=='0e18bf85322fcdb5' and s['prefix']=='1.1.']
    assert len(listed)==1 and listed[0]['title']=='1.1 制造费用分摊（上市）'
    docs=module.json.loads((ROOT/'data/full-export/manifest.json').read_text(encoding='utf-8'))['documents']
    matching=[d for d in docs if d['source_id']==listed[0]['source_id'] and listed[0]['prefix'] in d['metadata']['section_title']]
    assert len(matching)==5
    assert max(p for d in matching for p in d['pages'])==9
    from ops_rag.full_sync import retrieval_model, payload
    assert retrieval_model('finance')['top_k']==20
    assert payload('finance')['retrieval_model']['top_k']==20
    assert retrieval_model('projects')['top_k']==6
