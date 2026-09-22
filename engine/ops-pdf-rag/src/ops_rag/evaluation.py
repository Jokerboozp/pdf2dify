import os
from pathlib import Path
import yaml
from .cards import load_cards
from .common import read_json, write_json, now
from .retrieval import rank_cards
from .dify import DifyClient


def evaluate(cfg, mode='local'):
    root=Path(cfg['data_dir'])
    cases=yaml.safe_load((Path(cfg['project_root'])/'evaluation'/'cases.yaml').read_text(encoding='utf-8'))['cases']
    exported=read_json(root/'export'/'manifest.json')['included']
    cards=[c for c in load_cards(cfg) if c['card_id'] in exported]
    client=None
    if mode=='dify':
        client=DifyClient(os.getenv('DIFY_BASE_URL',''),os.getenv('DIFY_DATASET_API_KEY',''))
        if not os.getenv('DIFY_DATASET_ID'):
            raise ValueError('DIFY_DATASET_ID is required')
    rows=[]
    for case in cases:
        cid,split,kind,page,query,checklist=case
        row=dict(id=cid,split=split,kind=kind,query=query,source_page=page,checklist=checklist)
        if kind!='answer':
            row['status']='pending_end_to_end_or_expanded_knowledge'
            rows.append(row)
            continue
        expected=next(c['card_id'] for c in cards if any(s['page']==page for s in c['sources']))
        if client:
            result=client.call('POST',f"datasets/{os.environ['DIFY_DATASET_ID']}/retrieve",json={'query':query})
            texts=[x.get('segment',{}).get('content','') for x in result.get('records',[])]
            row['retrieval']=result
            row['hit_at_5']=any(expected in t for t in texts[:5])
            row['hit_at_1']=bool(texts and expected in texts[0])
        else:
            hits=rank_cards(cards,query,5)
            row['retrieval']=hits
            row['hit_at_5']=any(x['card_id']==expected for x in hits)
            row['hit_at_1']=bool(hits and hits[0]['card_id']==expected)
        row.update(expected_card_id=expected,status='retrieval_measured',answer_quality='not_measured')
        rows.append(row)
    scored=[r for r in rows if r['status']=='retrieval_measured']
    summary=dict(created_at=now(),engine='offline_lexical_bm25' if mode=='local' else 'dify_retrieval_api',
                 total_cases=len(rows),scored_retrieval_cases=len(scored),pending_cases=len(rows)-len(scored),
                 hit_at_1=sum(r['hit_at_1'] for r in scored)/len(scored) if scored else None,
                 hit_at_5=sum(r['hit_at_5'] for r in scored)/len(scored) if scored else None,
                 limitations='Retrieval hit rate only, not answer correctness, not production acceptance.',
                 gold_review='pending_business_owner')
    for split in ['dev','holdout']:
        group=[r for r in scored if r['split']==split]
        summary[split]={'count':len(group),'hit_at_5':sum(r['hit_at_5'] for r in group)/len(group) if group else None}
    write_json(root/'reports'/f'evaluation-{mode}.json',{'summary':summary,'cases':rows})
    return summary
