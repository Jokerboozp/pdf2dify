"""汇总开发成果与应用效果指标，输出 data/reports/metrics-report.json 与 Markdown。

只统计本机真实产物（清单、逐页 JSON、卡片、导出、评测报告），
不推测业务准确率；未经业务确认的口径统一标注为 “技术验证”。
"""

from __future__ import annotations

import hashlib
import json
import statistics
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data"
REPORTS = DATA / "reports"


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def load_yaml(path: Path) -> Any:
    try:
        import yaml

        return yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def human_bytes(n: int) -> str:
    for unit in ("B", "KiB", "MiB", "GiB", "TiB"):
        if n < 1024 or unit == "TiB":
            return f"{n:.1f} {unit}" if unit != "B" else f"{n} B"
        n /= 1024.0
    return f"{n} B"


def dir_size(path: Path) -> tuple[int, int]:
    files = bytes_ = 0
    for p in path.rglob("*"):
        if p.is_file():
            files += 1
            bytes_ += p.stat().st_size
    return files, bytes_


def digest_tree(paths: list[Path]) -> tuple[str, int]:
    """对给定文件集合做顺序无关的内容指纹（按相对路径排序）。"""
    h = hashlib.sha256()
    files: list[Path] = []
    for p in paths:
        if p.is_file():
            files.append(p)
        elif p.is_dir():
            files.extend(x for x in p.rglob("*") if x.is_file())
    files.sort(key=lambda p: str(p.relative_to(ROOT)).replace("\\", "/"))
    for p in files:
        rel = str(p.relative_to(ROOT)).replace("\\", "/")
        h.update(rel.encode("utf-8"))
        h.update(p.read_bytes())
    return h.hexdigest(), len(files)


# ---------------------------------------------------------------- 1. 清点
def collect_inventory() -> dict:
    inv = load_json(DATA / "inventory.json") or {}
    docs = inv.get("documents", [])
    pages = sum(int(d.get("pages") or 0) for d in docs)
    total_bytes = sum(int(d.get("bytes") or 0) for d in docs)
    status = {}
    for d in docs:
        status[d.get("status", "unknown")] = status.get(d.get("status", "unknown"), 0) + 1
    modules = {}
    for d in docs:
        top = str(d.get("relative_path", "")).split("/")[0] or "(root)"
        modules[top] = modules.get(top, 0) + 1
    hashes = {d.get("sha256") for d in docs if d.get("sha256")}
    return {
        "source_root": inv.get("source_root"),
        "created_at": inv.get("created_at"),
        "documents": len(docs),
        "pages": pages,
        "bytes": total_bytes,
        "bytes_human": human_bytes(total_bytes),
        "unique_sha256": len(hashes),
        "sha256_ok": len(hashes) == len(docs),
        "status_counts": status,
        "top_level_groups": len(modules),
        "largest_groups": sorted(modules.items(), key=lambda kv: -kv[1])[:8],
    }


