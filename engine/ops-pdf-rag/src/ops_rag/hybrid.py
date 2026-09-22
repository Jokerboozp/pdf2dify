"""Local, source-preserving BM25 + dense retrieval + cross-encoder reranking."""
from __future__ import annotations

from collections import Counter, defaultdict
import math
import os
from pathlib import Path
import sqlite3
import time
import uuid

import numpy as np

from .common import now, read_json, signature, write_json
from .retrieval import tokens

VERSION = 1
DEFAULTS = {
    'embedding_model': 'BAAI/bge-small-zh-v1.5',
    'rerank_model': 'BAAI/bge-reranker-base',
    'threads': 3, 'batch_size': 8, 'window_chars': 300, 'overlap_chars': 60,
    'recall_k': 60, 'rerank_k': 24, 'rrf_k': 60,
}


def settings(cfg):
    return {**DEFAULTS, **cfg.get('local_retrieval', {})}


def models(cfg, rerank=False, download=False):
    # Inference is explicitly CPU-only, and normal operation never downloads.
    os.environ['HF_HUB_DISABLE_TELEMETRY'] = '1'
    os.environ['HF_HUB_DISABLE_SYMLINKS_WARNING'] = '1'
    from fastembed import TextEmbedding
    from fastembed.rerank.cross_encoder import TextCrossEncoder
    opts = settings(cfg)
    cls = TextCrossEncoder if rerank else TextEmbedding
    return cls(model_name=opts['rerank_model' if rerank else 'embedding_model'],
               cache_dir=str(Path(cfg['data_dir']) / 'models'), threads=opts['threads'],
               providers=['CPUExecutionProvider'], local_files_only=not download)


def input_fingerprint(root):
    return signature([read_json(root / 'full-export/manifest.json')['documents'],
                      read_json(root / 'process-navigation/catalog.json')['records']])


def load_documents(cfg):
    """The current export manifest, NOT historic upload receipts, is authoritative."""
    from .corpus import region_text
    root = Path(cfg['data_dir'])
    catalogue = read_json(root / 'process-navigation/catalog.json')['records']
    nav = {r['source_id']: r for r in catalogue}
    sources, result = {}, []
    for item in read_json(root / 'full-export/manifest.json')['documents']:
        if item['metadata'].get('validity_status') == 'retired':
            continue
        sid = item['source_id']
        if sid not in sources:
            source = read_json(root / 'corpus' / (sid + '.json'))
            sources[sid] = (source['source'], {c['chunk_id']: c for c in source['chunks']})
        source, chunks = sources[sid]
        text, images = [], []
        for cid in item['chunk_ids']:
            chunk = chunks[cid]  # Fail on incomplete conversion, never silently skip it.
            text.extend([chunk['title'], *chunk.get('notes', [])])
            for region in chunk['regions']:
                text.append(region_text(source, region))
                images.extend({'path': im['path'], 'page': region['page'], 'image_id': im['image_id']}
                              for im in region['images'])
        record = nav.get(sid, {})
        title = item['metadata']['section_title']
        result.append({
            'id': item['key'], 'kind': 'detail', 'title': title,
            'source_id': sid, 'source_name': item['source_name'], 'domains': [item['domain']],
            'pages': item['pages'], 'metadata': item['metadata'],
            'topic': record.get('filename_topic', record.get('title', item['source_name'])),
            'content': '\n\n'.join(text), 'images': images,
        })
    for r in catalogue:
        text = ['流程名称：' + r['title'], '原文名称别称：' + '；'.join(r['aliases']),
                '资料主题：' + r['filename_topic'], '原文目录：']
        text.extend(f"{x['title']}（PDF 第 {','.join(map(str,x['pages']))} 页）" for x in r['outline'])
        text.extend(f"PDF 第 {e['page']} 页：\n{e['text']}\n" + '\n'.join(e.get('table_rows', []))
                    for e in r['overview_evidence'])
        result.append({'id': 'nav-' + r['key'], 'kind': 'overview', 'title': r['title'],
                       'topic': r['filename_topic'], 'source_id': r['source_id'],
                       'source_name': r['source_name'], 'domains': r['domains'],
                       'pages': sorted({p for x in r['outline'] for p in x['pages']}),
                       'metadata': {'process_key': r['key'], 'section_title': r['title'],
                                    'validity_status': 'unconfirmed'},
                       'content': '\n'.join(text), 'images': r.get('images', [])})
    return result


