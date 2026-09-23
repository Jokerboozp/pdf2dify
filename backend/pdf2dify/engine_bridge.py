"""Run ops-pdf-rag functions with a per-job configuration.

This module is executed by the existing engine's Python interpreter. Keeping the
bridge out of the API process isolates heavy OCR dependencies and makes retries
safe after the web process restarts.
"""
from __future__ import annotations

import argparse
import json
import re
import os
import sys
import zipfile
from collections import Counter
from pathlib import Path
from xml.etree import ElementTree as ET


def load_engine(engine_root: Path) -> None:
    sys.path.insert(0, str(engine_root / "src"))


def verify(cfg: dict) -> dict:
    from ops_rag.common import digest_file, now, read_json, write_json
    from ops_rag.corpus import VERSION

    root = Path(cfg["data_dir"])
    manifest = read_json(root / "full-export/manifest.json")
    inventory = read_json(root / "inventory.json")["documents"]
    errors, notes, counts = [], [], Counter()
    covered_sources: set[str] = set()
    docs = {d["source_id"]: d for d in inventory}
    for source_id in sorted({d["source_id"] for d in manifest["documents"]}):
        corpus = read_json(root / "corpus" / f"{source_id}.json")
        if corpus["version"] != VERSION:
            errors.append({"source_id": source_id, "error": "stale_builder_version"})
        if corpus["source"]["sha256"] != docs[source_id]["sha256"]:
            errors.append({"source_id": source_id, "error": "stale_source"})
        if digest_file(docs[source_id]["path"]) != docs[source_id]["sha256"]:
            errors.append({"source_id": source_id, "error": "source_changed_on_disk"})
        covered = {r["page"] for chunk in corpus["chunks"] for r in chunk["regions"]}
        missing = sorted(set(range(1, docs[source_id]["pages"] + 1)) - covered)
        if missing:
            notes.append({"source_id": source_id, "empty_or_uncovered_pages": missing})
        counts["covered_pages"] += len(covered)
        covered_sources.add(source_id)
    for item in manifest["documents"]:
        path = Path(item["path"])
        if not path.exists():
            errors.append({"key": item["key"], "error": "missing_docx"})
            continue
        if path.stat().st_size > 15 * 1024 * 1024:
            errors.append({"key": item["key"], "error": "oversized_docx"})
        with zipfile.ZipFile(path) as archive:
            tree = ET.fromstring(archive.read("word/document.xml"))
            text = "".join(tree.itertext())
            embeds = tree.findall(".//{http://schemas.openxmlformats.org/drawingml/2006/main}blip")
            if len(embeds) != item["image_count"]:
                errors.append({"key": item["key"], "error": "docx_image_count_mismatch"})
            if item["source_name"] not in text:
                errors.append({"key": item["key"], "error": "missing_source_name"})
        counts["docx_documents"] += 1
    report = {
        "checked_at": now(), "counts": dict(counts), "sources": len(covered_sources),
        "total_sources": len(inventory),
        "pending_sources": sorted(set(docs) - covered_sources),
        "errors": errors, "notes": notes, "business_review": "pending",
        "interpretation": "Technical provenance checks only; not business accuracy approval.",
    }
    write_json(root / "reports/full-corpus-verification.json", report)
    return report


def audit_remote(cfg: dict) -> dict:
    """Verify only the documents managed by this job, not other jobs' receipts."""
    from ops_rag.common import now, read_json, write_json
    from ops_rag.full_sync import connect
    from ops_rag.search_anchors import anchor_text

    root = Path(cfg["data_dir"])
    manifest = read_json(root / "full-export/manifest.json")
    state = read_json(root / "dify/full-state.json")
    anchor_path = root / "dify/search-anchors.json"
    anchors = read_json(anchor_path).get("documents", {}) if anchor_path.exists() else {}
    client = connect(cfg)
    remote = {
        document["id"]: document
        for dataset in state["datasets"].values()
        for document in client.documents(dataset["id"])
    }
    checked, images, errors = 0, 0, []
    for item in manifest["documents"]:
        key = item["key"]
        receipt = state["documents"].get(key, {})
        document = remote.get(receipt.get("document_id"), {})
        problems = []
        if receipt.get("hash") != item["content_hash"] or document.get("indexing_status") != "completed" or not document.get("enabled"):
            problems.append("current_content_not_ready")
        if not receipt.get("document_id") or not receipt.get("dataset_id"):
            errors.append({"key": key, "errors": problems + ["missing_receipt"]})
            continue
        base = f"datasets/{receipt['dataset_id']}/documents/{receipt['document_id']}"
        detail = client.call("GET", base, params={"metadata": "only"})
        metadata = detail.get("doc_metadata") or []
        values = metadata if isinstance(metadata, dict) else {entry["name"]: entry.get("value") for entry in metadata}
        for name, value in item["metadata"].items():
            if values.get(name) != value:
                problems.append("metadata_mismatch:" + name)
        parents = client.call("GET", base + "/segments", params={"limit": 100}).get("data", [])
        if len(parents) != 1:
            errors.append({"key": key, "errors": problems + ["expected_one_parent"]})
            continue
        parent = parents[0]
        content = parent.get("content", "")
        if item["source_name"] not in content:
            problems.append("missing_source_name")
        for page in item.get("pages", []):
            if f"PDF 第{page}页" not in content:
                problems.append("missing_page:" + str(page))
        found_images = re.findall(r"!\[[^\]]*\]\(([^)]+)\)", content)
        images += len(found_images)
        if len(found_images) != item.get("image_count", 0):
            problems.append("image_count_mismatch")
        anchor = anchor_text(item)
        if anchor:
            receipt_anchor = anchors.get(key, {})
            children = client.call(
                "GET", base + f"/segments/{parent['id']}/child_chunks", params={"limit": 100}
            ).get("data", [])
            if not any(child["id"] == receipt_anchor.get("child_id") and child.get("content") == anchor for child in children):
                problems.append("missing_search_anchor")
        checked += 1
        if problems:
            errors.append({"key": key, "errors": problems})
    report = {
        "checked_at": now(), "checked": checked, "expected": len(manifest["documents"]),
        "image_references": images, "errors": errors,
        "passed": checked == len(manifest["documents"]) and not errors,
    }
    write_json(root / "reports/remote-corpus-audit.json", report)
    return report


