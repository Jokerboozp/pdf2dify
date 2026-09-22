from __future__ import annotations
import os
import re
from pathlib import Path
import httpx
from .cards import load_cards, markdown
from .common import now, read_json, write_json, signature

SEPARATOR = '<OPS_CARD_BOUNDARY>'


def export(cfg, include_drafts=False):
    root = Path(cfg['data_dir'])
    all_cards = load_cards(cfg)
    cards = [c for c in all_cards if not c['validation_issues'] and not c['review_flags']
             and (include_drafts or c['business_review'] == 'approved')]
    out = root/'export'
    out.mkdir(parents=True, exist_ok=True)
    texts = [markdown(c, os.getenv('ASSET_BASE_URL','')) for c in cards]
    if any(SEPARATOR in t for t in texts):
        raise ValueError('Reserved delimiter occurs inside source content')
    bundle = out/'ERP运维问答-清洗试点.txt'
    bundle.write_text(('\n'+SEPARATOR+'\n').join(texts), encoding='utf-8')
    manifest = dict(created_at=now(), usage='pilot_only' if include_drafts else 'approved_only',
                    separator=SEPARATOR, count=len(cards), included=[c['card_id'] for c in cards],
                    excluded=[{'card_id':c['card_id'],'review_flags':c['review_flags'],
                               'business_review':c['business_review'],'validation_issues':c['validation_issues']}
                              for c in all_cards if c not in cards],
                    max_card_chars=max(map(len,texts),default=0), bundle_path=str(bundle))
    write_json(out/'manifest.json',manifest)
    return manifest


class DifyClient:
    def __init__(self, base, key, transport=None):
        if not key:
            raise ValueError('Set DIFY_DATASET_API_KEY in local .env; do not paste it in chat.')
        self.client = httpx.Client(base_url=base.rstrip('/')+'/',
                                   headers={'Authorization':'Bearer '+key},
                                   timeout=60, follow_redirects=False, transport=transport)

    def call(self, method, path, **kwargs):
        response = self.client.request(method,path.lstrip('/'),**kwargs)
        if response.status_code >= 400:
            # Do not print request headers, credentials, or service bodies with private content.
            raise RuntimeError(f'Dify API failed: HTTP {response.status_code} at {path}')
        return response.json()

    def documents(self, dataset):
        result, page = [], 1
        while True:
            batch = self.call('GET',f'datasets/{dataset}/documents',params={'page':page,'limit':100})
            result.extend(batch.get('data',[]))
            if not batch.get('has_more'):
                return result
            page += 1


def document_payload(card, text):
    if len(text) > 3500:
        raise ValueError('Card exceeds safe segment size; split by business subprocedure first.')
    return dict(name=f"ops-rag--{card['card_id']}",text=text,indexing_technique='high_quality',
                doc_form='text_model',doc_language='Chinese Simplified',
                process_rule={'mode':'custom','rules':{
                    'pre_processing_rules':[{'id':'remove_extra_spaces','enabled':False},
                                            {'id':'remove_urls_emails','enabled':False}],
                    'segmentation':{'separator':SEPARATOR,'max_tokens':4000,'chunk_overlap':0}}})


def sync(cfg, apply=False):
    root = Path(cfg['data_dir'])
    exp = read_json(root/'export'/'manifest.json')
    selected = [c for c in load_cards(cfg) if c['card_id'] in exp['included']]
    dataset = os.getenv('DIFY_DATASET_ID','')
    base = os.getenv('DIFY_BASE_URL','')
    plan = dict(target=base, dataset_id=dataset, document_count=len(selected),
                usage=exp['usage'], apply=apply,
                note='GENERAL mode; use a separate dataset for per-card API sync, not the UI bundle dataset.')
    if not apply:
        return plan
    if not dataset or not base:
        raise ValueError('Set DIFY_BASE_URL and DIFY_DATASET_ID in .env first.')
    client = DifyClient(base,os.getenv('DIFY_DATASET_API_KEY',''))
    existing = client.documents(dataset)
    if any(d.get('name', '').startswith('ERP运维问答-清洗试点.txt') for d in existing):
        raise ValueError('This dataset already contains the UI pilot bundle. Select a separate GENERAL dataset for per-card API sync to avoid duplicate evidence.')
    names = {}
    for doc in existing:
        names.setdefault(doc['name'],[]).append(doc)
    state_path = root/'dify'/f'{dataset}-sync.json'
    state = read_json(state_path) if state_path.exists() else {'documents':{}}
    if state.get('base_url') and state['base_url'] != base:
        raise ValueError('Sync state belongs to another Dify server.')
    state['base_url'] = base
    for card in selected:
        text = markdown(card,os.getenv('ASSET_BASE_URL',''))
        payload = document_payload(card,text)
        hash_value = signature(payload)
        old = state['documents'].get(card['card_id'],{})
        matches = names.get(payload['name'],[])
        if len(matches) > 1:
            raise ValueError('Duplicate remote names require reconciliation: '+payload['name'])
        doc_id = matches[0]['id'] if matches else None
        if doc_id and old.get('hash') == hash_value and old.get('document_id') == doc_id:
            continue
        endpoint = f'datasets/{dataset}/documents/{doc_id}/update-by-text' if doc_id else f'datasets/{dataset}/document/create-by-text'
        # Never retry POST automatically; interrupted runs first reconcile by unique name.
        response = client.call('POST',endpoint,json=payload)
        state['documents'][card['card_id']] = dict(document_id=response['document']['id'],
                                                 hash=hash_value,batch=response.get('batch'),
                                                 status='submitted_not_indexing_verified',updated_at=now())
        write_json(state_path,state)
    return {**plan,'submitted_state':str(state_path),'note':'Submission is not indexing completion; inspect Dify status before use.'}
