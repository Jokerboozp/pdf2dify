import subprocess
import sys
import threading
from pathlib import Path

from pdf2dify.config import Settings
from pdf2dify.db import Database
from pdf2dify.jobs import JobService
from pdf2dify.pipeline import JobCancelled, PipelineRunner


def test_cancel_silent_engine_returns_promptly(tmp_path: Path, monkeypatch):
    engine = tmp_path / "engine"
    (engine / "src" / "ops_rag").mkdir(parents=True)
    db = Database(tmp_path / "test.db")
    db.init()
    job = db.create_job(name="静默引擎", source_type="path_directory", source_path=str(tmp_path), mode="export", fixed_domain=None)
    db.claim_next_job()
    settings = Settings(tmp_path, tmp_path, db.path, engine, Path(sys.executable))
    runner = PipelineRunner(settings, db)
    started = threading.Event()
    processes = []
    original_popen = subprocess.Popen

    def silent_popen(*_args, **kwargs):
        process = original_popen([sys.executable, "-c", "import time; time.sleep(10)"], **kwargs)
        processes.append(process)
        started.set()
        return process

    monkeypatch.setattr("pdf2dify.pipeline.subprocess.Popen", silent_popen)
    result = []

    def invoke():
        try:
            runner._run_engine(job["id"], "scan", tmp_path / "config.json")
        except JobCancelled:
            result.append("cancelled")
        except Exception as exc:
            result.append(type(exc).__name__)

    thread = threading.Thread(target=invoke)
    thread.start()
    try:
        assert started.wait(2)
        JobService(settings, db).cancel(job["id"])
        thread.join(timeout=0.75)
        assert not thread.is_alive(), "静默引擎没有及时响应取消"
        assert result == ["cancelled"]
    finally:
        for process in processes:
            if process.poll() is None:
                process.terminate()
        thread.join(timeout=2)


def test_engine_output_is_recorded_before_exit(tmp_path: Path, monkeypatch):
    engine = tmp_path / "engine"
    (engine / "src" / "ops_rag").mkdir(parents=True)
    db = Database(tmp_path / "test.db")
    db.init()
    job = db.create_job(name="输出日志", source_type="path_directory", source_path=str(tmp_path), mode="export", fixed_domain=None)
    settings = Settings(tmp_path, tmp_path, db.path, engine, Path(sys.executable))
    original_popen = subprocess.Popen

    def output_popen(*_args, **kwargs):
        return original_popen(
            [sys.executable, "-c", "print('first'); print('last')"], **kwargs,
        )

    monkeypatch.setattr("pdf2dify.pipeline.subprocess.Popen", output_popen)
    PipelineRunner(settings, db)._run_engine(job["id"], "scan", tmp_path / "config.json")
    lines = [event["message"] for event in db.list_events(job["id"]) if event["level"] == "engine"]
    assert lines == ["first", "last"]