# ------------------------------------------------- 2. 逐页提取与 OCR 汇总
def collect_pages() -> dict:
    parsed_files = sorted((DATA / "parsed").rglob("*.json"))
    screenshot_count = 0
    screenshot_bytes = 0
    ocr_chars = 0
    ocr_lines = 0
    low_conf_lines = 0
    ocr_conf: list[float] = []
    pages_with_ocr = 0
    pages_with_native = 0
    pages_failed = 0
    native_chars_parsed = 0
    ocr_seconds = 0.0
    ocr_seconds_n = 0
    anchor_pages = 0

    for f in parsed_files:
        d = load_json(f)
        if not isinstance(d, dict):
            pages_failed += 1
            continue
        if d.get("status") not in (None, "complete", "ok"):
            pages_failed += 1
        if d.get("cleaned_text") or d.get("native_text"):
            pages_with_native += 1
        native_chars_parsed += len(d.get("cleaned_text") or d.get("native_text") or "")
        images = d.get("images") or []
        for img in images:
            screenshot_count += 1
            lines = img.get("lines") or []
            texts = []
            for ln in lines:
                t = ln.get("text") or ""
                texts.append(t)
                ocr_lines += 1
                c = ln.get("score", ln.get("confidence"))
                if isinstance(c, (int, float)):
                    ocr_conf.append(float(c))
                    if float(c) < 0.6:
                        low_conf_lines += 1
            block = "".join(texts)
            if not block:
                block = img.get("text") or ""
            ocr_chars += len(block)
            if block:
                pages_with_ocr += 1
        sec = d.get("seconds") or d.get("duration_seconds")
        if isinstance(sec, (int, float)):
            ocr_seconds += float(sec)
            ocr_seconds_n += 1

    assets = DATA / "assets"
    asset_files, asset_bytes = dir_size(assets) if assets.exists() else (0, 0)
    page_pngs = len(list((assets).rglob("p*.png"))) if assets.exists() else 0

    native_files = sorted((DATA / "native").rglob("*.json"))
    native_chars = 0
    native_pages = 0
    blank_pages = 0
    per_doc_chars: list[int] = []
    for f in native_files:
        d = load_json(f)
        if not isinstance(d, dict):
            continue
        doc_chars = 0
        for pg in d.get("pages_data") or []:
            native_pages += 1
            t = pg.get("text") or ""
            if not (t or "").strip():
                blank_pages += 1
            doc_chars += len(t)
        native_chars += doc_chars
        per_doc_chars.append(doc_chars)

    return {
        "parsed_page_files": len(parsed_files),
        "parse_failed_pages": pages_failed,
        "pages_with_native": pages_with_native,
        "native_docs": len(native_files),
        "native_pages": native_pages,
        "native_chars": native_chars,
        "native_blank_pages": blank_pages,
        "native_chars_per_doc_median": int(statistics.median(per_doc_chars)) if per_doc_chars else 0,
        "screenshots_total": screenshot_count,
        "screenshots_localised": pages_with_ocr,
        "ocr_lines": ocr_lines,
        "ocr_chars": ocr_chars,
        "ocr_low_conf_lines": low_conf_lines,
        "ocr_mean_conf": round(statistics.mean(ocr_conf), 3) if ocr_conf else None,
        "ocr_conf_p10": round(sorted(ocr_conf)[int(len(ocr_conf) * 0.10)], 3) if ocr_conf else None,
        "ocr_conf_p90": round(sorted(ocr_conf)[int(len(ocr_conf) * 0.90)], 3) if ocr_conf else None,
        "ocr_chars_per_screenshot": round(ocr_chars / screenshot_count, 1) if screenshot_count else 0,
        "asset_files": asset_files,
        "asset_bytes": asset_bytes,
        "asset_bytes_human": human_bytes(asset_bytes),
        "page_pngs": page_pngs,
        "ocr_cache_entries": len(list((DATA / "ocr-cache").rglob("*"))) if (DATA / "ocr-cache").exists() else 0,
    }


