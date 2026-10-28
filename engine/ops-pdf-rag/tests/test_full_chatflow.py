import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import build_full_chatflow as builder


def record(key, domains):
    return {'key': key, 'source_id': key, 'domains': domains, 'filename_topic': key + '手册',
            'aliases': [key], 'outline': []}


def document(key, domain, source_id):
    return {'key': key, 'domain': domain, 'source_id': source_id, 'source_name': source_id + '.pdf',
            'metadata': {'section_title': '操作步骤'}}


def build(dataset_ids):
    return builder.build(
        dataset_ids, process_dataset='nav-id',
        process_records=[record('s1', ['projects']), record('s2', ['custom_tech'])],
        documents=[document('d1', 'projects', 's1'), document('d2', 'custom_tech', 's2')],
        labels={'custom_tech': '科技分类'}, app_name='测试助手')


def test_routes_follow_synced_datasets_including_custom_categories():
    dsl = build({'projects': 'p-id', 'finance': 'f-id', 'custom_tech': 'c-id'})
    nodes = {n['id']: n['data'] for n in dsl['workflow']['graph']['nodes']}
    routes = nodes['normalize']['structured_output']['schema']['properties']['route']['enum']
    assert routes == ['finance', 'projects', 'custom_tech', 'projects_finance', 'clarify']
    prompt = nodes['normalize']['prompt_template'][0]['text']
    assert 'custom_tech：科技分类相关业务资料。' in prompt
    assert '\nequipment：' not in prompt and 'master_ops' not in prompt.split('clarify：')[0]
    assert nodes['retrieve_custom_tech']['dataset_ids'] == ['c-id']
    assert nodes['retrieve_projects_finance']['dataset_ids'] == ['p-id', 'f-id']
    assert '科技分类' in nodes['select_process']['prompt_template'][0]['text']
    assert dsl['app']['name'] == '测试助手'
    features = dsl['workflow']['features']
    assert '项目管理、财务核算、科技分类' in features['opening_statement'] and '财务月结' not in features['opening_statement']
    assert features['suggested_questions'] == ['s1手册', 's2手册']
    for edge in dsl['workflow']['graph']['edges']:
        assert edge['source'] in nodes and edge['target'] in nodes
    assert all(n['reasoning_format'] == 'separated' for n in nodes.values() if n['type'] == 'llm')


def test_unnamed_category_is_rejected():
    try:
        builder.build({'mystery': 'm-id'}, process_dataset='nav-id', process_records=[], documents=[])
    except ValueError as exc:
        assert 'mystery' in str(exc)
    else:
        raise AssertionError('expected ValueError')
