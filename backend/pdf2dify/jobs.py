from __future__ import annotations

import shutil
from pathlib import Path
from typing import BinaryIO

from .config import Settings
from .db import Database
from .domains import DOMAINS


TERMINAL_STATUSES = {"completed", "failed", "cancelled"}


class JobService:
    def __init__(self, settings: Settings, db: Database):
        self.settings = settings
        self.db = db

    def create_path_job(self, *, name: str, source_path: str, mode: str,
                        fixed_domain: str | None) -> dict:
        path = Path(source_path).expanduser().resolve()
        if not path.exists():
            raise ValueError(f"路径不存在：{path}")
        if path.is_file() and path.suffix.lower() != ".pdf":
            raise ValueError("指定文件必须是 PDF")
        if path.is_dir() and not any(p.is_file() and p.suffix.lower() == ".pdf" for p in path.rglob("*")):
            raise ValueError("目录中没有找到 PDF")
        if fixed_domain and fixed_domain not in DOMAINS:
            raise ValueError("未知业务分类")
        if path.is_file():
            job = self.db.create_job(
                name=name, source_type="path_file", source_path=str(path),
                mode=mode, fixed_domain=fixed_domain,
            )
            target = self.settings.data_dir / "uploads" / job["id"]
            target.mkdir(parents=True, exist_ok=True)
            copied = target / path.name
            shutil.copy2(path, copied)
            return self.db.update_job(job["id"], message="文件已复制到任务工作区") | {"source_path": str(copied)}
        return self.db.create_job(
            name=name, source_type="path_directory", source_path=str(path),
            mode=mode, fixed_domain=fixed_domain,
        )

    def create_upload_job(self, *, name: str, mode: str, fixed_domain: str | None,
                          files: list[tuple[str, BinaryIO]]) -> dict:
        if not files:
            raise ValueError("至少上传一个 PDF")
        if fixed_domain and fixed_domain not in DOMAINS:
            raise ValueError("未知业务分类")
        normalized_files: list[tuple[Path, BinaryIO]] = []
        for raw_name, stream in files:
            normalized = raw_name.replace("\\", "/").lstrip("/")
            relative = Path(normalized)
            if relative.suffix.lower() != ".pdf" or ".." in relative.parts or relative.is_absolute():
                raise ValueError(f"不支持的上传文件：{raw_name}")
            normalized_files.append((relative, stream))
        job = self.db.create_job(
            name=name, source_type="upload", source_path="",
            mode=mode, fixed_domain=fixed_domain,
        )
        root = self.settings.data_dir / "uploads" / job["id"]
        root.mkdir(parents=True, exist_ok=True)
        for relative, stream in normalized_files:
            target = (root / relative).resolve()
            if not target.is_relative_to(root.resolve()):
                raise ValueError(f"非法文件路径：{relative}")
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("wb") as output:
                shutil.copyfileobj(stream, output)
        return self.db.update_job(job["id"], message=f"已接收 {len(files)} 个 PDF", output_dir=str(root))

    def source_root(self, job: dict) -> Path:
        if job["source_type"] == "path_file":
            return self.settings.data_dir / "uploads" / job["id"]
        if job["source_type"] == "upload":
            return self.settings.data_dir / "uploads" / job["id"]
        return Path(job["source_path"])

    def request_pause(self, job_id: str) -> dict:
        job = self.db.get_job(job_id)
        if job["status"] in TERMINAL_STATUSES:
            return job
        self.db.add_event(job_id, "info", "已请求暂停，当前阶段结束后生效")
        return self.db.update_job(job_id, pause_requested=1)

    def resume(self, job_id: str) -> dict:
        job = self.db.get_job(job_id)
        if job["status"] not in {"paused", "needs_review", "failed"}:
            raise ValueError("当前状态不能继续")
        if job["status"] == "needs_review":
            unresolved = [item for item in self.db.list_files(job_id) if not item.get("domain")]
            if unresolved:
                raise ValueError(f"仍有 {len(unresolved)} 个文件未分类")
        self.db.add_event(job_id, "info", "任务已重新进入队列")
        return self.db.update_job(
            job_id, status="queued", pause_requested=0, cancel_requested=0,
            error=None, finished_at=None,
        )

    def cancel(self, job_id: str) -> dict:
        job = self.db.get_job(job_id)
        if job["status"] in TERMINAL_STATUSES:
            return job
        self.db.add_event(job_id, "warning", "已请求取消")
        return self.db.update_job(job_id, cancel_requested=1)
