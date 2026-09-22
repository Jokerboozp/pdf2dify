import csv
from pathlib import Path
from ops_rag.common import read_json, write_json, now
from ops_rag.corpus import classify, DOMAINS, metadata

root=Path(__file__).resolve().parents[1]/'data'
rows=[]
for doc in read_json(root/'inventory.json')['documents']:
    domain=classify(doc)
    rows.append({'source_id':doc['source_id'],'filename':doc['name'],'relative_path':doc['relative_path'],
        'pages':doc['pages'],'primary_domain':domain,'primary_domain_name':DOMAINS[domain],
        'classification_basis':'source_directory_or_document_subject',
        'mixed_document':doc['name']=='财务模块常见问题.pdf','review_status':'pending',
        'document_version':metadata(doc,domain)['document_version']})
write_json(root/'source-classification.json',{'created_at':now(),'sources':rows})
with (root/'source-classification.csv').open('w',encoding='utf-8-sig',newline='') as f:
    writer=csv.DictWriter(f,fieldnames=list(rows[0]));writer.writeheader();writer.writerows(rows)
print(f'Classified {len(rows)} source documents; mixed FAQ is routed at section level.')
