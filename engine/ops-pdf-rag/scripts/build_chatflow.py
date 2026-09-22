from pathlib import Path
import argparse
import yaml

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser()
parser.add_argument('--dataset-id',required=True)
parser.add_argument('--model',default='deepseek-v4-flash')
args=parser.parse_args()

model={'provider':'langgenius/deepseek/deepseek','name':args.model,'mode':'chat',
       'completion_params':{'temperature':0.1}}

def node(id,type,title,x,y,**data):
    return {'id':id,'type':'custom','position':{'x':x,'y':y},'positionAbsolute':{'x':x,'y':y},
            'width':244,'height':100,'sourcePosition':'right','targetPosition':'left',
            'data':{'type':type,'title':title,'desc':'','selected':False,**data}}

def edge(source,target,source_type,target_type,handle='source'):
    return {'id':f'{source}-{handle}-{target}','source':source,'target':target,'sourceHandle':handle,
            'targetHandle':'target','type':'custom','data':{'sourceType':source_type,'targetType':target_type,'isInIteration':False,'isInLoop':False}}

nodes=[
    node('start','start','用户问题',0,200,variables=[]),
    node('normalize','llm','理解问题与识别歧义',300,200,model=model,
         prompt_template=[{'id':'normalize-system','role':'system','text':(root/'prompts/normalize.txt').read_text(encoding='utf-8')},
                          {'id':'normalize-user','role':'user','text':'请执行问题整理任务：结合前文补全下面真实问题的指代，仅输出结构化字段，不回答业务操作。\n本轮问题：{{#sys.query#}}'}],
         context={'enabled':False,'variable_selector':[]},vision={'enabled':False},
         structured_output_enabled=True,
         structured_output={'schema':{'type':'object','additionalProperties':False,
             'properties':{'query':{'type':'string'},'needs_clarification':{'type':'string','enum':['yes','no']},'clarification':{'type':'string'}},
             'required':['query','needs_clarification','clarification']}},
         memory={'window':{'enabled':True,'size':6},'role_prefix':{'user':'用户','assistant':'助手'},'query_prompt_template':'请结合历史对话补全本轮问题，仅输出实际的 query、needs_clarification、clarification。\n本轮问题：{{#sys.query#}}'}),
    node('route','if-else','是否需要澄清',900,200,cases=[{'id':'true','case_id':'true','logical_operator':'and',
         'conditions':[{'id':'clarify-condition','variable_selector':['normalize','structured_output','needs_clarification'],
                        'comparison_operator':'is','value':'yes','varType':'string'}]}]),
    node('clarify','answer','追问关键条件',1200,0,answer='{{#normalize.structured_output.clarification#}}',variables=[]),
    node('retrieve','knowledge-retrieval','检索试点知识',1200,300,dataset_ids=[args.dataset_id],
         query_variable_selector=['normalize','structured_output','query'],retrieval_mode='multiple',
         multiple_retrieval_config={'top_k':5,'score_threshold':None,'reranking_mode':'weighted_score',
                                   'reranking_enable':False,'weights':{'weight_type':'customized',
                                   'vector_setting':{'vector_weight':0.7,'embedding_provider_name':'langgenius/ollama/ollama','embedding_model_name':'nomic-embed-text:latest'},
                                   'keyword_setting':{'keyword_weight':0.3}}},
         metadata_filtering_mode='disabled'),
    node('grounded','llm','按证据回答并引用来源',1500,300,model=model,
         prompt_template=[{'id':'answer-system','role':'system','text':(root/'prompts/answer.txt').read_text(encoding='utf-8')},
                          {'id':'answer-user','role':'user','text':'用户本轮问题：{{#sys.query#}}\n补全后的检索问题：{{#normalize.structured_output.query#}}'}],
         context={'enabled':True,'variable_selector':['retrieve','result']},vision={'enabled':False}),
    node('answer','answer','返回运维回答',1800,300,answer='{{#grounded.text#}}',variables=[])
]
edges=[edge('start','normalize','start','llm'),edge('normalize','route','llm','if-else'),
       edge('route','clarify','if-else','answer','true'),
       edge('route','retrieve','if-else','knowledge-retrieval','false'),
       edge('retrieve','grounded','knowledge-retrieval','llm'),edge('grounded','answer','llm','answer')]
dsl={'version':'0.7.0','kind':'app','app':{'name':'ERP运维问答-清洗试点','description':'本地PDF清洗试点。44条问答，含澄清分支、来源页码和资料不足处理。未经生产业务验收。',
      'mode':'advanced-chat','icon':'📘','icon_type':'emoji','icon_background':'#E0F2FE','use_icon_as_answer_icon':False},
     'dependencies':[], 'workflow':{'conversation_variables':[],'environment_variables':[],
     'features':{'opening_statement':'请说明具体业务对象、想完成的操作或报错信息。我会依据试点手册回答，并标明来源页码。',
                 'suggested_questions':['凭证冲销原因01和02的日期怎么填？','以前期间的会计凭证怎么修改？','维修工单结转后怎么取消？'],
                 'suggested_questions_after_answer':{'enabled':False},'retriever_resource':{'enabled':True},
                 'file_upload':{'enabled':False},'speech_to_text':{'enabled':False},'text_to_speech':{'enabled':False},
                 'sensitive_word_avoidance':{'enabled':False}},
     'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':30,'y':50,'zoom':0.6}}}}
target=root/'dify'/'chatflow-pilot.yml'
target.parent.mkdir(parents=True,exist_ok=True)
target.write_text(yaml.safe_dump(dsl,allow_unicode=True,sort_keys=False),encoding='utf-8')
print(target)
