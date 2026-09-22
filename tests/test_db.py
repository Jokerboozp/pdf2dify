from pathlib import Path

from pdf2dify.db import Database


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