def retire_replaced(cfg: dict, plan_path: Path) -> dict:
    """Disable only older documents for sources replaced by this job."""
    from ops_rag.common import now, read_json, write_json
    from ops_rag.full_sync import connect

    root = Path(cfg["data_dir"])
    plan = json.loads(plan_path.read_text(encoding="utf-8"))
    client = connect(cfg)
    retired = []
    for group, state_path in (
        ("documents", root / "dify/full-state.json"),
        ("navigation", root / "process-navigation/dify/full-state.json"),
    ):
        keys = plan.get(group, [])
        if not keys:
            continue
        state = read_json(state_path)
        receipts = state.get("documents", {})
        for key in keys:
            receipt = receipts.get(key)
            if not receipt or receipt.get("retired_at"):
                continue
            dataset = receipt["dataset_id"]
            document_id = receipt["document_id"]
            remote = {item["id"]: item for item in client.documents(dataset)}
            current = remote.get(document_id)
            if current and current.get("enabled"):
                client.call(
                    "PATCH", f"datasets/{dataset}/documents/status/disable",
                    json={"document_ids": [document_id]},
                )
                remote = {item["id"]: item for item in client.documents(dataset)}
                if remote.get(document_id, {}).get("enabled"):
                    raise RuntimeError(f"旧文档仍处于启用状态：{key}")
            receipt["retired_at"] = now()
            write_json(state_path, state)
            retired.append(key)
    result = {"retired": retired, "count": len(retired), "checked_at": now()}
    write_json(root / "reports/replaced-documents.json", result)
    return result


