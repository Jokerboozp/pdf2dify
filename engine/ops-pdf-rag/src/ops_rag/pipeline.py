from __future__ import annotations
import hashlib
import re
import time
from collections import defaultdict
from contextlib import closing
from pathlib import Path
import pdfplumber
import pypdfium2 as pdfium
from . import __version__
from .common import digest_file, now, read_json, write_json, signature
from .ocr import LocalOCR


def clean_lines(text):
    """Remove only known decorative lines; never remove action/condition lines."""
    kept, removed = [], []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        if re.fullmatch(r'(大集中\s*ERP\s*项目|第\s*\d+\s*页\s*共\s*\d+\s*页)', line, re.I):
            removed.append(line)
        else:
            kept.append(line)
    return '\n'.join(kept), removed


def native_extract(cfg, names=None, all_sources=False):
    inv = read_json(Path(cfg['data_dir']) / 'inventory.json')
    wanted = names or [p['name'] for p in cfg['pilot']]
    count = 0
    for item in inv['documents']:
        if (not all_sources and item['name'] not in wanted) or item['status'] != 'ok':
            continue
        target = Path(cfg['data_dir']) / 'native' / (item['source_id'] + '.json')
        cached = read_json(target) if target.exists() else {}
        if cached.get('sha256') == item['sha256'] and cached.get('cleaner_version') == 2:
            count += item['pages']
            continue
        pages = []
        with closing(pdfium.PdfDocument(item['path'])) as doc:
            for n in range(len(doc)):
                page = doc[n]
                tp = page.get_textpage()
                raw = tp.get_text_range()
                text, removed = clean_lines(raw)
                pages.append(dict(page=n+1, raw_text=raw, text=text, removed_lines=removed))
                tp.close()
                page.close()
        write_json(target, {**item, 'extracted_at': now(), 'cleaner_version': 2, 'pages_data': pages})
        count += len(pages)
    return {'native_pages': count, 'scope':'all_sources' if all_sources else 'pilot_sources'}


def normalize_box(image, width, height):
    box = [max(0, float(image['x0'])), max(0, float(image['top'])),
           min(width, float(image['x1'])), min(height, float(image['bottom']))]
    if box[2] <= box[0] or box[3] <= box[1]:
        return None
    return box


