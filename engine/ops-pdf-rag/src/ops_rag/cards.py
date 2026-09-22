from __future__ import annotations
import re
from pathlib import Path
from .common import read_json, write_json, now, signature

LABEL = re.compile(r'(问题描述|问题原因|解决办法)\s*[：:]')
HEADERS = re.compile(r'(核算|资金|司库|内部交易)常见问题')


def faq_fields(text):
    """Explicit labels delimit fields regardless of PDF's object order."""
    text = HEADERS.sub('', text)
    fields = {}
    matches = list(LABEL.finditer(text))
    for i, match in enumerate(matches):
        value = text[match.end():matches[i+1].start() if i+1 < len(matches) else len(text)]
        # PDF soft line breaks inside sentences should not change code characters.
        value = re.sub(r'(?<![。；;：:])\n(?!\s*\d+[、.])', '', value).strip()
        fields[match.group(1)] = value
    return fields


def validate_card(card):
    issues = []
    if not card.get('question') or not card.get('answer'):
        issues.append('missing_question_or_answer')
    if not card.get('sources'):
        issues.append('missing_sources')
    for field in ('question','answer','cause'):
        value = card.get(field, '')
        if value and not any(value in faq_fields(s['evidence_text']).get(
                {'question':'问题描述','answer':'解决办法','cause':'问题原因'}[field], '')
                for s in card.get('sources', [])):
            # Multi-source cards preserve individual answers as branches, validated separately.
            if not (field == 'answer' and card.get('branches') and all(
                b['answer'] == faq_fields(b['evidence_text']).get('解决办法') for b in card['branches'])):
                issues.append(f'{field}_not_extractively_grounded')
    return issues


def markdown(card, asset_base=''):
    out = [f"# {card['title']}", '', f"卡片ID：{card['card_id']}",
           f"模块：{card['module']}", '资料适用版本：待业务确认',
           '用途：试点验证；不是已通过业务验收的操作规程。', '',
           '## 用户问题', card['question']]
    if card.get('cause'):
        out += ['', '## 原文原因', card['cause']]
    out += ['', '## 原文处理说明', card['answer']]
    if card['review_flags']:
        out += ['', '## 资料边界', '本条存在需核对内容：' + '；'.join(card['review_flags'])]
    out += ['', '## 来源']
    for s in card['sources']:
        out.append(f"- {s['filename']}，PDF 第 {s['page']} 页；source_id={s['source_id']}")
    if card.get('images') and asset_base:
        out += ['', '## 配图']
        for im in card['images']:
            if asset_base:
                out.append(f"- [{im['image_id']}]({asset_base.rstrip('/')}/{im['path'].removeprefix('assets/')})")
            else:
                out.append(f"- 截图编号：{im['image_id']}（内网图片服务待配置）")
    return '\n'.join(out) + '\n'


def build_cards(cfg):
    root = Path(cfg['data_dir'])
    docs = [read_json(p) for p in (root/'native').glob('*.json')]
    docs = [x for x in docs if x['name'] == '财务模块常见问题.pdf']
    if len(docs) != 1:
        raise ValueError('Run native extraction first; expected exactly one finance FAQ source.')
    doc = docs[0]
    cards = []
    by_question = {}
    for page in doc['pages_data']:
        text = page['text']
        fields = faq_fields(text)
        if not fields.get('问题描述') or not fields.get('解决办法'):
            continue
        p = page['page']
        module = next((m for m in ['内部交易','司库','资金','核算'] if m+'常见问题' in text), '财务')
        source = dict(source_id=doc['source_id'], sha256=doc['sha256'], filename=doc['name'],
                      page=p, evidence_text=text)
        flags = []
        if any(x in fields['解决办法'] for x in ['下方操作','以下图','功能为：']):
            flags.append('处理说明依赖截图，文字不足以还原全部操作')
        if 'ZP0FIADG001C' in text:
            flags.append('原文事务码ZP0FIADG001C与其他页写法不一致，未自动更正')
        parsed_path = root/'parsed'/doc['source_id']/f'p{p:04}.json'
        parsed = read_json(parsed_path) if parsed_path.exists() else {}
        images = [{k:im[k] for k in ['image_id','path']} for im in parsed.get('images', [])]
        question = fields['问题描述']
        if question in by_question:
            card = by_question[question]
            if not card.get('branches'):
                card['branches'] = [dict(answer=card['answer'], evidence_text=card['sources'][0]['evidence_text'], page=card['sources'][0]['page'])]
            card['branches'].append(dict(answer=fields['解决办法'],evidence_text=text,page=p))
            card['answer'] = '\n\n'.join(f"原文第 {b['page']} 页的情形：\n{b['answer']}" for b in card['branches'])
            card['sources'].append(source)
            card['images'].extend(images)
            card['review_flags'] = list(dict.fromkeys(card['review_flags'] + flags + ['同一问题有不同业务情形，回答前须确认适用条件']))
            continue
        card = dict(card_id=f"faq-{doc['source_id'][:8]}-p{p:03}", title=f'{module}—{question}',
                    module=module, question=question, cause=fields.get('问题原因',''), answer=fields['解决办法'],
                    sources=[source], images=images, review_flags=flags, status='draft',
                    business_review='pending', created_at=now(), method='extractive-labelled-fields',
                    source_scope='original_text_only; OCR evidence kept separately')
        cards.append(card)
        by_question[question] = card
    card_dir = root/'cards'
    card_dir.mkdir(parents=True, exist_ok=True)
    import os
    for card in cards:
        card['validation_issues'] = validate_card(card)
        card['content_hash'] = signature({k:card[k] for k in ['question','answer','cause','sources','review_flags']})
        write_json(card_dir/(card['card_id']+'.json'), card)
        (card_dir/(card['card_id']+'.md')).write_text(markdown(card, os.getenv('ASSET_BASE_URL','')), encoding='utf-8')
    # Manifest is the authority: stale files are not silently reimported.
    result = dict(created_at=now(), count=len(cards), card_ids=[x['card_id'] for x in cards],
                  validation_errors=sum(bool(x['validation_issues']) for x in cards),
                  business_review='pending')
    write_json(root/'cards-manifest.json', result)
    return result


def load_cards(cfg):
    root = Path(cfg['data_dir'])
    manifest = read_json(root/'cards-manifest.json')
    return [read_json(root/'cards'/(cid+'.json')) for cid in manifest['card_ids']]
