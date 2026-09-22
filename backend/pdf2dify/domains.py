from __future__ import annotations

from pathlib import PurePosixPath


DOMAINS = {
    "finance": "财务核算",
    "funds": "资金与预算",
    "procurement": "采购与物资",
    "projects": "项目管理",
    "internal": "内部交易",
    "oilgas": "油气业务",
    "equipment": "设备管理",
    "master_ops": "主数据操作",
    "master_rules": "主数据标准",
}


def classify_path(relative_path: str, name: str) -> str | None:
    path = "/" + PurePosixPath(relative_path.replace("\\", "/")).as_posix().lstrip("/")
    if "公共数据管理标准/" in path:
        return "master_rules"
    if "/主数据管理/" in path:
        return "master_ops"
    if "/核算模块/" in path or name == "财务模块常见问题.pdf":
        return "finance"
    if "/资金模块/" in path or "/预算模块/" in path:
        return "funds"
    if "/内部交易模块/" in path:
        return "internal"
    if "/油气销售/" in path or "/油气委托加工/" in path:
        return "oilgas"
    if "/物资管理/" in path or "物资采购培训" in name:
        return "procurement"
    if "设备管理" in path or "设备管理" in name:
        return "equipment"
    if any(token in path for token in ("投资项目", "其他费用项目", "数信项目", "科技项目", "费用项目操作")):
        return "projects"
    return None

