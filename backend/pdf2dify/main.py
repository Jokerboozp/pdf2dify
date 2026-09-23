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
from .categories import CategoryStore
from .db import Database
from .jobs import JobService
from .schemas import CategoryUpsert, DifySettingsUpdate, FileDomainUpdate, PathJobCreate


settings = Settings.load()
settings.ensure()
db = Database(settings.database_path)
db.init()
service = JobService(settings, db)
secrets = SecretStore(settings)
categories = CategoryStore(settings.data_dir)

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
    return categories.list()


@app.post("/api/domains", status_code=201)
def create_domain(payload: CategoryUpsert):
    try:
        return categories.create(payload.name)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@app.patch("/api/domains/{domain_id}")
def rename_domain(domain_id: str, payload: CategoryUpsert):
    try:
        return categories.rename(domain_id, payload.name)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="分类不存在或不可编辑") from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


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
        result["events"] = db.list_events(job_id, limit=200, recent=True)
        return result
    except KeyError as exc:
        raise not_found(exc) from exc


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    try:
        return service.delete(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


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
    if payload.domain not in categories.mapping():
        raise HTTPException(status_code=422, detail="未知业务分类")
    try:
        return db.set_file_domain(job_id, file_id, payload.domain)
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="文件不存在") from exc


@app.get("/api/jobs/{job_id}/files/{file_id}/preview")
def preview_source_pdf(job_id: str, file_id: str):
    try:
        db.get_job(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc
    item = next((row for row in db.list_files(job_id) if row["id"] == file_id), None)
    if not item:
        raise HTTPException(status_code=404, detail="文件不存在")
    path = Path(item["absolute_path"])
    if not path.is_file() or path.suffix.lower() != ".pdf":
        raise HTTPException(status_code=404, detail="原 PDF 不可用")
    return FileResponse(path, media_type="application/pdf", content_disposition_type="inline")


@app.get("/api/jobs/{job_id}/documents")
def list_documents(job_id: str):
    try:
        db.get_job(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc
    root = settings.data_dir / "jobs" / job_id / "engine-data"
    result = []
    for relative_manifest in ("full-export/manifest.json", "process-navigation/full-export/manifest.json"):
        manifest = root / relative_manifest
        if not manifest.is_file():
            continue
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        for item in payload.get("documents", []):
            result.append({
                "key": item["key"], "domain": item["domain"],
                "source_name": item["source_name"], "title": item.get("metadata", {}).get("section_title", ""),
                "pages": item.get("pages", []), "image_count": item.get("image_count", 0),
            })
    return result


@app.get("/api/jobs/{job_id}/documents/{document_key}")
def download_document(job_id: str, document_key: str):
    try:
        db.get_job(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc
    root = (settings.data_dir / "jobs" / job_id / "engine-data").resolve()
    for relative_manifest in ("full-export/manifest.json", "process-navigation/full-export/manifest.json"):
        manifest = root / relative_manifest
        if not manifest.is_file():
            continue
        payload = json.loads(manifest.read_text(encoding="utf-8"))
        item = next((entry for entry in payload.get("documents", []) if entry["key"] == document_key), None)
        if item:
            path = Path(item["path"]).resolve()
            if not path.is_relative_to(root) or not path.is_file():
                raise HTTPException(status_code=404, detail="章节文件不可用")
            return FileResponse(path, filename=path.name)
    raise HTTPException(status_code=404, detail="章节不存在")


@app.get("/api/jobs/{job_id}/events")
async def stream_events(job_id: str, after: int = 0):
    try:
        db.get_job(job_id)
    except KeyError as exc:
        raise not_found(exc) from exc

    async def events():
        cursor = max(0, after)
        last_status_update = None
        loop = asyncio.get_running_loop()
        last_sent = loop.time()
        while True:
            rows = db.list_events(job_id, after=cursor, limit=100)
            for row in rows:
                cursor = row["id"]
                yield f"id: {cursor}\nevent: log\ndata: {json.dumps(row, ensure_ascii=False)}\n\n"
                last_sent = loop.time()
            job = db.get_job(job_id)
            if job["updated_at"] != last_status_update:
                yield f"event: status\ndata: {json.dumps(job, ensure_ascii=False)}\n\n"
                last_status_update = job["updated_at"]
                last_sent = loop.time()
            elif loop.time() - last_sent >= 15:
                yield ": keepalive\n\n"
                last_sent = loop.time()
            if job["status"] in {"completed", "failed", "cancelled"} and len(rows) < 100:
                break
            if len(rows) == 100:
                continue
            await asyncio.sleep(2)

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
        "PDF2DIFY_DATASET_PREFIX": payload.dataset_prefix,
        "PDF2DIFY_DATASET_IDS": json.dumps(payload.dataset_ids, ensure_ascii=False) if payload.dataset_ids is not None else None,
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
