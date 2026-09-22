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

