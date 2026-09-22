"""Regression: detail retrieval must respect the manual's condition branch."""
from pathlib import Path
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect, retrieval_model


if __name__ == '__main__':
    cfg=config(); root=Path(cfg['data_dir']); client=connect(cfg)
    state=read_json(root/'dify/full-state.json')
    source='0e18bf85322fcdb5'
    manifest=read_json(root/'full-export/manifest.json')['documents']
    cases=[]
    for condition,prefix,required in [('上市','1.1.','ZP0FIADG0033_Y5'),('未上市','1.2.','KSU5'),('','',None)]:
        allowed={Path(d['path']).name for d in manifest if d['source_id']==source and prefix in d['metadata']['section_title']}
        model=retrieval_model()
        model['top_k']=20 if prefix else 6
        model['metadata_filtering_conditions']={'logical_operator':'and','conditions':[
            {'name':'source_id','comparison_operator':'contains','value':source},
            {'name':'section_title','comparison_operator':'contains','value':prefix},
            {'name':'validity_status','comparison_operator':'is not','value':'retired'}]}
        response=client.call('POST',f"datasets/{state['datasets']['finance']['id']}/retrieve",timeout=180,
            json={'query':f'制造费用分摊 {condition} 成本中心组维护 接收方科目维护 凭证清单 分摊执行','retrieval_model':model})
        records=response.get('records',[])
        names={r['segment']['document']['name'] for r in records}
        text='\n'.join(r['segment']['content'] for r in records)
        passed=bool(records) and names.issubset(allowed) and (not required or required in text)
        if condition=='上市': passed=passed and names==allowed and 'KSU5' not in text
        cases.append({'condition':condition or 'unspecified','prefix':prefix,'documents':sorted(names),'passed':passed})
    report={'checked_at':now(),'scope':'Source and section filter verification; UI verifies selector and answer','cases':cases,'passed':all(c['passed'] for c in cases)}
    write_json(root/'reports/finance-branch-retrieval.json',report)
    print(report)
    if not report['passed']: raise SystemExit(1)
