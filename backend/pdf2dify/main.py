from __future__ import annotations

import asyncio
import json
from pathlib import Path

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

from .config import SecretStore, Settings
from .db import Database
from .domains import DOMAINS
from .jobs import JobService
from .schemas import DifySettingsUpdate, FileDomainUpdate, PathJobCreate


settings = Settings.load()
settings.ensure()
db = Database(settings.database_path)
db.init()
service = JobService(settings, db)
secrets = SecretStore(settings)

app = FastAPI(title="pdf2dify", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def not_found(exc: KeyError) -> HTTPException:
    return HTTPException(status_code=404, detail=f"任务不存在：{exc.args[0]}")


@app.get("/api/health")
def health():
    return {
        "status": "ok", "version": "0.1.0",
        "engine_ready": settings.engine_python.is_file() and (settings.engine_root / "src/ops_rag").is_dir(),
        "engine_root": str(settings.engine_root),
    }


@app.get("/api/domains")
def domains():
    return [{"id": key, "name": value} for key, value in DOMAINS.items()]


@app.get("/api/jobs")
def list_jobs(limit: int = 100):
    return db.list_jobs(min(max(limit, 1), 500))


@app.post("/api/jobs", status_code=201)
def create_path_job(payload: PathJobCreate):
    try:
        return service.create_path_job(**payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.post("/api/jobs/upload", status_code=201)
def create_upload_job(
    name: str = Form(...), mode: str = Form("export"), fixed_domain: str | None = Form(None),
    files: list[UploadFile] = File(...),
):
    if mode not in {"export", "sync"}:
        raise HTTPException(status_code=422, detail="mode 必须是 export 或 sync")
    try:
        pairs = [(item.filename or "upload.pdf", item.file) for item in files]
        return service.create_upload_job(
            name=name, mode=mode, fixed_domain=fixed_domain or None, files=pairs,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    try:
        result = db.get_job(job_id)
        result["files"] = db.list_files(job_id)
        result["events"] = db.list_events(job_id, limit=200)
        return result
    except KeyError as exc:
        raise not_found(exc) from exc


@app.post("/api/jobs/{job_id}/pause")
def pause_job(job_id: str):
    try:
        return service.request_pause(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc


@app.post("/api/jobs/{job_id}/resume")
def resume_job(job_id: str):
    try:
        return service.resume(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    try:
        return service.cancel(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc


@app.patch("/api/jobs/{job_id}/files/{file_id}")
def update_file_domain(job_id: str, file_id: str, payload: FileDomainUpdate):
    try:
        return db.set_file_domain(job_id, file_id, payload.domain)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc


@app.get("/api/jobs/{job_id}/events")
async def stream_events(job_id: str, after: int = 0):
    try:
        db.get_job(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc

    async def events():
        cursor = after
        while True:
            rows = db.list_events(job_id, after=cursor, limit=100)
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: log\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
            job = db.get_job(job_id)
            yield f"event: status\ndata: {json.dumps(job, ensure_ascii=False)}\n\n"
            if job["status"] in {"completed", "failed", "cancelled"}:
                break
            await asyncio.sleep(1)

    return StreamingResponse(events(), media_type="text/event-stream")


@app.get("/api/jobs/{job_id}/artifacts/{artifact}")
def download_artifact(job_id: str, artifact: str):
    allowed = {
        "dify-ready.zip": "dify-ready.zip",
        "manifest.json": "dify-ready/manifest.json",
        "manifest.xlsx": "dify-ready/manifest.xlsx",
        "quality-report.html": "dify-ready/quality-report.html",
        "verification.json": "engine-data/reports/full-corpus-verification.json",
        "dify-status.json": "engine-data/reports/full-indexing.json",
    }
    if artifact not in allowed:
        raise HTTPException(status_code=404, detail="产物不存在")
    try:
        job = db.get_job(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc
    root = (settings.data_dir / "jobs" / job_id).resolve()
    path = (root / allowed[artifact]).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise HTTPException(status_code=404, detail="产物尚未生成")
    return FileResponse(path, filename=path.name)


@app.get("/api/settings/dify")
def get_dify_settings():
    return secrets.public()


@app.put("/api/settings/dify")
def update_dify_settings(payload: DifySettingsUpdate):
    values = {
        "DIFY_BASE_URL": payload.dify_base_url,
        "DIFY_DATASET_API_KEY": payload.dify_api_key,
        "DIFY_EMBEDDING_PROVIDER": payload.embedding_provider,
        "DIFY_EMBEDDING_MODEL": payload.embedding_model,
    }
    secrets.update(values)
    return secrets.public()


@app.post("/api/settings/dify/test")
def test_dify_connection():
    values = secrets.read()
    base = values.get("DIFY_BASE_URL", "").rstrip("/")
    key = values.get("DIFY_DATASET_API_KEY", "")
    if not base or not key:
        raise HTTPException(status_code=422, detail="请先保存 Dify 地址和 API Key")
    try:
        response = httpx.get(
            f"{base}/datasets", params={"page": 1, "limit": 1},
            headers={"Authorization": f"Bearer {key}"}, timeout=15,
        )
        response.raise_for_status()
        return {"ok": True, "message": "Dify 知识库 API 连接成功"}
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"Dify 连接失败：{exc}") from exc


frontend_dist = settings.project_root / "frontend" / "dist"
if frontend_dist.is_dir():
    assets = frontend_dist / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def frontend(path: str):
        candidate = (frontend_dist / path).resolve()
        if candidate.is_relative_to(frontend_dist.resolve()) and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(frontend_dist / "index.html")


def run() -> None:
    import uvicorn
    uvicorn.run("pdf2dify.main:app", host="127.0.0.1", port=8010, reload=False)


if __name__ == "__main__":
    run()
