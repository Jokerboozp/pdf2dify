"""Audit provenance and DOCX transport contents; never labels business approval."""
import json
import zipfile
from pathlib import Path
from collections import Counter
from xml.etree import ElementTree as ET
from ops_rag.common import read_json, write_json, now, digest_file
from ops_rag.corpus import VERSION

ROOT=Path(__file__).resolve().parents[1]/'data'


def verify():
    manifest=read_json(ROOT/'full-export/manifest.json')
    inventory=read_json(ROOT/'inventory.json')['documents']
    errors=[]; notes=[]; counts=Counter(); covered_sources=set()
    docs={d['source_id']:d for d in inventory}
    for sid in sorted({d['source_id'] for d in manifest['documents']}):
        corpus=read_json(ROOT/'corpus'/f'{sid}.json')
        if corpus['version'] != VERSION: errors.append({'source_id':sid,'error':'stale_builder_version'})
        if corpus['source']['sha256'] != docs[sid]['sha256']: errors.append({'source_id':sid,'error':'stale_source'})
        if digest_file(docs[sid]['path']) != docs[sid]['sha256']: errors.append({'source_id':sid,'error':'source_changed_on_disk'})
        covered={r['page'] for c in corpus['chunks'] for r in c['regions']}
        missing=sorted(set(range(1,docs[sid]['pages']+1))-covered)
        if missing: notes.append({'source_id':sid,'empty_or_uncovered_pages':missing})
        counts['covered_pages']+=len(covered); covered_sources.add(sid)
        for chunk in corpus['chunks']:
            counts['parent_chunks']+=1
            images=[im for r in chunk['regions'] for im in r['images']]
            if len(images)>10: errors.append({'chunk_id':chunk['chunk_id'],'error':'too_many_images'})
            for im in images:
                p=ROOT/im['path']
                if not p.exists(): errors.append({'chunk_id':chunk['chunk_id'],'error':'missing_image'})
                elif p.stat().st_size>=2*1024*1024: errors.append({'chunk_id':chunk['chunk_id'],'error':'oversized_image'})
            counts['image_references']+=len(images)
            counts['low_confidence_ocr_lines']+=sum(im.get('low_confidence_count',0) for im in images)
    for item in manifest['documents']:
        path=Path(item['path'])
        if path.stat().st_size>15*1024*1024: errors.append({'key':item['key'],'error':'oversized_docx'})
        with zipfile.ZipFile(path) as z:
            tree=ET.fromstring(z.read('word/document.xml'))
            text=''.join(tree.itertext())
            embeds=tree.findall('.//{http://schemas.openxmlformats.org/drawingml/2006/main}blip')
            if len(embeds)!=item['image_count']: errors.append({'key':item['key'],'error':'docx_image_count_mismatch'})
            if item['source_name'] not in text: errors.append({'key':item['key'],'error':'missing_source_name'})
        counts['docx_documents']+=1
    report={'checked_at':now(),'counts':dict(counts),'sources':len(covered_sources),'total_sources':len(inventory),
            'pending_sources':sorted(set(docs)-covered_sources),'errors':errors,'notes':notes,
            'business_review':'pending','interpretation':'Technical provenance checks only; not business accuracy approval.'}
    write_json(ROOT/'reports/full-corpus-verification.json',report)
    print(json.dumps({**report,'pending_sources':len(report['pending_sources'])},ensure_ascii=False,indent=2))
    if errors: raise SystemExit(1)


if __name__=='__main__': verify()