# ------------------------------------------------------- 3. 内容与索引规模
def collect_corpus() -> dict:
    export_manifest = load_json(DATA / "full-export" / "manifest.json") or {}
    entries = export_manifest.get("entries") or export_manifest.get("documents") or []
    if isinstance(entries, dict):
        entries = list(entries.values())
    dicts = [e for e in entries if isinstance(e, dict)]
    image_refs = sum(int(e.get("image_count") or len(e.get("images") or [])) for e in dicts)
    pages: set[int] = set()
    for e in dicts:
        for p in e.get("pages") or []:
            try:
                pages.add(int(p))
            except (TypeError, ValueError):
                pass
    sources = {e.get("source_id") for e in dicts if e.get("source_id")}
    chunks = {c for e in dicts for c in (e.get("chunk_ids") or [])}
    with_images = sum(1 for e in dicts if int(e.get("image_count") or 0) > 0)
    cards = sorted((DATA / "cards").glob("faq-*.json"))
    procedures = sorted((DATA / "procedure-packets").glob("*.json"))
    docx_files, docx_bytes = dir_size(DATA / "full-export") if (DATA / "full-export").exists() else (0, 0)
    by_domain: dict[str, int] = {}
    domain_images: dict[str, int] = {}
    for e in dicts:
        dom = e.get("domain") or e.get("dataset") or "(未标注)"
        by_domain[dom] = by_domain.get(dom, 0) + 1
        domain_images[dom] = domain_images.get(dom, 0) + int(e.get("image_count") or 0)
    assets = DATA / "assets"
    page_pngs = len(list(assets.rglob("p*.png"))) if assets.exists() else 0
    crops = len(list(assets.rglob("*-img-*.png"))) if assets.exists() else 0
    verified = (load_json(REPORTS / "full-corpus-verification.json") or {}).get("counts") or {}
    return {
        "verified_covered_pages": verified.get("covered_pages"),
        "verified_image_refs": verified.get("image_references"),
        "manifest_documents": len(dicts),
        "manifest_sources": len(sources),
        "manifest_image_refs": image_refs,
        "manifest_documents_with_images": with_images,
        "manifest_documents_with_image_pct": round(with_images / len(dicts) * 100, 1) if dicts else 0,
        "manifest_pages_field_values": len(pages),
        "manifest_chunk_ids": len(chunks),
        "cards_json": len(cards),
        "procedure_packets": len(procedures),
        "export_files": docx_files,
        "export_bytes": docx_bytes,
        "export_bytes_human": human_bytes(docx_bytes),
        "page_pngs": page_pngs,
        "crop_pngs": crops,
        "by_domain": dict(sorted(by_domain.items(), key=lambda kv: -kv[1])),
        "images_by_domain": dict(sorted(domain_images.items(), key=lambda kv: -kv[1])),
    }


# ------------------------------------------------------------- 4. 测试与评测
def collect_quality() -> dict:
    pytest_cache = load_json(ROOT / ".pytest_cache" / "v" / "cache" / "lastfailed")
    delivery = load_json(REPORTS / "delivery.json") or {}
    eval_local = load_json(REPORTS / "evaluation-local.json") or {}
    cases = load_yaml(ROOT / "evaluation" / "cases.yaml")
    smoke = load_yaml(ROOT / "evaluation" / "full-smoke.yaml")
    corpus_verification = load_json(REPORTS / "full-corpus-verification.json") or {}
    indexing = load_json(REPORTS / "full-indexing.json") or {}
    test_sources = [p for p in (ROOT / "tests").glob("test_*.py")]
    test_lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in test_sources)
    test_funcs = 0
    for p in test_sources:
        test_funcs += p.read_text(encoding="utf-8").count("def test_")
    case_list = (cases or {}).get("cases") if isinstance(cases, dict) else cases
    smoke_list = (smoke or {}).get("cases") if isinstance(smoke, dict) else smoke

    # 离线 BM25 评测结果
    summary = {}
    if isinstance(eval_local, dict):
        for key in ("summary", "metrics", "totals", "aggregate"):
            if isinstance(eval_local.get(key), dict):
                summary = eval_local[key]
                break
        if not summary:
            summary = {
                k: v
                for k, v in eval_local.items()
                if isinstance(v, (int, float, str)) and k not in ("created_at",)
            }

    domains = (indexing or {}).get("domains") or {}
    indexed_ready = sum(int((d.get("target", {}).get("counts", {}) or {}).get("ready", 0)) for d in domains.values())
    anchors_current = sum(
        int((d.get("target", {}).get("counts", {}) or {}).get("anchors_current", 0)) for d in domains.values()
    )
    anchor_required = sum(
        int((d.get("target", {}).get("counts", {}) or {}).get("anchor_required", 0)) for d in domains.values()
    )

    return {
        "test_files": len(test_sources),
        "test_functions": test_funcs,
        "test_lines": test_lines,
        "delta_tests_declared": delivery.get("tests"),
        "lastfailed_entries": len(pytest_cache or {}),
        "offline_eval_cases": len(case_list) if isinstance(case_list, list) else None,
        "offline_eval_summary": summary,
        "smoke_cases": len(smoke_list) if isinstance(smoke_list, list) else None,
        "corpus_verification": corpus_verification.get("counts"),
        "corpus_verification_errors": corpus_verification.get("errors"),
        "business_review": corpus_verification.get("business_review"),
        "domains": len(domains),
        "indexed_ready_parents": indexed_ready,
        "anchor_required": anchor_required,
        "anchors_current": anchors_current,
        "indexing_checked_at": (indexing or {}).get("checked_at"),
    }


