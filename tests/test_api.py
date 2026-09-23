from pathlib import Path


def test_health_and_path_job(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    source = tmp_path / "source"
    source.mkdir()
    (source / "one.pdf").write_bytes(b"%PDF placeholder")
    monkeypatch.setenv("PDF2DIFY_DATA_DIR", str(data))
    monkeypatch.setenv("PDF2DIFY_DATABASE", str(data / "test.db"))

    import importlib
    import pdf2dify.main as main
    main = importlib.reload(main)
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    assert client.get("/api/health").status_code == 200
    response = client.post("/api/jobs", json={
        "name": "测试任务", "source_path": str(source), "mode": "export",
    })
    assert response.status_code == 201
    assert response.json()["status"] == "queued"
    assert len(client.get("/api/jobs").json()) == 1
    job_id = response.json()["id"]
    assert client.post(f"/api/jobs/{job_id}/pause").json()["status"] == "paused"
    assert client.get(f"/api/jobs/{job_id}").json()["status"] == "paused"
    assert client.post(f"/api/jobs/{job_id}/resume").json()["status"] == "queued"
    assert client.post(f"/api/jobs/{job_id}/cancel").json()["status"] == "cancelled"


def test_dify_base_url_can_be_cleared(monkeypatch, tmp_path: Path):
    data = tmp_path / "data"
    monkeypatch.setenv("PDF2DIFY_DATA_DIR", str(data))
    monkeypatch.setenv("PDF2DIFY_DATABASE", str(data / "test.db"))

    import importlib
    import pdf2dify.main as main
    main = importlib.reload(main)
    from fastapi.testclient import TestClient

    client = TestClient(main.app)
    assert client.put("/api/settings/dify", json={
        "dify_base_url": "https://example.test/v1", "dify_api_key": "test-key",
    }).status_code == 200
    assert client.get("/api/settings/dify").json()["dify_base_url"] == "https://example.test/v1"

    assert client.put("/api/settings/dify", json={
        "dify_base_url": "", "dify_api_key": "",
    }).status_code == 200
    assert client.get("/api/settings/dify").json()["dify_base_url"] == ""
    assert client.get("/api/settings/dify").json()["dify_api_key_configured"] is True
