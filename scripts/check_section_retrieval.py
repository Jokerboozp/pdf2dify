"""Live regression: common system terms must not displace a selected section."""
import json,sys
from pathlib import Path
from ops_rag.common import config,read_json
from ops_rag.full_sync import connect,retrieval_model
sys.stdout.reconfigure(encoding='utf-8')
cfg=config();cl=connect(cfg);state=read_json(Path(cfg['data_dir'])/'dify/full-state.json')
source='f44c1c7f7813c41f'
section='4.4.1.操作步骤：01系统录入油气田单元基本信息'
model=retrieval_model()
base=[{'name':'source_id','comparison_operator':'contains','value':source},{'name':'validity_status','comparison_operator':'is not','value':'retired'}]
checks=[]
for scoped in (False,True):
 model['metadata_filtering_conditions']={'logical_operator':'and','conditions':base+([{'name':'section_title','comparison_operator':'is','value':section}] if scoped else [])}
 r=cl.call('POST',f"datasets/{state['datasets']['master_ops']['id']}/retrieve",timeout=90,json={'query':'油气田单元 系统录入基本信息 字段录入 操作步骤 MDG','retrieval_model':model})
 names=[x['segment']['document']['name'] for x in r.get('records',[])]
 checks.append({'section_filter':scoped,'has_required_body':any('master_ops-024' in n for n in names),'documents':names})
print(json.dumps(checks,ensure_ascii=False,indent=2))
assert checks[1]['has_required_body'], 'Selected step body missing'
assert all('master_ops-024' in n for n in checks[1]['documents']), 'Other steps leaked into selected operation'
