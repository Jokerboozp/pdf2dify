"""Run ops-pdf-rag functions with a per-job configuration.

This module is executed by the existing engine's Python interpreter. Keeping the
bridge out of the API process isolates heavy OCR dependencies and makes retries
safe after the web process restarts.
"""
from __future__ import annotations

import argparse
import json
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


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=[
        "scan", "native", "process", "build", "navigation", "verify",
        "dify-setup", "dify-upload", "dify-status",
        "nav-setup", "nav-upload", "nav-status",
    ])
    parser.add_argument("--engine-root", required=True)
    parser.add_argument("--config", required=True)
    parser.add_argument("--classifications")
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
    elif args.stage in {"dify-setup", "dify-upload", "dify-status"}:
        from ops_rag import full_sync
        if args.stage == "dify-setup":
            result = full_sync.setup(cfg)
        elif args.stage == "dify-upload":
            result = full_sync.upload(cfg, workers=max(1, min(args.workers, 4)))
        else:
            result = full_sync.status(cfg)
    else:
        sys.path.insert(0, str(engine_root / "scripts"))
        import process_navigation
        from ops_rag import full_sync
        if args.stage == "nav-setup":
            result = process_navigation.setup(cfg)
        elif args.stage == "nav-upload":
            result = full_sync.upload(process_navigation.nav_config(cfg), workers=max(1, min(args.workers, 4)))
        else:
            result = process_navigation.status(cfg)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
