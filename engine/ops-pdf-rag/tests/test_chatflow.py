from pathlib import Path
import yaml


def test_live_compatible_flow_has_no_sandbox_and_nested_output_paths_resolve():
    root = Path(__file__).resolve().parents[1]
    dsl = yaml.safe_load((root / 'dify/chatflow-pilot.yml').read_text(encoding='utf-8'))
    nodes = {n['id']: n['data'] for n in dsl['workflow']['graph']['nodes']}
    assert not any(n['type'] == 'code' for n in nodes.values())
    normalizer = nodes['normalize']
    assert normalizer['structured_output_enabled']
    fields = normalizer['structured_output']['schema']['properties']
    assert fields['needs_clarification']['enum'] == ['yes', 'no']
    assert nodes['retrieve']['query_variable_selector'] == ['normalize', 'structured_output', 'query']
    assert nodes['route']['cases'][0]['conditions'][0]['variable_selector'][-1] in fields
    assert nodes['clarify']['answer'] == '{{#normalize.structured_output.clarification#}}'
    for edge in dsl['workflow']['graph']['edges']:
        assert edge['source'] in nodes and edge['target'] in nodes


def test_workflow_embeds_current_answer_prompt():
    root = Path(__file__).resolve().parents[1]
    dsl = yaml.safe_load((root / 'dify/chatflow-pilot.yml').read_text(encoding='utf-8'))
    grounded = next(n['data'] for n in dsl['workflow']['graph']['nodes'] if n['id'] == 'grounded')
    assert grounded['prompt_template'][0]['text'] == (root / 'prompts/answer.txt').read_text(encoding='utf-8')
