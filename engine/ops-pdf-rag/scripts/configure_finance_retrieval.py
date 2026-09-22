"""Align the dataset candidate pool with bounded condition retrieval in Dify 1.17.1."""
import os
from copy import deepcopy
from pathlib import Path
from ops_rag.common import config, read_json, write_json, now
from ops_rag.full_sync import connect


if __name__=='__main__':
    cfg=config(); client=connect(cfg); root=Path(cfg['data_dir'])
    state=read_json(root/'dify/full-state.json')
    if state['base_url'] != os.getenv('DIFY_BASE_URL'): raise ValueError('Wrong server')
    ds=state['datasets']['finance']['id']
    before=client.call('GET',f'datasets/{ds}')['retrieval_model_dict']
    report=root/'reports/finance-retrieval-settings.json'
    if not report.exists(): write_json(report,{'created_at':now(),'dataset_id':ds,'before':before})
    if before['top_k']!=20:
        updated=deepcopy(before); updated['top_k']=20
        if not updated.get('reranking_enable'): updated.pop('reranking_model',None)
        client.call('PATCH',f'datasets/{ds}',json={'retrieval_model':updated})
    after=client.call('GET',f'datasets/{ds}')['retrieval_model_dict']
    if after['top_k']!=20: raise ValueError('Dataset candidate limit did not persist')
    result=read_json(report); result.update(checked_at=now(),after=after)
    write_json(report,result)
    print({'dataset_id':ds,'candidate_top_k':after['top_k'],'ordinary_node_top_k':6,'scoped_node_top_k':20})