def passages(documents, opts):
    size, overlap = opts['window_chars'], opts['overlap_chars']
    if not 0 <= overlap < size <= 350:
        raise ValueError('Require 0 <= overlap_chars < window_chars <= 350')
    result = []
    for di, doc in enumerate(documents):
        # Repeat the true business/condition heading in each child; do not infer aliases/steps.
        prefix = f"{doc['topic'][:65]} / {doc['title'][:85]}\n"
        body = doc['content']
        for offset in range(0, max(len(body), 1), size-overlap):
            text = prefix + body[offset:offset+size]
            result.append({'doc': di, 'offset': offset, 'text': text})
            if offset+size >= len(body):
                break
    return result


def build_index(cfg, embedder=None, progress=None):
    """Resume embeddings by content hash; publish an immutable, complete snapshot."""
    opts = settings(cfg)
    root = Path(cfg['data_dir'])
    folder = root / 'local-index'
    folder.mkdir(parents=True, exist_ok=True)
    fingerprint = input_fingerprint(root)
    docs = load_documents(cfg)
    document_fingerprint = signature(docs)
    current_path = folder / 'current.json'
    if current_path.exists():
        current = read_json(current_path)
        if (current.get('version') == VERSION and current.get('settings') == opts
                and current.get('input_fingerprint') == fingerprint
                and current.get('document_fingerprint') == document_fingerprint):
            return {**current, 'embedded': 0, 'reused': current['passages'], 'unchanged': True}
    rows = passages(docs, opts)
    model_key = signature({'version': VERSION, 'model': opts['embedding_model']})
    hashes = [signature([model_key, row['text']]) for row in rows]
    cache = sqlite3.connect(folder / 'embedding-cache.sqlite3')
    try:
        cache.execute('CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, dim INTEGER NOT NULL, value BLOB NOT NULL)')
        existing = {k for k, in cache.execute('SELECT key FROM vectors')}
        missing = list(dict.fromkeys(h for h in hashes if h not in existing))
        lookup = {h: row['text'] for h, row in zip(hashes, rows)}
        if missing:
            encoder = embedder if embedder is not None else models(cfg)
            for start in range(0, len(missing), opts['batch_size']):
                batch = missing[start:start+opts['batch_size']]
                vectors = list(encoder.embed([lookup[h] for h in batch], batch_size=opts['batch_size']))
                if len(vectors) != len(batch):
                    raise ValueError('Embedding count mismatch')
                for h, vector in zip(batch, vectors):
                    value = np.asarray(vector, dtype=np.float32)
                    if value.ndim != 1 or not np.isfinite(value).all() or np.linalg.norm(value) == 0:
                        raise ValueError('Invalid embedding')
                    cache.execute('INSERT OR REPLACE INTO vectors VALUES (?, ?, ?)', (h, len(value), value.tobytes()))
                cache.commit()
                if progress and (start % (opts['batch_size']*25) == 0 or start+len(batch) == len(missing)):
                    progress({'embedded': start+len(batch), 'pending_total': len(missing), 'passages': len(rows)})
        vectors = []
        for h in hashes:
            dim, blob = cache.execute('SELECT dim, value FROM vectors WHERE key=?', (h,)).fetchone()
            vector = np.frombuffer(blob, dtype=np.float32)
            if len(vector) != dim:
                raise ValueError('Corrupt cached vector')
            vectors.append(vector)
        matrix = np.stack(vectors)
        matrix /= np.linalg.norm(matrix, axis=1, keepdims=True)
        snapshot = uuid.uuid4().hex
        dest = folder / snapshot
        dest.mkdir()
        np.save(dest / 'vectors.npy', matrix, allow_pickle=False)
        if input_fingerprint(root) != fingerprint:
            raise ValueError('Source manifest changed during indexing; rerun to publish consistently')
        info = {'version': VERSION, 'created_at': now(), 'snapshot': snapshot,
                'settings': opts, 'input_fingerprint': fingerprint,
                'document_fingerprint': document_fingerprint,
                'source_count': len({d['source_id'] for d in docs}), 'documents': len(docs),
                'passages': len(rows), 'dimension': matrix.shape[1],
                'embedded': len(missing), 'reused': len(rows)-len(missing)}
        write_json(dest / 'corpus.json', {'info': info, 'documents': docs, 'passages': rows})
        write_json(folder / 'current.json', info)
        return info
    finally:
        cache.close()


