from ops_rag.cards import faq_fields, validate_card
from ops_rag.common import parse_pages
from ops_rag.pipeline import clean_lines, normalize_box
from ops_rag.retrieval import rank_cards
from ops_rag.dify import DifyClient, document_payload, SEPARATOR
import pytest
import httpx


def test_labels_in_reverse_pdf_order_preserve_negative_condition():
    text='核算常见问题\n解决办法：选择01不输入过账日期；选择02必须输入。 问题描述：凭证冲销'
    assert faq_fields(text) == {'解决办法':'选择01不输入过账日期；选择02必须输入。','问题描述':'凭证冲销'}


def test_cleaner_keeps_business_numbers_and_step_headings():
    clean, removed = clean_lines('大集中 ERP 项目\n第 10 页 共 152 页\n步骤 4：\n选择 C700，不能选择2100\n01 不填写过账日期')
    assert '步骤 4：' in clean and '不能选择2100' in clean and '01 不填写' in clean
    assert len(removed) == 2
    assert clean_lines('2100\n01')[0] == '2100\n01'


def test_pages_are_one_based_and_out_of_bounds_rejected():
    assert parse_pages('3-5,5,8',10) == [3,4,5,8]
    for bad in ['0','8-11','9-2']:
        with pytest.raises(ValueError): parse_pages(bad,10)


def test_outside_image_box_is_clamped():
    assert normalize_box({'x0':-1,'top':2,'x1':101,'bottom':210},100,200) == [0,2,100,200]


def test_invented_transaction_cannot_pass_card_validation():
    c={'question':'如何修改','answer':'使用FB08','sources':[{'evidence_text':'问题描述：如何修改\n解决办法：使用FB02'}]}
    assert 'answer_not_extractively_grounded' in validate_card(c)


def test_source_code_is_not_autocorrected():
    fields=faq_fields('问题描述：ZP0FIADG001C报错\n解决办法：查找ZP0FIADG0001')
    assert 'ZP0FIADG001C' in fields['问题描述']


def test_bm25_distinguishes_different_transactions():
    cards=[{'card_id':'a','title':'a','question':'项目结转如何取消','answer':'使用CJ88','sources':[]},
           {'card_id':'b','title':'b','question':'维修工单结转如何取消','answer':'使用KO8G','sources':[]}]
    assert rank_cards(cards,'KO8G取消结转')[0]['card_id']=='b'


def test_dify_lists_all_pages():
    def handler(request):
        page=int(request.url.params['page'])
        return httpx.Response(200,json={'data':[{'id':str(page),'name':str(page)}],'has_more':page<2})
    client=DifyClient('http://example.invalid/v1','test',httpx.MockTransport(handler))
    assert len(client.documents('sample'))==2


def test_api_errors_do_not_echo_credentials_or_private_body():
    client=DifyClient('http://example.invalid/v1','secret-test',httpx.MockTransport(lambda r:httpx.Response(401,json={'key':'secret-test'})))
    with pytest.raises(RuntimeError) as err: client.call('GET','datasets')
    assert 'secret-test' not in str(err.value)


def test_card_payload_never_strips_links_or_uses_character_line_breaks():
    p=document_payload({'card_id':'a'},'原因01不填写日期')
    assert p['process_rule']['rules']['segmentation']['separator']==SEPARATOR
    assert not p['process_rule']['rules']['pre_processing_rules'][1]['enabled']