def process(cfg, manifest_path=None, limit=None, force=False, report_path=None):
    root = Path(cfg['data_dir'])
    report_path = Path(report_path) if report_path else root / 'reports' / 'processing-latest.json'
    manifest = read_json(manifest_path or root / 'pilot-manifest.json')
    if limit is not None and limit < 1:
        raise ValueError('limit must be a positive number of pending pages')
    tasks = manifest['pages']
    run_sig = signature({'config': cfg['ocr'], 'version': __version__, 'format': 4})
    groups = defaultdict(list)
    for item in tasks:
        groups[item['path']].append(item)
    engine = None
    report = dict(started_at=now(), completed=0, skipped=0, failed=[], run_signature=run_sig)
    for path, rows in groups.items():
        if limit is not None and report['completed'] + len(report['failed']) >= limit:
            break
        # Validate actual content once per file; stale inventory must never reuse old evidence.
        if digest_file(path) != rows[0]['sha256']:
            raise ValueError(f'Source changed; rerun scan and plan: {Path(path).name}')
        with closing(pdfium.PdfDocument(path)) as doc, pdfplumber.open(path) as layout:
            for task in rows:
                number = task['page']
                output = root / 'parsed' / task['source_id'] / f'p{number:04}.json'
                if output.exists() and not force:
                    old = read_json(output)
                    if old.get('status') == 'complete' and old.get('run_signature') == run_sig:
                        report['skipped'] += 1
                        continue
                if limit is not None and report['completed'] + len(report['failed']) >= limit:
                    break
                started = time.perf_counter()
                page = doc[number-1]
                lp = layout.pages[number-1]
                try:
                    raw = lp.extract_text(x_tolerance=2, y_tolerance=3) or ''
                    text, removed = clean_lines(raw)
                    scale = cfg['ocr']['render_scale']
                    bitmap = page.render(scale=scale)
                    rendered = bitmap.to_pil().copy()
                    bitmap.close()
                    assets = root / 'assets' / task['source_id']
                    assets.mkdir(parents=True, exist_ok=True)
                    page_asset = assets / f'p{number:04}.png'
                    rendered.save(page_asset)
                    boxes = []
                    excluded = []
                    for img in lp.images:
                        box = normalize_box(img, float(lp.width), float(lp.height))
                        if box is None:
                            continue
                        obj_sha = hashlib.sha256(img['stream'].get_data()).hexdigest()
                        if obj_sha in cfg['ocr'].get('ignored_image_sha256', []):
                            excluded.append({'bbox':box,'image_sha256':obj_sha,'reason':'reviewed_decoration','needs_review':False})
                            continue
                        w, h = box[2]-box[0], box[3]-box[1]
                        if w < cfg['ocr']['image_min_width_pt'] or h < cfg['ocr']['image_min_height_pt']:
                            excluded.append({'bbox':box, 'reason':'small_image_candidate_not_indexed', 'needs_review':True})
                        elif not any(all(abs(a-b)<2 for a,b in zip(box, other)) for other in boxes):
                            boxes.append(box)
                    # Scan-only pages include full page. Small native headers do not suppress OCR.
                    if len(text) < 40 and not boxes:
                        boxes = [[0, 0, float(lp.width), float(lp.height)]]
                    image_records = []
                    for i, box in enumerate(boxes):
                        crop = rendered.crop(tuple(round(x*scale) for x in box))
                        region_id = signature([round(x,2) for x in box])[:8]
                        image_path = assets / f'p{number:04}-img-{region_id}.png'
                        crop.save(image_path)
                        sha = hashlib.sha256(crop.tobytes()).hexdigest()
                        cache_key = signature({'sha':sha,'ocr_engine':'rapidocr-1.4.4','size':crop.size})
                        cache = root / 'ocr-cache' / f'{cache_key}.json'
                        if cache.exists():
                            lines = read_json(cache)['lines']
                        else:
                            if engine is None:
                                engine = LocalOCR(cfg['ocr']['cpu_threads'])
                            lines = engine.read(crop)
                            write_json(cache, {'lines':lines,'engine':'rapidocr-onnxruntime-1.4.4','created_at':now()})
                        image_records.append(dict(image_id=f"{task['source_id']}-p{number:04}-{region_id}",
                                                  path=image_path.relative_to(root).as_posix(), bbox=box,
                                                  lines=lines, text='\n'.join(x['text'] for x in lines),
                                                  low_confidence_count=sum(x['score'] < cfg['ocr']['min_score'] for x in lines),
                                                  role='screenshot_candidate', relation_status='needs_review'))
                    table_data = []
                    try:
                        for tab in lp.find_tables():
                            table_data.append({'bbox': list(tab.bbox), 'rows':tab.extract(), 'status':'needs_visual_review'})
                    except Exception as exc:
                        table_data = [{'status':'failed', 'error':type(exc).__name__}]
                    value = dict(**task, status='complete', run_signature=run_sig, created_at=now(),
                                 native_text=raw, cleaned_text=text, excluded_lines=removed,
                                 page_asset=page_asset.relative_to(root).as_posix(), images=image_records,
                                 excluded_image_candidates=excluded, tables=table_data,
                                 seconds=round(time.perf_counter()-started,3),
                                 review_flags=['screenshot_action_relations_unverified'] if image_records else [])
                    write_json(output, value)
                    report['completed'] += 1
                    print(f"[{report['completed']+report['skipped']}/{len(tasks)}] {task['name']} p{number}: {len(text)} native chars, {len(image_records)} images, {value['seconds']}s", flush=True)
                except Exception as exc:
                    err = dict(source_id=task['source_id'], page=number, error=type(exc).__name__+': '+str(exc))
                    write_json(output, {**err,'status':'failed','run_signature':run_sig})
                    report['failed'].append(err)
                    print(f"ERROR page {number}: {type(exc).__name__}", flush=True)
                finally:
                    page.close()
                    lp.close()
                    write_json(report_path, report)
    report['finished_at'] = now()
    write_json(report_path, report)
    return report
