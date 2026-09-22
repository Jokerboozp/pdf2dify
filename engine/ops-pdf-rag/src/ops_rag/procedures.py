"""Extract cross-page source packets. They remain drafts until screenshot relations are verified."""
import re
from pathlib import Path
from .common import read_json, write_json, now

HEADING = re.compile(r'(?m)^\s*(\d+(?:\.\d+){2,4})\s+([^\n]+)')


def make_packets(cfg):
    root=Path(cfg['data_dir'])
    doc=next(read_json(p) for p in (root/'native').glob('*.json') if read_json(p)['name']=='0.财务月结操作手册.pdf')
    starts=[]
    full=''
    page_spans=[]
    for page in doc['pages_data']:
        start=len(full)
        full+=page['text']+'\n'
        page_spans.append((start,len(full),page['page']))
    matches=list(HEADING.finditer(full))
    packets=[]
    for i,m in enumerate(matches):
        if m.group(1) not in {'1.5.2','1.5.3','1.5.4','1.5.5','1.5.6','1.5.7'}:
            continue
        end=matches[i+1].start() if i+1<len(matches) else len(full)
        spans=[dict(page=p,text=full[max(a,m.start()):min(b,end)].strip()) for a,b,p in page_spans if a<end and b>m.start()]
        cid='procedure-'+doc['source_id'][:8]+'-'+m.group(1).replace('.','-')
        images=[]
        for s in spans:
            parsed=root/'parsed'/doc['source_id']/f"p{s['page']:04}.json"
            if parsed.exists():
                images.extend(read_json(parsed).get('images',[]))
        packet=dict(packet_id=cid,title=m.group(2),source_id=doc['source_id'],filename=doc['name'],
                    pages=[s['page'] for s in spans], source_spans=spans, images=images,
                    status='draft',business_review='pending',
                    warning='跨页正文已合并；截图中的字段与动作尚需复核，不能当作完整操作直接导入。',created_at=now())
        dest=root/'procedure-packets'
        write_json(dest/(cid+'.json'),packet)
        text=f"# {packet['title']}\n\n{packet['warning']}\n\n"
        text+='\n\n'.join(f"## PDF 第 {s['page']} 页\n\n{s['text']}" for s in spans)
        (dest/(cid+'.md')).write_text(text,encoding='utf-8')
        packets.append(dict(packet_id=cid,title=packet['title'],pages=packet['pages']))
    write_json(root/'procedure-packets'/'manifest.json',{'packets':packets})
    return {'cross_page_packets':len(packets),'packets':packets}