class BM25:
    def __init__(self, texts):
        counts = [Counter(tokens(t)) for t in texts]
        self.size = len(counts)
        lengths = np.array([sum(c.values()) for c in counts], dtype=np.float32)
        average = float(lengths.mean()) if len(lengths) else 1
        postings = defaultdict(list)
        for i, counts_i in enumerate(counts):
            for token, count in counts_i.items():
                postings[token].append((i, count))
        self.postings = {}
        for token, entries in postings.items():
            ids = np.array([i for i, _ in entries])
            freq = np.array([f for _, f in entries])
            idf = math.log(1+(self.size-len(ids)+.5)/(len(ids)+.5))
            weights = idf*freq*2.2/(freq+1.2*(.25+.75*lengths[ids]/max(average, 1)))
            self.postings[token] = ids, weights

    def scores(self, query):
        scores = np.zeros(self.size, dtype=np.float32)
        for token in set(tokens(query)):
            if token in self.postings:
                ids, weights = self.postings[token]
                scores[ids] += weights
        return scores


def rrf(rankings, k=60):
    scores = defaultdict(float)
    for ranking in rankings:
        for rank, key in enumerate(ranking, 1):
            scores[key] += 1/(k+rank)
    return sorted(scores, key=lambda i: (-scores[i], i)), scores


def rerank_candidates(ordered, lexical, semantic, limit):
    # A semantic-only top hit can have lower RRF than dozens of weak dual hits.
    # Reserve leading candidates from BOTH channels before applying the budget.
    reserved = set(list(lexical)[:3] + list(semantic)[:3])
    return ([i for i in ordered if i in reserved] + [i for i in ordered if i not in reserved])[:limit]


