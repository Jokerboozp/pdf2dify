from pathlib import Path

from pdf2dify.db import Database
from pdf2dify.jobs import JobService
from pdf2dify.config import Settings


def test_job_lifecycle_and_atomic_claim(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.init()
    job = db.create_job(name="测试", source_type="path_directory", source_path=str(tmp_path), mode="export", fixed_domain=None)
    assert job["status"] == "queued"
    claimed = db.claim_next_job()
    assert claimed and claimed["id"] == job["id"]
    assert claimed["status"] == "running"
    assert db.claim_next_job() is None
    db.update_job(job["id"], status="completed", progress=100)
    assert db.get_job(job["id"])["progress"] == 100


def test_file_classification_persists_across_rescan(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.init()
    job = db.create_job(name="测试", source_type="upload", source_path="", mode="export", fixed_domain=None)
    item = {"source_id": "abc", "name": "unknown.pdf", "relative_path": "unknown.pdf",
            "path": str(tmp_path / "unknown.pdf"), "pages": 2, "bytes": 10, "sha256": "abc",
            "domain": None, "classification_status": "needs_review"}
    db.upsert_files(job["id"], [item])
    file = db.list_files(job["id"])[0]
    db.set_file_domain(job["id"], file["id"], "finance")
    db.upsert_files(job["id"], [item])
    saved = db.list_files(job["id"])[0]
    assert saved["domain"] == "finance"
    assert saved["classification_status"] == "confirmed"


def test_interrupted_running_job_is_requeued(tmp_path: Path):
    db = Database(tmp_path / "test.db")
    db.init()
    job = db.create_job(name="恢复", source_type="path_directory", source_path=str(tmp_path), mode="export", fixed_domain=None)
    claimed = db.claim_next_job()
    assert claimed and claimed["status"] == "running"
    assert db.recover_interrupted_jobs() == [job["id"]]
    assert db.get_job(job["id"])["status"] == "queued"
    assert "自动重新排队" in db.list_events(job["id"])[-1]["message"]


def test_worker_cannot_claim_upload_until_copy_finishes(tmp_path: Path):
    class InspectingStream:
        def __init__(self, database):
            self.database = database
            self.called = False

        def read(self, _size=-1):
            if not self.called:
                self.called = True
                assert self.database.claim_next_job() is None
                return b"%PDF-test"
            return b""

    db = Database(tmp_path / "data" / "test.db")
    db.init()
    settings = Settings(
        project_root=tmp_path, data_dir=tmp_path / "data", database_path=db.path,
        engine_root=tmp_path / "engine", engine_python=tmp_path / "engine" / "python.exe",
    )
    job = JobService(settings, db).create_upload_job(
        name="上传", mode="export", fixed_domain="finance",
        files=[("nested/manual.pdf", InspectingStream(db))],
    )
    assert job["status"] == "queued"
    assert (settings.data_dir / "uploads" / job["id"] / "nested" / "manual.pdf").read_bytes() == b"%PDF-test"
    assert db.claim_next_job()["id"] == job["id"]
