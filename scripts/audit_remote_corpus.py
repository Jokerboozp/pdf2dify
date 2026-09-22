"""Read every current evidence parent from Dify and verify provenance and media.

This checks transport/index integrity, not OCR transcription or business approval.
"""
import json
import re
import sys
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from ops_rag.common import config,read_json,write_json,now,signature
from ops_rag.full_sync import connect
from ops_rag.search_anchors import anchor_text


def metadata(doc):
    value=doc.get('doc_metadata') or {}
    return value if isinstance(value,dict) else {v['name']:v.get('value') for v in value}


def main():
    cfg=config(); root=Path(cfg['data_dir']); client=connect(cfg)
    manifest=read_json(root/'full-export/manifest.json'); state=read_json(root/'dify/full-state.json')
    receipts=read_json(root/'dify/search-anchors.json')['documents']
    remote={d['id']:d for ds in state['datasets'].values() for d in client.documents(ds['id'])}
    report={'started_at':now(),'scope':'all current parents, source metadata, page references, image references and search children',
            'counts':{},'errors':[],'retired_verified':0}
    current_keys={x['key'] for x in manifest['documents']}
    for key,receipt in state['documents'].items():
        if key in current_keys: continue
        doc=remote.get(receipt['document_id'])
        if not doc or metadata(doc).get('validity_status')!='retired': report['errors'].append({'key':key,'error':'obsolete_not_retired'})
        else: report['retired_verified']+=1
    counts=Counter()

    def one(item):
        receipt=state['documents'][item['key']]; doc=remote[receipt['document_id']]; errors=[]
        if receipt['hash']!=item['content_hash'] or doc['indexing_status']!='completed' or not doc['enabled']:
            errors.append('current_content_not_ready')
        for key,value in item['metadata'].items():
            if metadata(doc).get(key)!=value: errors.append('metadata_mismatch:'+key)
        base='datasets/'+receipt['dataset_id']+'/documents/'+receipt['document_id']
        parents=client.call('GET',base+'/segments',params={'limit':100})['data']
        if len(parents)!=1: return {'key':item['key'],'errors':errors+['expected_one_full_parent'],'images':0,'anchor':0}
        parent=parents[0]; content=parent['content']
        if item['source_name'] not in content: errors.append('missing_source_filename')
        for p in item['pages']:
            if f'PDF 第{p}页' not in content: errors.append('missing_page:'+str(p))
        images=re.findall(r'!\[[^\]]*\]\(([^)]+)\)',content)
        if len(images)!=item['image_count']: errors.append('image_count:'+str(len(images))+'/'+str(item['image_count']))
        if any('/files/' not in u or 'file-preview' not in u for u in images): errors.append('unexpected_image_link')
        text=anchor_text(item); matched=0
        if text:
            anchor=receipts.get(item['key'],{})
            children=client.call('GET',base+'/segments/'+parent['id']+'/child_chunks',params={'limit':100})['data']
            matches=[c for c in children if c['id']==anchor.get('child_id') and c['content']==text]
            if len(matches)!=1: errors.append('missing_current_search_child')
            else: matched=1
        return {'key':item['key'],'errors':errors,'images':len(images),'anchor':matched}

    with ThreadPoolExecutor(max_workers=4) as pool:
        jobs={pool.submit(one,item):item['key'] for item in manifest['documents']}
        for future in as_completed(jobs):
            try:
                row=future.result();counts['parents_checked']+=1;counts['image_references']+=row['images'];counts['anchors_verified']+=row['anchor']
                if row['errors']: report['errors'].append(row)
            except Exception as exc:
                report['errors'].append({'key':jobs[future],'error':str(exc)})
            report['counts']=dict(counts);report['checked_at']=now()
            if counts['parents_checked']%100==0:
                write_json(root/'reports/remote-corpus-audit.json',report)
                print(json.dumps({'counts':dict(counts),'errors':len(report['errors'])}),flush=True)
    report['finished_at']=now();report['passed']=not report['errors'] and counts['parents_checked']==len(manifest['documents'])
    write_json(root/'reports/remote-corpus-audit.json',report)
    print(json.dumps({k:v for k,v in report.items() if k!='errors'}),flush=True)
    if not report['passed']: raise SystemExit(1)


if __name__=='__main__':
    sys.stdout.reconfigure(encoding='utf-8',errors='replace')
    main()