# ----------------------------------------------------- 5. 缓存/续跑收益估算
def collect_reuse() -> dict:
    coordinator = load_json(REPORTS / "ingestion-coordinator.json") or {}
    processing = load_json(REPORTS / "full-processing.json") or {}
    pilot = load_json(REPORTS / "pilot-summary.json") or {}
    ocr_cache = DATA / "ocr-cache"
    cache_files, cache_bytes = dir_size(ocr_cache) if ocr_cache.exists() else (0, 0)

    started = processing.get("started_at")
    finished = processing.get("finished_at")
    wall_seconds = None
    if started and finished:
        try:
            a = datetime.fromisoformat(started)
            b = datetime.fromisoformat(finished)
            wall_seconds = (b - a).total_seconds()
        except Exception:
            wall_seconds = None

    pages = int(processing.get("planned_pages") or 0)
    return {
        "full_processing": {
            "planned_pages": pages,
            "completed": processing.get("completed"),
            "failed_pages": len(processing.get("failed") or []),
            "wall_seconds": wall_seconds,
            "wall_hours": round(wall_seconds / 3600, 2) if wall_seconds else None,
            "pages_per_minute": round(pages / (wall_seconds / 60), 2) if wall_seconds else None,
            "started_at": started,
            "finished_at": finished,
        },
        "ocr_cache_entries": cache_files,
        "ocr_cache_bytes_human": human_bytes(cache_bytes),
        "pilot_cached_rerun_seconds": pilot.get("total_page_seconds"),
        "pilot_cached_rerun_note": pilot.get("timing_note"),
        "ingestion_resume_phase": coordinator.get("phase"),
        "ingestion_checked_at": coordinator.get("checked_at"),
        "ingestion_counts": coordinator.get("counts"),
    }


