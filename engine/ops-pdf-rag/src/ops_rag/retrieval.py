"""Offline lexical baseline only; never report this as Dify vector/Rerank accuracy."""
import math
import re
from collections import Counter
from .cards import load_cards


def tokens(text):
    out = re.findall(r'[a-z0-9]+(?:[_-][a-z0-9]+)*', text.lower())
    for run in re.findall(r'[\u4e00-\u9fff]+', text):
        out.extend(run[i:i+2] for i in range(len(run)-1))
        if len(run) == 1:
            out.append(run)
    return out


def rank_cards(cards, query, top_k=5):
    texts = [c['question']+' '+c['question']+' '+c.get('cause','')+' '+c['answer'] for c in cards]
    counts = [Counter(tokens(t)) for t in texts]
    n = len(counts)
    if not n:
        return []
    avg = sum(sum(c.values()) for c in counts)/n or 1
    df = Counter(t for c in counts for t in c)
    results = []
    for card, c in zip(cards, counts):
        score = 0.0
        for t in set(tokens(query)):
            f = c[t]
            if f:
                score += math.log(1+(n-df[t]+0.5)/(df[t]+0.5))*f*2.2/(f+1.2*(.25+.75*sum(c.values())/avg))
        if score:
            results.append(dict(card_id=card['card_id'],title=card['title'],score=round(score,5),
                                sources=[{k:s[k] for k in ['filename','page','source_id']} for s in card['sources']]))
    return sorted(results,key=lambda x:x['score'],reverse=True)[:top_k]


def search(cfg, query, top_k=5):
    return {'engine':'offline_bm25_chinese_bigrams','query':query,'results':rank_cards(load_cards(cfg),query,top_k)}
