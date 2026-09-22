"""Keep established routing/overview; replace detail retrieval with local BM25+BGE+rerank."""
from copy import deepcopy
import json
import os
from pathlib import Path
import uuid
import yaml
from ops_rag.common import load_env
from build_full_chatflow import build, node, edge

ROOT = Path(__file__).resolve().parents[1]


def localize(dsl, url, token=''):
    dsl = deepcopy(dsl)
    workflow = dsl['workflow']
    workflow['environment_variables'] = [
        {'id': '89052461-b125-4dd4-939a-a10c341f0821', 'name': 'LOCAL_RETRIEVAL_TOKEN',
         'value_type': 'secret', 'value': token, 'description': 'Local read-only retrieval authentication'},
    ]
    nodes, edges = workflow['graph']['nodes'], workflow['graph']['edges']
    retrievals = [n for n in nodes if n['data']['type'] == 'knowledge-retrieval' and n['id'] != 'retrieve_process']
    for n in retrievals:
        rid = n['id']
        route = rid.removeprefix('retrieve_').removesuffix('_scoped')
        fields = {'query': '{{#normalize.structured_output.query#}}', 'route': route,
                  'kind': 'detail', 'top_k': '20' if rid.endswith('_scoped') else '6'}
        if route in ('master_ops', 'funds', 'finance'):
            fields['source_id'] = '{{#select_source_' + route + '.structured_output.source_id#}}'
        if route == 'finance':
            fields['section_prefix'] = '{{#select_source_finance.structured_output.section_prefix#}}'
        n['data'] = {'type': 'http-request', 'title': '本地混合检索与重排 · '+n['data']['title'],
                     'desc': '', 'selected': False, 'method': 'post', 'url': url.rstrip('/')+'/search-form',
                     'authorization': {'type': 'api-key', 'config': {'type': 'bearer', 'api_key': '{{#env.LOCAL_RETRIEVAL_TOKEN#}}'}},
                     'headers': 'Content-Type:application/x-www-form-urlencoded', 'params': '',
                     'body': {'type': 'x-www-form-urlencoded', 'data': [
                         {'id': str(uuid.uuid5(uuid.NAMESPACE_URL, rid+'/'+k)), 'key': k, 'type': 'text', 'value': v} for k,v in fields.items()]},
                     'timeout': {'connect': 10, 'read': 120, 'write': 30}, 'ssl_verify': True,
                     'retry_config': {'retry_enabled': False, 'max_retries': 0, 'retry_interval': 1000}}
        lid = rid.replace('retrieve_', 'grounded_', 1)
        llm = next(x['data'] for x in nodes if x['id'] == lid)
        llm['context'] = {'enabled': False, 'variable_selector': []}
        llm['prompt_template'][0]['text'] = llm['prompt_template'][0]['text'].replace('{{#context#}}', '{{#'+rid+'.body#}}')
        llm['prompt_template'][0]['text'] += ('\n24. 上述 JSON 是本地检索证据。仅 results 中的 content 可以作为操作依据；'
            'matched_text 用于定位，不代表全流程。分数只表示检索相关性，不是正确率或业务审批结果。'
            'results 为空时说明本次未找到依据。继续保留与本轮问题匹配的原文图片 Markdown 和 PDF 页码。')
        for e in edges:
            if e['target'] == rid: e['data']['targetType'] = 'http-request'
            if e['source'] == rid: e['data']['sourceType'] = 'http-request'
        gate, unavailable = rid+'_available', rid+'_unavailable'
        edges[:] = [e for e in edges if not (e['source'] == rid and e['target'] == lid)]
        x, y = n['position']['x'], n['position']['y']
        nodes.extend([
            node(gate, 'if-else', '检索服务返回成功', x+150, y-90, cases=[{'id': 'ready', 'case_id': 'ready', 'logical_operator': 'and', 'conditions': [
                {'id': rid+'-status', 'variable_selector': [rid, 'status_code'], 'comparison_operator': '=', 'value': '200', 'varType': 'number'}]}]),
            node(unavailable, 'answer', '检索服务暂不可用', x+450, y-90, answer='检索服务暂不可用，请稍后重试。本次尚未核实操作依据。', variables=[]),
        ])
        edges.extend([edge(rid, gate, 'http-request', 'if-else'), edge(gate, lid, 'if-else', 'llm', 'ready'),
                      edge(gate, unavailable, 'if-else', 'answer', 'false')])
    dsl['app']['description'] = '9个业务主题，流程导航；本地 BM25 + 中文向量 + BGE 重排，原文图文溯源。'
    return dsl


def main():
    load_env(ROOT)
    state = json.loads((ROOT/'data/dify/full-state.json').read_text(encoding='utf-8'))
    original = build({k: v['id'] for k, v in state['datasets'].items()})
    url = os.environ['LOCAL_RETRIEVAL_URL']
    template = localize(original, url)
    (ROOT/'dify/chatflow-local.yml').write_text(yaml.safe_dump(template, allow_unicode=True, sort_keys=False), encoding='utf-8')
    ready = localize(original, url, os.environ['LOCAL_RETRIEVAL_API_KEY'])
    target = ROOT/'data/dify/chatflow-local-private.yml'
    target.write_text(yaml.safe_dump(ready, allow_unicode=True, sort_keys=False), encoding='utf-8')
    print('Template: dify/chatflow-local.yml; private import artifact written under ignored data/dify/')


if __name__ == '__main__': main()