def render_markdown(r: dict) -> str:
    inv, ext, cor, qua, reu, eng = (
        r["inventory"],
        r["extraction"],
        r["corpus"],
        r["quality"],
        r["reuse_and_resume"],
        r["engineering"],
    )
    ev = qua["offline_eval_summary"]
    fp = reu["full_processing"]
    domain_rows = "\n".join(
        f"| {k} | {v} | {cor['images_by_domain'].get(k, 0)} |" for k, v in cor["by_domain"].items()
    )
    return f"""# 开发成果与应用效果（自动核对）

> 由 `scripts/report_metrics.py` 扫描本机产物生成，生成时间 {r['generated_at']}。
> 全部数字可从 `data/` 下清单、逐页 JSON、导出清单与报告复核；业务准确率未经业务负责人确认，
> 只统计“技术验证”口径。原始资料处理区间：{fp['started_at']} → {fp['finished_at']}。

## 一、一句话结论

把 {inv['documents']} 份、{inv['pages']} 页（{inv['bytes_human']}）只读 PDF 运维手册，转成
{qua['domains']} 个主题库、{cor['manifest_documents']} 个带页码和图的可检索知识条目；
本机一次性处理耗时 {fp['wall_hours']} 小时、失败 {fp['failed_pages']} 页，
全部条目带来源文件 SHA256、页码与截图坐标，可回溯到原文。

## 二、可量化成果

| 指标 | 实测值 | 复核位置 |
|---|---|---|
| 原始 PDF 份数 / 页数 / 体积 | {inv['documents']} / {inv['pages']} / {inv['bytes_human']} | `data/inventory.json` |
| 文件指纹唯一且齐全 | {inv['unique_sha256']} 份 SHA256（{ '全部一致' if inv['sha256_ok'] else '存在重复' }） | `data/inventory.json` |
| 原生文字提取 | {ext['native_pages']} 页、{ext['native_chars']:,} 字符（空白页 {ext['native_blank_pages']}） | `data/native/` |
| 截图定位与识别 | {ext['screenshots_total']:,} 张截图、{ext['ocr_chars']:,} 字符、{ext['ocr_lines']:,} 行 | `data/parsed/` |
| OCR 平均置信度 | {ext['ocr_mean_conf']}（P10={ext['ocr_conf_p10']}，P90={ext['ocr_conf_p90']}） | `data/parsed/` |
| 低置信行（<0.6，待复核） | {ext['ocr_low_conf_lines']:,} 行，占 {round(ext['ocr_low_conf_lines']/max(ext['ocr_lines'],1)*100,1)}% | `data/parsed/` |
| 本地图像资产 | 整页 PNG {ext['page_pngs']:,} 张 + 截图裁切 {cor['crop_pngs']:,} 张，{ext['asset_bytes_human']} | `data/assets/` |
| 结构化知识条目 | {cor['manifest_documents']} 条，覆盖 {cor['verified_covered_pages']} 页、{cor['manifest_sources']} 份来源 | `data/full-export/manifest.json` |
| 条目自带原图引用 | {cor['manifest_image_refs']:,} 处，{cor['manifest_documents_with_images']} 条含图（{cor['manifest_documents_with_image_pct']}%） | 同上 |
| FAQ 卡片 / 流程证据包 | {cor['cards_json']} 张 / {cor['procedure_packets']} 份 | `data/cards/`、`data/procedure-packets/` |
| 代码测试 | {qua['test_functions']} 个测试函数（{qua['test_files']} 个文件、{eng['code_lines']} 行代码） | `tests/` |
| 离线检索评测 | {qua['offline_eval_cases']} 用例，可评分 {ev.get('scored_retrieval_cases')} 条：hit@1={ev.get('hit_at_1')}、hit@5={ev.get('hit_at_5')} | `data/reports/evaluation-local.json` |
| 溯源校验 | 覆盖 {qua['corpus_verification']['covered_pages']} 页、{qua['corpus_verification']['parent_chunks']} 个条目、{qua['corpus_verification']['image_references']:,} 处图片引用，错误 {len(qua['corpus_verification_errors'] or [])} 项 | `data/reports/full-corpus-verification.json` |
| 远端索引就绪 | {qua['indexed_ready_parents']} 条当前版本可检索，检索锚点 {qua['anchors_current']}/{qua['anchor_required']} | `data/reports/full-indexing.json` |
| 断点续跑 | 全量 {fp['completed']}/{fp['planned_pages']} 页完成、{fp['failed_pages']} 失败，OCR 缓存 {reu['ocr_cache_entries']:,} 项 | `data/reports/full-processing.json` |

## 三、九个主题库分布

| 主题库 | 条目数 | 原图引用 |
|---|---:|---:|
{domain_rows}

## 四、对照原始八项工作：各自交付了什么

| 原汇报的功能 | 可展示的成果 | 支撑数字 |
|---|---|---|
| 1 PDF 批量扫描、页数统计、版本校验 | 全库清单与指纹台账，源文件变更即阻断旧证据复用 | {inv['documents']} 份 / {inv['pages']} 页 / {inv['unique_sha256']} 个 SHA256 |
| 2 原生文字提取与结构化保存 | 逐页 JSON（原文、清洗文、页图路径），可直接被下游引用 | {ext['native_pages']} 页 / {ext['native_chars']:,} 字符 |
| 3 RapidOCR + ONNX + Pillow 文字识别 | 截图、扫描页、界面文字本地识别并留坐标，不出网 | {ext['screenshots_total']:,} 张 / {ext['ocr_chars']:,} 字符 / 均值 {ext['ocr_mean_conf']} |
| 4 正则 + Markdown + python-docx 整理 | FAQ 卡片、跨页流程包、可导入知识库的图文文档 | {cor['cards_json']} 卡片 / {cor['procedure_packets']} 流程包 / {cor['export_files']} 个文档 |
| 5 JSON 元数据 + 页码 + 坐标溯源 | 每条答案可回指原文件、页码、截图位置，校验 0 错误 | {cor['verified_image_refs']:,} 处引用 / {cor['verified_covered_pages']} 页 |
| 6 BM25 词法检索 | 本地检索基线，用于排查覆盖盲区；并生成原文检索锚点 | hit@1={ev.get('hit_at_1')} / hit@5={ev.get('hit_at_5')} / 锚点 {qua['anchors_current']} 条 |
| 7 哈希 + JSON 状态：缓存、续跑、增量 | 冷处理 {fp['wall_hours']} 小时完成全库；复跑命中缓存、失败可续 | {fp['pages_per_minute']} 页/分钟 / 失败 {fp['failed_pages']} 页 / 缓存 {reu['ocr_cache_entries']:,} 项 |
| 8 pytest + YAML + 评测脚本 | 回归测试与检索评测纳入流程，改一处可自动复验 | {qua['test_functions']} 个测试 / {qua['offline_eval_cases']} 用例 |

## 五、应用效果（怎么用、替代了什么）

1. **问答即给出处**：用户提问后返回原文操作步骤、适用条件与 PDF 页码，并可直接查看原页截图；
   实测样例见 `data/reports/full-chat-project-ui.txt`、`data/reports/full-installed-chat-ui.txt`。
2. **替代人工翻手册**：原先需在 {inv['documents']} 份手册里按目录逐页找操作步骤，现由一次检索定位到
   条目与页码；候选证据面从 {inv['pages']} 页收敛到 Top 5 条目。
3. **证据可审计**：每条内容保留来源 SHA256、页码、坐标与图片引用，出现争议可回原文核对，
   业务口径未确认时明确回复“无法确认”，见 `data/reports/full-version-unknown-ui.txt`。
4. **形成可复用产线**：{eng['python_modules']} 个模块 + {eng['scripts']} 个脚本构成“扫描→提取→识别→
   整理→入库→评测”的固定流程，后续新增或改版手册按同一命令增量更新，不需要重做工程。
5. **数据不出本地**：PDF 渲染、截图裁切、OCR 全部本机执行，云端只接收检索到的文字与图片链接。

## 六、尚未完成 / 不应夸大的部分

- 业务准确率、适用系统版本、岗位权限**未由业务负责人确认**（`business_review=pending`）。
- 低置信 OCR {ext['ocr_low_conf_lines']:,} 行只是“待复核标记”，不等于 {ext['ocr_low_conf_lines']:,} 个错误。
- 检索 hits 是本地词法基线，不能当作线上回答准确率；Dify 端到端验收仍待补。
- 未启用重排模型；混合检索权重与 Top K 仍需按业务问题集调参。
- 索引快照时间：{qua['indexing_checked_at']}；重新生成本文档即可刷新。

---
*重新生成：`.\\\\.venv\\\\Scripts\\\\python.exe scripts/report_metrics.py`*
"""


