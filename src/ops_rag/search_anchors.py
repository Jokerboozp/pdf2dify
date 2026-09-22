"""Add concise, source-derived search children while keeping full evidence parents."""
import re
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from functools import lru_cache
from .common import read_json, write_json, now, signature
from .full_sync import connect


@lru_cache(maxsize=300)
def _condition_contexts(path, modified_ns):
    headings={}; result={}
    for chunk in read_json(path)['chunks']:
        title=chunk['title'].strip()
        match=re.match(r'^(\d+(?:\.\d+)*)(?:[.、\s]|(?=[^\d.]))',title)
        if not match: continue
        parts=tuple(match[1].split('.'))
        candidates=[headings[parts[:n]] for n in range(1,len(parts)) if parts[:n] in headings]
        # These conditions change the business procedure. Copy them from actual
        # ancestor headings, never from neighboring pages or inferred SAP rules.
        candidates=[v for v in candidates if re.search('上市|未上市|内部|外部|内修|外修',v)]
        if candidates: result[chunk['chunk_id']]=candidates[-1]
        headings[parts]=title
    return result


def native_operation_labels(item):
    """Read short native headings/codes from this parent, never neighboring pages or OCR."""
    if not item.get('path') or not item.get('chunk_ids'):
        return []
    path = Path(item['path']).parents[2] / 'corpus' / f"{item['source_id']}.json"
    if not path.exists():
        return []
    labels = []
    for chunk in read_json(path)['chunks']:
        if chunk['chunk_id'] not in item['chunk_ids']:
            continue
        for region in chunk['regions']:
            lines = [s.strip(' •\t') for s in region['text'].splitlines()]
            lines = [s for s in lines if s and not re.fullmatch(r'[\d\W]+', s)]
            if not lines or re.sub(r'\s+', '', lines[0]) == '目录':
                continue
            for line in lines[:4]:
                if line in ('设备管理主数据', '业务流程操作'):
                    continue
                if not 3 <= len(line) <= 40 or re.search('[，。；]', line):
                    continue
                is_code = bool(re.match(r'^(创建|查询|事务码|事物码)[：:]', line) and re.search(r'[A-Za-z]+\d', line))
                is_heading = line.endswith(('主数据', '主数据查询', '批量导入'))
                if (is_code or is_heading) and line not in labels:
                    labels.append(line)
    return labels


def anchor_text(item):
    title = item['metadata']['section_title'].strip()
    if title in ('目录', '资料说明与适用范围', '谢谢', '感谢聆听', '结束语'):
        return None
    if item.get('path') and item.get('chunk_ids'):
        corpus_path=Path(item['path']).parents[2]/'corpus'/f"{item['source_id']}.json"
        if corpus_path.exists():
            contexts=_condition_contexts(str(corpus_path),corpus_path.stat().st_mtime_ns)
            context=contexts.get(item['chunk_ids'][0])
            if context and context not in title:
                title=context+' / '+title
    topic = Path(item['source_name']).stem
    topic = re.sub(r'^.*?MDG\.[\d.]+[-_\s]*', '', topic)
    topic = re.sub(r'[_\s]*V\d[\d.]*.*$', '', topic, flags=re.I)
    topic = re.sub(r'^\d+[.、\s]*', '', topic)
    topic = re.sub(r'[_\s]+', ' ', topic).strip()
    if item.get('domain') == 'equipment' and title == '设备管理主数据':
        labels = native_operation_labels(item)
        if labels:
            return '检索主题：' + '；'.join(labels) + '。资料主题：' + topic + '。'
    if item.get('domain') == 'equipment' and (title.startswith('事务码') or title == '业务流程操作') and item.get('path'):
        # Slide PDFs sometimes expose only a transaction-code line as a native
        # heading. Recover search labels from that SAME evidence parent's native
        # headings and screenshot window titles; these labels are not new steps.
        corpus_path=Path(item['path']).parents[2]/'corpus'/f"{item['source_id']}.json"
        if corpus_path.exists():
            chunks=read_json(corpus_path)['chunks']; labels=[]
            for chunk in chunks:
                if chunk['chunk_id'] not in item['chunk_ids']: continue
                for region in chunk['regions']:
                    for line in region['text'].splitlines():
                        line=line.strip(' •\t')
                        if 4<=len(line)<=35 and line!='业务流程操作' and not line.startswith('事务码') and not re.fullmatch(r'[\d\W]+',line):
                            if line not in labels: labels.append(line)
                    for im in region['images']:
                        for line in im.get('lines',[])[:8]:
                            value=line['text'].strip()
                            if 4<=len(value)<=20 and re.match(r'^(创建|修改|显示|查询|维护|申请|审批|工单管理)',value) and line.get('score',0)>=.9:
                                if value not in labels: labels.append(value)
            if labels:
                return '；'.join(labels[:8])+'。'+title+'。'+topic+'。'
    if item.get('domain') == 'funds' and '常见问题' not in topic:
        # Funds booklets often use generic headings such as "付款功能". The
        # source filename carries the payment type and responsible role.
        return topic + '。' + title + '。'
    # FAQ question titles already identify the question precisely. Adding the
    # generic PDF name would weaken the short child's signal.
    text = '检索主题：' + title + '。'
    if '常见问题' not in topic and title not in topic and topic not in title:
        text += '资料主题：' + topic + '。'
    return text