class HybridSearch:
    def __init__(self, cfg, encoder=None, reranker=None, check_fresh=True):
        self.cfg, self.encoder, self.reranker = cfg, encoder, reranker
        root = Path(cfg['data_dir'])
        current = read_json(root / 'local-index/current.json')
        if current['version'] != VERSION or current['settings'] != settings(cfg):
            raise ValueError('Local index settings changed. Run ops-rag index.')
        if check_fresh and current['input_fingerprint'] != input_fingerprint(root):
            raise ValueError('Local index is stale. Run ops-rag index after PDF conversion.')
        folder = root / 'local-index' / current['snapshot']
        corpus = read_json(folder / 'corpus.json')
        self.info, self.docs, self.rows = current, corpus['documents'], corpus['passages']
        self.opts = current['settings']
        self.matrix = np.load(folder / 'vectors.npy', allow_pickle=False, mmap_mode='r')
        if self.matrix.shape != (len(self.rows), current['dimension']):
            raise ValueError('Local index vectors do not match passages')
        self.lexical = BM25([r['text'] for r in self.rows])

    def warm(self):
        if self.encoder is None: self.encoder = models(self.cfg)
        if self.reranker is None: self.reranker = models(self.cfg, rerank=True)

    def search(self, query, top_k=5, mode='hybrid', domains=None, source_id='', section_prefix='', kind=None):
        if mode not in ('bm25', 'vector', 'fusion', 'hybrid'):
            raise ValueError('Unknown search mode')
        if not query.strip() or len(query) > 1000 or not 1 <= top_k <= 20:
            raise ValueError('Require nonempty query <= 1000 characters, top_k 1..20')
        started = time.perf_counter()
        allowed = {i for i, d in enumerate(self.docs)
                   if (not domains or set(domains).intersection(d['domains']))
                   and (not source_id or d['source_id'] == source_id)
                   and (not kind or d['kind'] == kind)
                   and (not section_prefix or d['metadata'].get('section_title', '').startswith(section_prefix))}
        indices = np.array([i for i, r in enumerate(self.rows) if r['doc'] in allowed], dtype=np.int64)
        if not len(indices):
            return {'engine': mode, 'query': query, 'results': [], 'elapsed_ms': 0}
        recall_k = max(self.opts['recall_k'], top_k)
        lexical = self.lexical.scores(query)
        def ranked_parents(scores, positive=False):
            order = indices[np.argsort(-scores[indices], kind='stable')]
            output = {}
            for i in order:
                if positive and scores[i] <= 0: break
                di = self.rows[i]['doc']
                if di not in output: output[di] = int(i)
                if len(output) >= recall_k: break
            return output
        lex = ranked_parents(lexical, positive=True)
        dense, vec = None, {}
        if mode != 'bm25':
            if self.encoder is None: self.encoder = models(self.cfg)
            vector = np.asarray(next(iter(self.encoder.query_embed(query))), dtype=np.float32)
            if vector.shape != (self.matrix.shape[1],) or not np.isfinite(vector).all() or np.linalg.norm(vector) == 0:
                raise ValueError('Invalid query embedding')
            dense = self.matrix @ (vector/np.linalg.norm(vector))
            vec = ranked_parents(dense)
        if mode == 'bm25': ordered, fused = list(lex), {}
        elif mode == 'vector': ordered, fused = list(vec), {}
        else: ordered, fused = rrf([lex, vec], self.opts['rrf_k'])
        reranked = {}
        best_rows = {di: vec.get(di, lex.get(di)) for di in ordered}
        if mode == 'hybrid':
            if self.reranker is None: self.reranker = models(self.cfg, rerank=True)
            # Score both lexical and semantic evidence windows when they differ.
            candidates = rerank_candidates(ordered, lex, vec, max(top_k, self.opts['rerank_k']))
            pairs = [(di, i) for di in candidates for i in dict.fromkeys([v for v in (lex.get(di), vec.get(di)) if v is not None])]
            scores = list(self.reranker.rerank(query, [self.rows[i]['text'] for _, i in pairs], batch_size=2))
            if len(scores) != len(pairs) or not np.isfinite(scores).all():
                raise ValueError('Invalid reranker scores')
            for (di, i), score in zip(pairs, scores):
                if di not in reranked or score > reranked[di]:
                    reranked[di], best_rows[di] = float(score), i
            ordered = sorted(candidates, key=lambda di: (-reranked[di], -fused[di], di))
        results = []
        for di in ordered[:top_k]:
            doc, row = self.docs[di], self.rows[best_rows[di]]
            score = reranked.get(di, fused.get(di, float(lexical[best_rows[di]]) if mode == 'bm25' else float(dense[best_rows[di]])))
            results.append({**doc, 'score': float(score), 'matched_text': row['text'],
                            'scores': {'bm25': float(lexical[lex[di]]) if di in lex else None,
                                       'cosine': float(dense[vec[di]]) if di in vec else None,
                                       'rrf': fused.get(di), 'rerank_logit': reranked.get(di)}})
        return {'engine': mode, 'query': query, 'snapshot': self.info['snapshot'],
                'results': results, 'elapsed_ms': round((time.perf_counter()-started)*1000, 1)}
