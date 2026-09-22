import html
import statistics
from pathlib import Path
from .common import read_json, write_json, now


def build_report(cfg):
    root = Path(cfg['data_dir'])
    manifest = read_json(root/'pilot-manifest.json')
    pages = []
    missing = []
    for task in manifest['pages']:
        path = root/'parsed'/task['source_id']/f"p{task['page']:04}.json"
        if path.exists() and (rec := read_json(path)).get('status') == 'complete':
            pages.append(rec)
        else:
            missing.append({'source_id':task['source_id'],'page':task['page']})
    elapsed = [p['seconds'] for p in pages]
    result = dict(created_at=now(), planned_pages=len(manifest['pages']), completed_pages=len(pages),
                  missing=missing, native_chars=sum(len(p['cleaned_text']) for p in pages),
                  screenshots=sum(len(p['images']) for p in pages),
                  ocr_chars=sum(len(im['text']) for p in pages for im in p['images']),
                  low_confidence_lines=sum(im['low_confidence_count'] for p in pages for im in p['images']),
                  median_page_seconds=round(statistics.median(elapsed),2) if elapsed else None,
                  total_page_seconds=round(sum(elapsed),2),
                  timing_note='Latest per-page processing durations may include OCR cache hits. Do not use these as cold OCR throughput.',
                  status='extraction_measured_not_business_accepted')
    write_json(root/'reports'/'pilot-summary.json',result)
    esc = html.escape
    blocks = []
    for p in pages:
        imgs = ''.join(f'<details><summary>截图 {esc(im["image_id"])} · 低置信度行 {im["low_confidence_count"]}</summary><img loading="lazy" src="../{esc(im["path"])}"><pre>{esc(im["text"])}</pre></details>' for im in p['images'])
        blocks.append(f'<article><h2>{esc(p["name"])} · PDF 第 {p["page"]} 页</h2><div class="columns"><a href="../{esc(p["page_asset"])}"><img loading="lazy" src="../{esc(p["page_asset"])}"></a><section><h3>正文（按页面位置提取）</h3><pre>{esc(p["cleaned_text"])}</pre><p>截图文字不自动变成操作指令；请核对字段、箭头和示例值。</p>{imgs}</section></div></article>')
    body = f'''<!doctype html><html lang="zh-CN"><meta charset="utf-8"><title>PDF 试点核对报告</title><style>body{{font:16px/1.7 system-ui;margin:32px auto;max-width:1500px;background:#f4f6f8;color:#142333}}h1{{margin-bottom:8px}}article{{background:white;border:1px solid #dde3ea;padding:24px;margin:24px 0}}.columns{{display:grid;grid-template-columns:1fr 1fr;gap:28px}}img{{max-width:100%;height:auto}}pre{{white-space:pre-wrap;word-break:break-word;background:#f0f4f8;padding:16px;font:14px/1.8 monospace}}summary{{cursor:pointer;color:#125cb1}}@media(max-width:900px){{.columns{{grid-template-columns:1fr}}}}</style><h1>PDF 试点核对报告</h1><p>已处理 {len(pages)}/{len(manifest['pages'])} 页，{result['screenshots']} 张截图，截图 OCR {result['ocr_chars']} 字符。此报告是提取结果，尚不代表业务验收。</p>{''.join(blocks)}</html>'''
    output = root/'reports'/'pilot-review.html'
    output.write_text(body,encoding='utf-8')
    return {**result,'review_html':str(output)}