def ensure_child(client, endpoint, text):
    def find_matches():
        page = 1; found = []
        while True:
            children = client.call('GET', endpoint, params={'page':page,'limit':100})
            found.extend(x for x in children['data'] if x['content']==text)
            if page >= children.get('total_pages', 1): break
            page += 1
        if len(found)>1: raise ValueError('Duplicate search anchor children')
        return found

    def refresh(child):
        # A prior create can commit successfully and still return an error on
        # lock release. PATCH safely refreshes that same child's vector index.
        return client.call('PATCH', endpoint+'/'+child['id'], timeout=180, json={'content':text})['data']

    matches = find_matches()
    if matches: return refresh(matches[0])
    try:
        return client.call('POST', endpoint, timeout=180, json={'content':text})['data']
    except Exception:
        # Never repeat an uncertain create. Reconcile the exact server content.
        matches = find_matches()
        if not matches: raise
        return refresh(matches[0])


def enrich(cfg, workers=2, limit=None):
    if not 1 <= workers <= 4: raise ValueError('workers must be 1..4')
    root = Path(cfg['data_dir']); client = connect(cfg)
    state = read_json(root/'dify/full-state.json')
    if state['base_url'] != os.getenv('DIFY_BASE_URL'):
        raise ValueError('Wrong server for source receipts')
    manifest = read_json(root/'full-export/manifest.json')
    path = root/'dify/search-anchors.json'
    receipts = read_json(path) if path.exists() else {'documents': {}}
    if receipts.get('base_url', state['base_url']) != state['base_url']:
        raise ValueError('Wrong server for anchor receipts')
    receipts['base_url'] = state['base_url']
    wanted = []
    for item in manifest['documents']:
        text = anchor_text(item); remote = state['documents'].get(item['key'])
        if not text or not remote or remote.get('hash') != item['content_hash'] or not remote.get('metadata_applied'):
            continue
        fingerprint = signature({'parent_hash': item['content_hash'], 'text': text})
        old = receipts['documents'].get(item['key'], {})
        if old.get('fingerprint') == fingerprint and old.get('document_id') == remote['document_id']:
            continue
        wanted.append((item, remote, text, fingerprint))
    domains = {item['domain'] for item, _, _, _ in wanted}
    available = set()
    for domain in domains:
        available.update(d['id'] for d in client.documents(state['datasets'][domain]['id'])
                         if d['indexing_status']=='completed' and d.get('enabled'))
    jobs = [job for job in wanted if job[1]['document_id'] in available]
    waiting = len(wanted)-len(jobs)
    if limit is not None: jobs = jobs[:limit]
    lock = Lock()

    def one(job):
        item, remote, text, fingerprint = job
        ds = remote['dataset_id']; doc = remote['document_id']
        parents = client.call('GET', f'datasets/{ds}/documents/{doc}/segments')['data']
        if len(parents) != 1:
            raise ValueError('Expected exactly one full evidence parent: '+item['key'])
        parent = parents[0]['id']
        endpoint = f'datasets/{ds}/documents/{doc}/segments/{parent}/child_chunks'
        old = receipts['documents'].get(item['key'], {})
        if old.get('parent_id') == parent and old.get('document_id') == doc and old.get('child_id'):
            child = client.call('PATCH', endpoint+'/'+old['child_id'], timeout=180, json={'content':text})['data']
        else:
            child = ensure_child(client, endpoint, text)
        with lock:
            receipts['documents'][item['key']] = {'document_id':doc,'parent_id':parent,'child_id':child['id'],
                'fingerprint':fingerprint,'text':text,'updated_at':now()}
            write_json(path, receipts)
        return item['key']

    errors = []; done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        for start in range(0,len(jobs),20):
            futures = {pool.submit(one,job): job[0]['key'] for job in jobs[start:start+20]}
            for future in as_completed(futures):
                try: future.result(); done += 1
                except Exception as exc: errors.append({'key':futures[future],'error':str(exc)})
            print(f'Anchors completed this run: {done}; failures: {len(errors)}',flush=True)
            if errors: break
    result = {'checked_at':now(),'added_or_reconciled':done,'tracked':len(receipts['documents']),
              'waiting_for_index':waiting,'ready_remaining':len(wanted)-waiting-done,'errors':errors}
    write_json(root/'reports/search-anchors.json',result)
    if errors: raise RuntimeError('Search anchor errors; see data/reports/search-anchors.json')
    return result
