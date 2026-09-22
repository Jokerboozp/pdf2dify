import pytest

from pdf2dify.domains import classify_path


@pytest.mark.parametrize(("path", "name", "expected"), [
    ("ERP/核算模块/月结.pdf", "月结.pdf", "finance"),
    ("ERP/预算模块/预算.pdf", "预算.pdf", "funds"),
    ("ERP/物资管理/采购.pdf", "采购.pdf", "procurement"),
    ("培训/设备管理操作手册.pdf", "设备管理操作手册.pdf", "equipment"),
    ("ERP/主数据管理/物料.pdf", "物料.pdf", "master_ops"),
    ("ERP/主数据管理/公共数据管理标准/编码.pdf", "编码.pdf", "master_rules"),
    ("其他/完全未知.pdf", "完全未知.pdf", None),
])
def test_classify_path(path, name, expected):
    assert classify_path(path, name) == expected

