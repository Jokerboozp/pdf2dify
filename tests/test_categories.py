import json
from pathlib import Path

from fastapi.testclient import TestClient

from pdf2dify.categories import CategoryStore
from pdf2dify.config import Settings
from pdf2dify.db import Database
from pdf2dify.jobs import JobService
from pdf2dify.pipeline import PipelineRunner


def test_custom_category_persists_and_validates(tmp_path: Path):
    catalog = CategoryStore(tmp_path)
    created = catalog.create("供应链合规")
    assert created["id"].startswith("custom_")
    assert CategoryStore(tmp_path).mapping()[created["id"]] == "供应链合规"
    assert catalog.rename(created["id"], "生产安全")["name"] == "生产安全"
    assert catalog.mapping()[created["id"]] == "生产安全"
    try:
        catalog.create("财务核算")
        assert False, "duplicate name must be rejected"
    except ValueError:
        pass
    try:
        catalog.create("unsafe/path")
        assert False, "path separators must be rejected"
    except ValueError:
        pass


def test_custom_category_api_and_export(tmp_path: Path, monkeypatch):
    data = tmp_path / "data"
    monkeypatch.setenv("PDF2DIFY_DATA_DIR", str(data))
    monkeypatch.setenv("PDF2DIFY_DATABASE", str(data / "test.db"))
    import importlib
    import pdf2dify.main as main
    main = importlib.reload(main)
    client = TestClient(main.app)
    created = client.post("/api/domains", json={"name": "供应链合规"})
    assert created.status_code == 201
    category = created.json()["id"]
    assert category in [item["id"] for item in client.get("/api/domains").json()]
    assert client.patch(f"/api/domains/{category}", json={"name": "生产安全"}).status_code == 200

    source = tmp_path / "sample.pdf"
    source.write_bytes(b"%PDF placeholder")
    response = client.post("/api/jobs", json={
        "name": "custom", "source_path": str(source), "mode": "export", "fixed_domain": category,
    })
    assert response.status_code == 201
    assert response.json()["fixed_domain"] == category
    assert client.post("/api/jobs", json={
        "name": "unknown", "source_path": str(source), "fixed_domain": "not_known",
    }).status_code == 422

    settings = Settings.load()
    runner = PipelineRunner(settings, Database(settings.database_path))
    config_path = tmp_path / "config.yaml"
    runner._write_engine_config(config_path, tmp_path, tmp_path / "engine-data")
    assert json.loads(config_path.read_text(encoding="utf-8"))["categories"][category] == "生产安全"