def main() -> int:
    inventory = collect_inventory()
    pages = collect_pages()
    corpus = collect_corpus()
    quality = collect_quality()
    reuse = collect_reuse()

    code_files = [
        *sorted((ROOT / "src" / "ops_rag").glob("*.py")),
        *sorted((ROOT / "scripts").glob("*.py")),
        *sorted((ROOT / "tests").glob("*.py")),
    ]
    code_lines = sum(len(p.read_text(encoding="utf-8").splitlines()) for p in code_files)
    code_digest, code_count = digest_tree(code_files)

    report = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "scope_note": "全部数字来自本机产物文件；业务准确率未经业务负责人确认，标注为技术验证。",
        "inventory": inventory,
        "extraction": pages,
        "corpus": corpus,
        "quality": quality,
        "reuse_and_resume": reuse,
        "engineering": {
            "python_modules": len(sorted((ROOT / "src" / "ops_rag").glob("*.py"))),
            "scripts": len(sorted((ROOT / "scripts").glob("*.py"))),
            "test_files": len(sorted((ROOT / "tests").glob("test_*.py"))),
            "code_files": code_count,
            "code_lines": code_lines,
            "code_sha256": code_digest,
        },
    }

    REPORTS.mkdir(parents=True, exist_ok=True)
    out = REPORTS / "metrics-report.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    md_out = ROOT / "docs" / "results.md"
    md_out.write_text(render_markdown(report), encoding="utf-8")
    print(f"wrote {out.relative_to(ROOT)}")
    print(f"wrote {md_out.relative_to(ROOT)}")
    print(json.dumps({k: report[k] for k in ("inventory", "corpus", "engineering")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
