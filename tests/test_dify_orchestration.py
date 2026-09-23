import json
import threading
from pathlib import Path

import pytest

from pdf2dify.config import SecretStore, Settings
from pdf2dify.db import Database
from pdf2dify.jobs import JobService
from pdf2dify.pipeline import JobCancelled, JobPaused, PipelineRunner


def test_sync_waits_for_anchors_and_audits_before_completion(tmp_path: Path, monkeypatch):
    settings = Settings(
        project_root=tmp_path, data_dir=tmp_path / "data", database_path=tmp_path / "data" / "test.db",
        engine_root=tmp_path / "engine", engine_python=tmp_path / "engine" / "python.exe",
    )
    settings.ensure()
    db = Database(settings.database_path)
    db.init()
    job = db.create_job(
        name="sync", source_type="upload", source_path="", mode="sync", fixed_domain="finance",
    )
    SecretStore(settings).update({
        "DIFY_BASE_URL": "http://dify.local/v1", "DIFY_DATASET_API_KEY": "test-secret",
    })
    runner = PipelineRunner(settings, db)
    workspace = settings.data_dir / "jobs" / job["id"]
    workspace.mkdir(parents=True)
    db.upsert_files(job["id"], [{
        "source_id": "new-source", "name": "manual.pdf", "relative_path": "manual.pdf",
        "path": str(tmp_path / "manual.pdf"), "pages": 1, "bytes": 100, "sha256": "new-source",
        "domain": "finance", "classification_status": "confirmed",
    }])
    for relative, document in (
        ("full-export/manifest.json", {"documents": [{"key": "one", "source_id": "new-source"}]}),
        ("process-navigation/full-export/manifest.json", {"documents": [{"key": "nav", "source_id": "new-source"}]}),
    ):
        path = workspace / "engine-data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
    stages: list[str] = []

    def fake_engine(_job_id: str, stage: str, _config: Path, _extra=None):
        stages.append(stage)
        root = workspace / "engine-data"
        if stage == "dify-setup":
            path = root / "dify" / "full-state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"documents":{}}', encoding="utf-8")
        elif stage == "nav-setup":
            path = root / "process-navigation" / "dify" / "full-state.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text('{"documents":{}}', encoding="utf-8")
        elif stage == "dify-status":
            path = root / "reports" / "full-indexing.json"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                "domains": {"finance": {"target": {
                    "pending": [], "counts": {
                        "anchor_required": 1,
                        "anchors_current": int("dify-anchor" in stages),
                    },
                }}},
            }), encoding="utf-8")
        elif stage == "nav-status":
            path = root / "reports" / "process-navigation-status.json"
            path.write_text('{"pending":[]}', encoding="utf-8")
        elif stage == "dify-anchor":
            path = root / "dify" / "search-anchors.json"
            path.write_text('{"documents":{"one":{}}}', encoding="utf-8")

    monkeypatch.setattr(runner, "_run_engine", fake_engine)
    runner._sync_dify(job["id"], workspace / "config.yaml", workspace)

    assert stages.index("dify-anchor") < stages.index("dify-audit")
    assert stages[-2:] == ["dify-audit", "nav-audit"]
    shared = runner._sync_state_dir("http://dify.local/v1")
    assert (shared / "full-state.json").is_file()
    assert (shared / "search-anchors.json").is_file()
    next_workspace = settings.data_dir / "jobs" / "next"
    runner._load_sync_receipts(next_workspace, shared)
    assert (next_workspace / "engine-data" / "dify" / "search-anchors.json").is_file()


