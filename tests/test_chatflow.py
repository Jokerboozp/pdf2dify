import json
from pathlib import Path

import pytest
import yaml

from pdf2dify.config import PROJECT_ROOT, SecretStore, Settings
from pdf2dify.db import Database
from pdf2dify.pipeline import PipelineRunner

ENGINE = PROJECT_ROOT / "engine" / "ops-pdf-rag"
ENGINE_PYTHON = ENGINE / ".venv" / "Scripts" / "python.exe"
if not ENGINE_PYTHON.exists():
    ENGINE_PYTHON = ENGINE / ".venv" / "bin" / "python"


def write(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")


def make_runner(tmp_path: Path) -> tuple[PipelineRunner, Database]:
    settings = Settings(
        project_root=tmp_path, data_dir=tmp_path / "data", database_path=tmp_path / "data" / "test.db",
        engine_root=ENGINE, engine_python=ENGINE_PYTHON,
    )
    settings.ensure()
    db = Database(settings.database_path)
    db.init()
    return PipelineRunner(settings, db), db


@pytest.mark.skipif(not ENGINE_PYTHON.exists(), reason="engine environment not installed")
def test_chatflow_only_covers_datasets_synced_by_the_job(tmp_path: Path):
    runner, db = make_runner(tmp_path)
    SecretStore(runner.settings).update({"DIFY_EMBEDDING_PROVIDER": "local/embed", "DIFY_EMBEDDING_MODEL": "bge-m3"})
    custom = runner.categories.create("科技分类")["id"]
    job = db.create_job(name="科技", source_type="upload", source_path="", mode="sync", fixed_domain=None)
    db.update_job(job["id"], status="completed")
    workspace = runner.settings.data_dir / "jobs" / job["id"]
    root = workspace / "engine-data"
    write(workspace / "config.yaml", {"data_dir": "engine-data"})
    write(root / "full-export/manifest.json", {"documents": [{
        "key": "new-1", "domain": custom, "source_id": "new", "source_name": "new.pdf",
        "path": str(root / "full-export" / custom / "ops-new-1.docx"), "metadata": {"section_title": "操作步骤"},
    }]})
    write(root / "process-navigation/catalog.json", {"records": [{
        "key": "new", "source_id": "new", "domains": [custom], "filename_topic": "new", "aliases": ["new"], "outline": [],
    }]})
    # Shared receipts also list datasets that earlier jobs filled.
    write(root / "dify/full-state.json", {"datasets": {
        "finance": {"id": "finance-id", "name": "pdf2dify-财务核算"},
        custom: {"id": "custom-id", "name": "pdf2dify-科技分类"},
    }})
    write(root / "process-navigation/dify/full-state.json", {"datasets": {"process_navigation": {"id": "nav-id"}}})

    dsl = yaml.safe_load(runner.build_chatflow(job["id"]).read_text(encoding="utf-8"))

    nodes = {n["id"]: n["data"] for n in dsl["workflow"]["graph"]["nodes"]}
    assert dsl["app"]["name"] == "科技知识助手"
    assert nodes["normalize"]["structured_output"]["schema"]["properties"]["route"]["enum"] == [custom, "clarify"]
    assert nodes["retrieve_" + custom]["dataset_ids"] == ["custom-id"]
    assert "retrieve_finance" not in nodes
    assert nodes["retrieve_process"]["dataset_ids"] == ["nav-id"]
    assert nodes["select_process"]["structured_output"]["schema"]["properties"]["process_key"]["enum"] == ["", "new"]
    assert nodes["retrieve_" + custom]["multiple_retrieval_config"]["weights"]["vector_setting"]["embedding_model_name"] == "bge-m3"


def test_chatflow_requires_completed_sync_job(tmp_path: Path):
    runner, db = make_runner(tmp_path)
    job = db.create_job(name="export", source_type="upload", source_path="", mode="export", fixed_domain=None)
    db.update_job(job["id"], status="completed")
    with pytest.raises(ValueError):
        runner.build_chatflow(job["id"])