def setup_datasets(cfg: dict, navigation: bool = False) -> dict:
    from ops_rag.common import read_json, write_json
    from ops_rag.corpus import DOMAINS
    from ops_rag.full_sync import connect, retrieval_model

    client = connect(cfg)
    base = os.environ["DIFY_BASE_URL"].rstrip("/")
    prefix = os.environ.get("PDF2DIFY_DATASET_PREFIX", "pdf2dify-")
    mapping = json.loads(os.environ.get("PDF2DIFY_DATASET_IDS", "{}"))
    root = Path(cfg["data_dir"])
    if navigation:
        root = root / "process-navigation"
        categories = {"process_navigation": "资料导航"}
    else:
        categories = DOMAINS
    state_path = root / "dify/full-state.json"
    state = read_json(state_path) if state_path.exists() else {"datasets": {}, "documents": {}}
    if state.get("base_url", base) != base:
        raise ValueError("同步回执属于另一个 Dify 服务")
    state["base_url"] = base
    available, page = [], 1
    while True:
        batch = client.call("GET", "datasets", params={"page": page, "limit": 100})
        available.extend(batch.get("data", []))
        if not batch.get("has_more"):
            break
        page += 1
    by_id = {item["id"]: item for item in available}
    for domain, label in categories.items():
        mapped_id = mapping.get(domain)
        if mapped_id:
            if mapped_id not in by_id:
                raise ValueError(f"知识库映射无效：{domain}")
            dataset = by_id[mapped_id]
        else:
            name = prefix + label
            matches = [item for item in available if item["name"] == name]
            if len(matches) > 1:
                raise ValueError(f"知识库名称重复：{name}")
            if matches:
                dataset = matches[0]
            else:
                dataset = client.call("POST", "datasets", json={
                    "name": name,
                    "description": f"pdf2dify 本地 PDF 解析与 OCR；{label}。原文图片和页码保留，业务有效性待复核。",
                    "permission": "only_me", "indexing_technique": "high_quality",
                    "embedding_model": os.environ.get("DIFY_EMBEDDING_MODEL", "nomic-embed-text:latest"),
                    "embedding_model_provider": os.environ.get("DIFY_EMBEDDING_PROVIDER", "langgenius/ollama/ollama"),
                    "retrieval_model": retrieval_model(None if navigation else domain),
                })
                available.append(dataset)
                by_id[dataset["id"]] = dataset
        old_id = state.get("datasets", {}).get(domain, {}).get("id")
        if old_id and old_id != dataset["id"] and state.get("documents"):
            raise ValueError(f"{domain} 已有同步回执，不能直接切换目标知识库")
        state.setdefault("datasets", {})[domain] = {"id": dataset["id"], "name": dataset["name"]}
        write_json(state_path, state)
    return state["datasets"]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=[
        "scan", "native", "process", "build", "navigation", "verify",
        "dify-setup", "dify-upload", "dify-status",
        "dify-anchor", "dify-audit",
        "dify-retire",
        "nav-setup", "nav-upload", "nav-status", "nav-audit",
    ])
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--classifications")
    parser.add_argument("--retire-plan")
    parser.add_argument("--workers", type=int, default=2)
    args = parser.parse_args()
    engine_root = Path(args.engine_root).resolve()
    load_engine(engine_root)
    from ops_rag.common import config, read_json, write_json
    cfg = config(args.config)

    if args.stage == "scan":
        from ops_rag.inventory import scan
        result = scan(cfg)
        unique = {}
        duplicates = []
        for document in result["documents"]:
            if document["sha256"] in unique:
                duplicates.append({
                    "path": document["path"],
                    "same_as": unique[document["sha256"]]["path"],
                })
            else:
                unique[document["sha256"]] = document
        result["documents"] = list(unique.values())
        result["file_count"] = len(unique)
        result["total_pages"] = sum(item.get("pages", 0) for item in unique.values())
        result["duplicates"] = duplicates
        write_json(Path(cfg["data_dir"]) / "inventory.json", result)
        result = {k: v for k, v in result.items() if k != "documents"}
    elif args.stage == "native":
        from ops_rag.pipeline import native_extract
        result = native_extract(cfg, all_sources=True)
    elif args.stage == "process":
        from ops_rag.inventory import make_manifest
        from ops_rag.pipeline import process
        manifest = make_manifest(cfg, full=True)
        result = process(cfg, str(Path(cfg["data_dir"]) / "full-manifest.json"))
        result["planned_pages"] = len(manifest["pages"])
    elif args.stage == "build":
        import ops_rag.corpus as corpus
        classifications = json.loads(Path(args.classifications).read_text(encoding="utf-8"))
        original = corpus.classify

        def classify_with_override(doc, page=None):
            domain = classifications.get(doc["source_id"])
            return domain if domain else original(doc, page)

        corpus.classify = classify_with_override
        result = corpus.build(cfg)
        result["pending_sources"] = len(result["pending_sources"])
    elif args.stage == "navigation":
        from ops_rag.process_catalog import build
        result = build(cfg)
    elif args.stage == "verify":
        result = verify(cfg)
        if result["errors"]:
            print(json.dumps(result, ensure_ascii=False))
            return 2
    elif args.stage == "dify-retire":
        if not args.retire_plan:
            parser.error("--retire-plan is required for dify-retire")
        result = retire_replaced(cfg, Path(args.retire_plan))
    elif args.stage in {"dify-setup", "dify-upload", "dify-status", "dify-anchor", "dify-audit"}:
        from ops_rag import full_sync
        if args.stage == "dify-setup":
            result = setup_datasets(cfg)
        elif args.stage == "dify-upload":
            result = full_sync.upload(cfg, workers=max(1, min(args.workers, 4)))
        elif args.stage == "dify-anchor":
            from ops_rag.search_anchors import enrich
            result = enrich(cfg, workers=max(1, min(args.workers, 4)))
        elif args.stage == "dify-audit":
            result = audit_remote(cfg)
            if not result["passed"]:
                print(json.dumps(result, ensure_ascii=False))
                return 2
        else:
            result = full_sync.status(cfg)
    else:
        sys.path.insert(0, str(engine_root / "scripts"))
        import process_navigation
        from ops_rag import full_sync
        if args.stage == "nav-setup":
            result = setup_datasets(cfg, navigation=True)
        elif args.stage == "nav-upload":
            result = full_sync.upload(process_navigation.nav_config(cfg), workers=max(1, min(args.workers, 4)))
        else:
            result = process_navigation.status(cfg, audit=args.stage == "nav-audit")
            if args.stage == "nav-audit" and not result["passed"]:
                print(json.dumps(result, ensure_ascii=False))
                return 2
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
