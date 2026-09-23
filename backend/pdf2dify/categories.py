from __future__ import annotations

import json
import os
import uuid
import unicodedata
from pathlib import Path

from filelock import FileLock

from .domains import DOMAINS


class CategoryStore:
    """Persistent additive catalog; stable IDs keep old jobs and receipts readable."""

    def __init__(self, data_dir: Path):
        self.path = data_dir / "categories.json"
        self.lock = FileLock(str(data_dir / "categories.lock"))

    def _custom(self) -> dict[str, str]:
        if not self.path.exists():
            return {}
        value = json.loads(self.path.read_text(encoding="utf-8"))
        if not isinstance(value, dict):
            raise ValueError("分类配置格式无效")
        return {str(key): str(name) for key, name in value.items()}

    def mapping(self) -> dict[str, str]:
        return {**DOMAINS, **self._custom()}

    def list(self) -> list[dict[str, str | bool]]:
        return [
            {"id": key, "name": name, "custom": key not in DOMAINS}
            for key, name in self.mapping().items()
        ]

    @staticmethod
    def _validate_name(name: str, mapping: dict[str, str], except_id: str | None = None) -> str:
        name = name.strip()
        if (not name or len(name) > 50 or name.rstrip(".") != name
                or any(char in name for char in '/\\<>:"|?*')
                or any(unicodedata.category(char).startswith("C") for char in name)):
            raise ValueError("分类名称须为 1–50 字，且不能包含路径特殊字符")
        reserved = {"CON", "PRN", "AUX", "NUL"} | {f"COM{i}" for i in range(1, 10)} | {f"LPT{i}" for i in range(1, 10)}
        if name.split(".", 1)[0].upper() in reserved:
            raise ValueError("分类名称不能使用系统保留名称")
        if name == "资料导航":
            raise ValueError("资料导航为保留分类")
        if any(key != except_id and value.casefold() == name.casefold() for key, value in mapping.items()):
            raise ValueError("分类名称已存在")
        return name

    def _write(self, value: dict[str, str]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temp = self.path.with_suffix(".tmp")
        temp.write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(temp, self.path)

    def create(self, name: str) -> dict[str, str | bool]:
        with self.lock:
            custom = self._custom()
            name = self._validate_name(name, {**DOMAINS, **custom})
            category_id = "custom_" + uuid.uuid4().hex[:12]
            custom[category_id] = name
            self._write(custom)
        return {"id": category_id, "name": name, "custom": True}

    def rename(self, category_id: str, name: str) -> dict[str, str | bool]:
        with self.lock:
            custom = self._custom()
            if category_id not in custom:
                raise KeyError(category_id)
            name = self._validate_name(name, {**DOMAINS, **custom}, category_id)
            custom[category_id] = name
            self._write(custom)
        return {"id": category_id, "name": name, "custom": True}
