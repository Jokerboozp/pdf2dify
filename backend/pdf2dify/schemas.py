from __future__ import annotations

from typing import Literal
from pydantic import BaseModel, Field


class PathJobCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    source_path: str = Field(min_length=1)
    mode: Literal["export", "sync"] = "export"
    fixed_domain: str | None = None


class FileDomainUpdate(BaseModel):
    domain: str


class CategoryUpsert(BaseModel):
    name: str = Field(min_length=1, max_length=50)


class DifySettingsUpdate(BaseModel):
    dify_base_url: str | None = None
    dify_api_key: str | None = None
    embedding_provider: str | None = None
    embedding_model: str | None = None
    dataset_prefix: str | None = None
    dataset_ids: dict[str, str] | None = None
