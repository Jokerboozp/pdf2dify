from ops_rag.common import write_json
from ops_rag.search_anchors import anchor_text


def make_item(tmp_path, text):
    path = tmp_path / 'full-export/equipment/ops-s-equipment-007.docx'
    path.parent.mkdir(parents=True)
    item = {'path': str(path), 'source_id': 's', 'source_name': '设备管理操作手册.pdf',
            'domain': 'equipment', 'chunk_ids': ['s-007'],
            'metadata': {'section_title': '设备管理主数据'}}
    write_json(tmp_path / 'corpus/s.json', {'chunks': [
        {'chunk_id': 's-007', 'title': '设备管理主数据', 'regions': [{'text': text, 'images': []}]},
        {'chunk_id': 's-010', 'title': '设备管理主数据', 'regions': [
            {'text': '设备管理主数据\n功能位置结构主数据\n创建：IL01 查询：IL03', 'images': []}]}]})
    return item


def test_generic_equipment_heading_keeps_its_actual_operation_and_codes(tmp_path):
    item = make_item(tmp_path, '设备管理主数据\n工作中心主数据\n•\n•\n创建：IR01 查询：IR03\n可复制可不复制\n13')
    result = anchor_text(item)
    assert '工作中心主数据' in result and 'IR01' in result and 'IR03' in result
    assert '功能位置' not in result and 'IL01' not in result


def test_directory_mentions_do_not_become_operation_labels(tmp_path):
    from ops_rag.search_anchors import native_operation_labels
    item = make_item(tmp_path, '目 录\n1、工作中心主数据创建、查询\n2、功能位置主数据创建、查询\n11')
    assert native_operation_labels(item) == []


def test_contents_page_bookmark_does_not_masquerade_as_operation_title():
    from ops_rag.corpus import evidence_title
    title = '1、工作中心主数据创建、查询'
    assert evidence_title(title, [{'text': '目 录\n1、工作中心主数据创建、查询\n2、功能位置主数据创建、查询'}]) == '目录'
    assert evidence_title(title, [{'text': '工作中心主数据\n创建：IR01 查询：IR03'}]) == title
    assert evidence_title(title, [{'text': '目 录\n章节'}, {'text': '创建：IR01'}]) == title
