from __future__ import annotations

import json
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterator


def utcnow() -> str:
    return datetime.now(timezone.utc).isoformat()


SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS jobs (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    source_type TEXT NOT NULL,
    source_path TEXT NOT NULL,
    mode TEXT NOT NULL DEFAULT 'export',
    fixed_domain TEXT,
    status TEXT NOT NULL DEFAULT 'queued',
    stage TEXT NOT NULL DEFAULT 'queued',
    progress REAL NOT NULL DEFAULT 0,
    message TEXT NOT NULL DEFAULT '',
    total_files INTEGER NOT NULL DEFAULT 0,
    total_pages INTEGER NOT NULL DEFAULT 0,
    processed_files INTEGER NOT NULL DEFAULT 0,
    processed_pages INTEGER NOT NULL DEFAULT 0,
    output_dir TEXT,
    error TEXT,
    cancel_requested INTEGER NOT NULL DEFAULT 0,
    pause_requested INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    started_at TEXT,
    finished_at TEXT
);

CREATE TABLE IF NOT EXISTS job_files (
    id TEXT PRIMARY KEY,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    source_id TEXT NOT NULL,
    name TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    absolute_path TEXT NOT NULL,
    pages INTEGER NOT NULL DEFAULT 0,
    bytes INTEGER NOT NULL DEFAULT 0,
    sha256 TEXT NOT NULL DEFAULT '',
    domain TEXT,
    classification_status TEXT NOT NULL DEFAULT 'pending',
    processing_status TEXT NOT NULL DEFAULT 'pending',
    error TEXT,
    UNIQUE(job_id, source_id)
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    job_id TEXT NOT NULL REFERENCES jobs(id) ON DELETE CASCADE,
    level TEXT NOT NULL,
    message TEXT NOT NULL,
    data_json TEXT,
    created_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_jobs_status ON jobs(status, created_at);
CREATE INDEX IF NOT EXISTS idx_events_job_id ON events(job_id, id);
CREATE INDEX IF NOT EXISTS idx_job_files_job_id ON job_files(job_id, relative_path);
"""


class Database:
    def __init__(self, path: Path):
        self.path = path

    def init(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as conn:
            conn.executescript(SCHEMA)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path, timeout=30, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys=ON")
        conn.execute("PRAGMA busy_timeout=30000")
        try:
            yield conn
        finally:
            conn.close()

    def create_job(self, *, name: str, source_type: str, source_path: str,
                   mode: str, fixed_domain: str | None,
                   status: str = "queued") -> dict[str, Any]:
        job_id = uuid.uuid4().hex
        stamp = utcnow()
        with self.connect() as conn:
            conn.execute(
                """INSERT INTO jobs
                (id,name,source_type,source_path,mode,fixed_domain,status,stage,created_at,updated_at)
                VALUES (?,?,?,?,?,?,?,'queued',?,?)""",
                (job_id, name, source_type, source_path, mode, fixed_domain, status, stamp, stamp),
            )
        self.add_event(job_id, "info", "任务已创建")
        return self.get_job(job_id)

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self.connect() as conn:
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
        if not row:
            raise KeyError(job_id)
        return dict(row)

    def list_jobs(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?", (limit,)
            ).fetchall()
        return [dict(row) for row in rows]

    def update_job(self, job_id: str, **fields: Any) -> dict[str, Any]:
        if not fields:
            return self.get_job(job_id)
        allowed = {
            "status", "stage", "progress", "message", "total_files", "total_pages",
            "processed_files", "processed_pages", "output_dir", "error",
            "cancel_requested", "pause_requested", "started_at", "finished_at",
        }
        unknown = set(fields) - allowed
        if unknown:
            raise ValueError(f"Unknown job fields: {sorted(unknown)}")
        fields["updated_at"] = utcnow()
        columns = ", ".join(f"{key}=?" for key in fields)
        values = list(fields.values()) + [job_id]
        with self.connect() as conn:
            cursor = conn.execute(f"UPDATE jobs SET {columns} WHERE id=?", values)
            if cursor.rowcount != 1:
                raise KeyError(job_id)
        return self.get_job(job_id)

    def request_control(self, job_id: str, action: str) -> dict[str, Any]:
        """Apply a pause or cancel request atomically against worker claims."""
        if action not in {"pause", "cancel"}:
            raise ValueError(action)
        stamp = utcnow()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            status = row["status"]
            if status in {"completed", "failed", "cancelled"}:
                conn.execute("COMMIT")
                return dict(row)
            if action == "pause":
                if status in {"queued", "needs_review"}:
                    fields = ("status='paused', message='任务已暂停', pause_requested=0", [])
                else:
                    fields = ("pause_requested=1", [])
            elif status in {"queued", "paused", "needs_review"}:
                fields = ("status='cancelled', message='任务已取消', finished_at=?, cancel_requested=0", [stamp])
            else:
                fields = ("cancel_requested=1", [])
            assignments, values = fields
            conn.execute(
                f"UPDATE jobs SET {assignments}, updated_at=? WHERE id=?",
                [*values, stamp, job_id],
            )
            result = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            conn.execute("COMMIT")
            return result

    def complete_preparing(self, job_id: str) -> dict[str, Any]:
        """Publish a copied upload without losing a pause or cancel request."""
        stamp = utcnow()
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone()
            if row is None:
                raise KeyError(job_id)
            if row["status"] != "preparing":
                raise ValueError(f"任务不能完成准备阶段：{row['status']}")
            if row["cancel_requested"]:
                status, message, finished_at = "cancelled", "任务已取消", stamp
            elif row["pause_requested"]:
                status, message, finished_at = "paused", "任务已暂停", None
            else:
                status, message, finished_at = "queued", "等待处理", None
            conn.execute(
                """UPDATE jobs SET status=?, message=?, finished_at=?,
                cancel_requested=0, pause_requested=0, updated_at=? WHERE id=?""",
                (status, message, finished_at, stamp, job_id),
            )
            result = dict(conn.execute("SELECT * FROM jobs WHERE id=?", (job_id,)).fetchone())
            conn.execute("COMMIT")
            return result

    def claim_next_job(self) -> dict[str, Any] | None:
        with self.connect() as conn:
            conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """SELECT * FROM jobs
                WHERE status='queued' AND cancel_requested=0 AND pause_requested=0
                ORDER BY created_at LIMIT 1"""
            ).fetchone()
            if not row:
                conn.execute("COMMIT")
                return None
            stamp = utcnow()
            updated = conn.execute(
                """UPDATE jobs SET status='running', started_at=COALESCE(started_at,?),
                updated_at=? WHERE id=? AND status='queued'""",
                (stamp, stamp, row["id"]),
            )
            conn.execute("COMMIT")
            return self.get_job(row["id"]) if updated.rowcount == 1 else None

    def recover_interrupted_jobs(self) -> list[str]:
        """Return jobs owned by a previous worker process to the durable queue."""
        with self.connect() as conn:
            rows = conn.execute("SELECT id FROM jobs WHERE status='running'").fetchall()
            job_ids = [row["id"] for row in rows]
            if job_ids:
                conn.execute(
                    """UPDATE jobs SET status='queued', message='Worker 中断，等待断点续跑',
                    updated_at=? WHERE status='running'""", (utcnow(),)
                )
        for job_id in job_ids:
            self.add_event(job_id, "warning", "检测到上次 Worker 中断，任务已自动重新排队")
        return job_ids

    def add_event(self, job_id: str, level: str, message: str,
                  data: dict[str, Any] | None = None) -> int:
        with self.connect() as conn:
            cursor = conn.execute(
                "INSERT INTO events(job_id,level,message,data_json,created_at) VALUES(?,?,?,?,?)",
                (job_id, level, message,
                 json.dumps(data, ensure_ascii=False) if data is not None else None, utcnow()),
            )
            return int(cursor.lastrowid)

    def list_events(self, job_id: str, after: int = 0, limit: int = 500) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM events WHERE job_id=? AND id>? ORDER BY id LIMIT ?",
                (job_id, after, limit),
            ).fetchall()
        result = []
        for row in rows:
            item = dict(row)
            item["data"] = json.loads(item.pop("data_json")) if item.get("data_json") else None
            result.append(item)
        return result

    def upsert_files(self, job_id: str, files: list[dict[str, Any]]) -> None:
        with self.connect() as conn:
            conn.execute("BEGIN")
            for item in files:
                conn.execute(
                    """INSERT INTO job_files
                    (id,job_id,source_id,name,relative_path,absolute_path,pages,bytes,sha256,
                     domain,classification_status,processing_status,error)
                    VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(job_id,source_id) DO UPDATE SET
                      name=excluded.name, relative_path=excluded.relative_path,
                      absolute_path=excluded.absolute_path, pages=excluded.pages,
                      bytes=excluded.bytes, sha256=excluded.sha256,
                      domain=COALESCE(job_files.domain, excluded.domain),
                      classification_status=CASE WHEN job_files.domain IS NOT NULL
                        THEN 'confirmed' ELSE excluded.classification_status END,
                      error=excluded.error""",
                    (
                        uuid.uuid4().hex, job_id, item["source_id"], item["name"],
                        item["relative_path"], item["path"], item.get("pages", 0),
                        item.get("bytes", 0), item.get("sha256", ""), item.get("domain"),
                        item.get("classification_status", "pending"), "pending", item.get("error"),
                    ),
                )
            conn.execute("COMMIT")

    def list_files(self, job_id: str) -> list[dict[str, Any]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM job_files WHERE job_id=? ORDER BY relative_path", (job_id,)
            ).fetchall()
        return [dict(row) for row in rows]

    def set_file_domain(self, job_id: str, file_id: str, domain: str) -> dict[str, Any]:
        with self.connect() as conn:
            cursor = conn.execute(
                """UPDATE job_files SET domain=?, classification_status='confirmed'
                WHERE id=? AND job_id=?""", (domain, file_id, job_id)
            )
            if cursor.rowcount != 1:
                raise KeyError(file_id)
            row = conn.execute("SELECT * FROM job_files WHERE id=?", (file_id,)).fetchone()
        return dict(row)

    def set_all_file_status(self, job_id: str, status: str) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE job_files SET processing_status=? WHERE job_id=?", (status, job_id)
            )
