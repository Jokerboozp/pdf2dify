from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


Domain = Literal[
    "finance", "funds", "procurement", "projects", "internal", "oilgas",
    "equipment", "master_ops", "master_rules",
]


class PathJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_path: str = Field(min_length=1)
    mode: Literal["export", "sync"] = "export"
    fixed_domain: Domain | None = None


class FileDomainUpdate(BaseModel):
    domain: Domain


class DifySettingsUpdate(BaseModel):
    dify_base_url: str | None = None
    dify_api_key: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None