def test_dify_url_normalized_and_older_source_keys_retired(tmp_path: Path):
    settings = Settings(
        project_root=tmp_path, data_dir=tmp_path / "data", database_path=tmp_path / "data" / "test.db",
        engine_root=tmp_path / "engine", engine_python=tmp_path / "engine" / "python.exe",
    )
    settings.ensure()
    secrets = SecretStore(settings)
    secrets.update({"DIFY_BASE_URL": "http://dify.local/v1/"})
    assert secrets.read()["DIFY_BASE_URL"] == "http://dify.local/v1"
    secrets.update({"PDF2DIFY_DATASET_IDS": "broken-json"})
    assert secrets.public()["dataset_ids"] == {}

    db = Database(settings.database_path)
    db.init()
    job = db.create_job(
        name="updated", source_type="upload", source_path="", mode="sync", fixed_domain="finance",
    )
    db.upsert_files(job["id"], [{
        "source_id": "new-source", "name": "manual.pdf", "relative_path": "manual.pdf",
        "path": str(tmp_path / "manual.pdf"), "pages": 1, "bytes": 100,
        "sha256": "new-source", "domain": "finance", "classification_status": "confirmed",
    }])
    runner = PipelineRunner(settings, db)
    workspace = settings.data_dir / "jobs" / job["id"]
    for relative, document in (
        ("full-export/manifest.json", {"documents": [{"key": "new", "source_id": "new-source"}]}),
        ("process-navigation/full-export/manifest.json", {"documents": [{"key": "new-nav", "source_id": "new-source"}]}),
    ):
        path = workspace / "engine-data" / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(document), encoding="utf-8")
    state_dir = runner._sync_state_dir("http://dify.local/v1")
    identity = "upload:updated:manual.pdf"
    (state_dir / "source-index.json").write_text(json.dumps({
        identity: {"source_id": "old-source", "documents": ["old", "retained"],
                   "navigation": ["old-nav"]},
    }), encoding="utf-8")
    plan, index = runner._replacement_plan(job["id"], workspace, state_dir)
    assert plan == {"documents": ["old", "retained"], "navigation": ["old-nav"]}
    assert index[identity]["documents"] == ["new"]


@pytest.mark.parametrize("action, expected", [("cancel", JobCancelled), ("request_pause", JobPaused)])
def test_control_interrupts_index_poll_wait(tmp_path: Path, monkeypatch, action, expected):
    settings = Settings(
        project_root=tmp_path, data_dir=tmp_path / "data", database_path=tmp_path / "data" / "test.db",
        engine_root=tmp_path / "engine", engine_python=tmp_path / "engine" / "python.exe",
    )
    settings.ensure()
    db = Database(settings.database_path)
    db.init()
    job = db.create_job(name="索引等待", source_type="upload", source_path="", mode="sync", fixed_domain="finance")
    db.claim_next_job()
    SecretStore(settings).update({"DIFY_BASE_URL": "http://dify.local/v1", "DIFY_DATASET_API_KEY": "test-secret"})
    runner = PipelineRunner(settings, db)
    workspace = settings.data_dir / "jobs" / job["id"]
    status_written = threading.Event()
    wake = threading.Event()

    def fake_engine(_job_id: str, stage: str, _config: Path, _extra=None):
        root = workspace / "engine-data" / "reports"
        root.mkdir(parents=True, exist_ok=True)
        if stage == "dify-status":
            (root / "full-indexing.json").write_text(json.dumps({
                "domains": {"finance": {"target": {
                    "pending": [{"status": "indexing"}],
                    "counts": {"anchor_required": 0, "anchors_current": 0},
                }}},
            }), encoding="utf-8")
        elif stage == "nav-status":
            (root / "process-navigation-status.json").write_text(
                '{"pending":[{"status":"indexing"}]}', encoding="utf-8",
            )
            status_written.set()

    monkeypatch.setattr(runner, "_run_engine", fake_engine)
    monkeypatch.setattr("pdf2dify.pipeline.time.sleep", lambda seconds: wake.wait(seconds))
    result = []

    def invoke():
        try:
            runner._sync_dify(job["id"], workspace / "config.yaml", workspace)
        except Exception as exc:
            result.append(type(exc))

    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        assert status_written.wait(2)
        getattr(JobService(settings, db), action)(job["id"])
        thread.join(timeout=1.5)
        responsive = not thread.is_alive()
    finally:
        wake.set()
        thread.join(timeout=2)
    assert responsive, "索引轮询的 30 秒休眠没有及时响应任务控制"
    assert result == [expected]
