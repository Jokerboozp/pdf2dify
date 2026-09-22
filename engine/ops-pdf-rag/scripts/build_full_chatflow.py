"""Build explicit bounded retrieval branches, compatible with the working pilot."""
from pathlib import Path
import argparse
import json
import re
from copy import deepcopy
import yaml
from ops_rag.corpus import DOMAINS
from ops_rag.process_catalog import selection_catalog
from ops_rag.search_anchors import native_operation_labels

ROOT = Path(__file__).resolve().parents[1]
ROUTES = {k: [k] for k in DOMAINS}
ROUTES.update({'projects_finance': ['projects', 'finance'], 'equipment_finance': ['equipment', 'finance'],
               'procurement_master': ['procurement', 'master_ops'], 'internal_funds': ['internal', 'funds'],
               'finance_funds': ['finance', 'funds']})


def node(nid, typ, title, x, y, **data):
    return {'id': nid, 'type': 'custom', 'position': {'x': x, 'y': y}, 'positionAbsolute': {'x': x, 'y': y},
            'width': 244, 'height': 100, 'sourcePosition': 'right', 'targetPosition': 'left',
            'data': {'type': typ, 'title': title, 'desc': '', 'selected': False, **data}}


def edge(source, target, st, tt, handle='source'):
    return {'id': f'{source}-{handle}-{target}', 'source': source, 'target': target, 'sourceHandle': handle,
            'targetHandle': 'target', 'type': 'custom', 'data': {'sourceType': st, 'targetType': tt, 'isInIteration': False, 'isInLoop': False}}


def finance_scopes(records):
    """Copy actual numbered condition headings; never infer procedure branches."""
    result = []
    for record in records:
        if 'finance' not in record['domains']: continue
        for entry in record['outline']:
            match = re.match(r'^(\d+(?:\.\d+)*)(?:[.、\s]|(?=[^\d.]))', entry['title'])
            if not match or not re.search('上市|内部|外部|内修|外修', entry['title']): continue
            prefix = match[1] + '.'
            children = [e for e in record['outline'] if e['title'].startswith(prefix)]
            if children:
                result.append({'source_id':record['source_id'], 'source_name':record['source_name'],
                               'prefix':prefix, 'title':entry['title']})
    return result


def build(dataset_ids):
    if set(dataset_ids) != set(DOMAINS): raise ValueError('All nine dataset mappings are required')
    navigation = ROOT/'data/process-navigation'
    process_records = json.loads((navigation/'catalog.json').read_text(encoding='utf-8'))['records']
    process_state = json.loads((navigation/'dify/full-state.json').read_text(encoding='utf-8'))
    process_dataset = process_state['datasets']['process_navigation']['id']
    master_topics = sorted({r['filename_topic'] for r in process_records if r['domains'] == ['master_ops']})
    route_prompt = (ROOT/'prompts/route-full.txt').read_text(encoding='utf-8')
    route_prompt += ('\n以下是当前主数据操作手册的真实主题。问题涉及这些主数据对象的维护/创建/审批等操作时，'
                     '优先 master_ops，不能仅因“油气田、设备、会计科目、项目”等词误选其他业务库；'
                     '数据标准/编码规则仍按 master_rules，概览仍走 overview。\n'+'；'.join(master_topics))
    evidence_manifest=json.loads((ROOT/'data/full-export/manifest.json').read_text(encoding='utf-8'))['documents']
    equipment_topics = sorted({label for d in evidence_manifest if d['domain'] == 'equipment'
                              and d['metadata']['section_title'] == '设备管理主数据'
                              for label in native_operation_labels(d)
                              if not re.match(r'^(创建|查询|事务码|事物码)[：:]', label)})
    route_prompt += ('\n以下是设备管理库操作正文中的真实章节对象：'+'；'.join(equipment_topics)+
                     '。询问这些对象的创建、查询、批量导入等具体操作时，选 equipment、detail。'
                     '这些对象位于设备管理操作手册内，不需要存在同名整本手册。不能仅因“主数据”三字选 master_ops；'
                     '若用户明确要求 MDG 的创建审批，则按 MDG 资料定位，不把两种入口混用。')
    faq_titles=sorted({d['metadata']['section_title'] for d in evidence_manifest if '常见问题' in d['source_name']
                       and d['metadata']['section_title'] not in ('资料说明与适用范围','财务模块常见问题')})
    route_prompt += ('\n以下是已经入库的原文常见问题标题。仅当用户的业务对象、动作、报错及适用条件与某标题一致时，'
        'search_query直接照抄该完整标题（不拆为零散关键词、不增加猜测事务码）；query仍保留用户本轮真实意图。'
        '例如“项目结转后怎么撤销”对应原文“项目结转后如何取消结转”，这属于同义定位。'
        '不一致、无匹配或缺少关键条件时不要强行套用标题。\n'+'\n'.join(faq_titles))
    model = {'provider': 'langgenius/deepseek/deepseek', 'name': 'deepseek-v4-flash', 'mode': 'chat', 'completion_params': {'temperature': .1}}
    schema = {'type': 'object', 'additionalProperties': False,
              'properties': {'query': {'type': 'string'}, 'search_query': {'type':'string'}, 'answer_mode': {'type':'string','enum':['overview','detail']}, 'route': {'type': 'string', 'enum': list(ROUTES)+['clarify']}, 'clarification': {'type': 'string'}},
              'required': ['query', 'search_query', 'answer_mode', 'route', 'clarification']}
    nodes = [node('start', 'start', '用户提问', 0, 500, variables=[]),
        node('normalize', 'llm', '理解问题并选择业务范围', 300, 500, model=model,
             prompt_template=[{'id':'route-system','role':'system','text':route_prompt},
                              {'id':'route-user','role':'user','text':'本轮真实问题：{{#sys.query#}}'}],
             context={'enabled':False,'variable_selector':[]}, vision={'enabled':False},
             structured_output_enabled=True, structured_output={'schema':schema},
             memory={'window':{'enabled':True,'size':6},'role_prefix':{'user':'用户','assistant':'助手'},
                     'query_prompt_template':'请结合历史对话整理本轮真实问题，只输出结构化分类结果。\n本轮问题：{{#sys.query#}}'}),
        node('route', 'if-else', '选择主题库或跨模块组合', 650, 500, cases=[{
            'id':key,'case_id':key,'logical_operator':'and','conditions':[{'id':key+'-condition',
            'variable_selector':['normalize','structured_output','route'],'comparison_operator':'is','value':key,'varType':'string'}]} for key in ROUTES]),
        node('clarify', 'answer', '追问业务对象', 1000, -180, answer='{{#normalize.structured_output.clarification#}}', variables=[])]
    nodes.extend([
        node('answer_mode','if-else','流程概览还是具体问题',580,-440,cases=[{'id':'overview','case_id':'overview','logical_operator':'and','conditions':[{
            'id':'overview-mode','variable_selector':['normalize','structured_output','answer_mode'],'comparison_operator':'is','value':'overview','varType':'string'}]}]),
        node('select_process','llm','按流程名和文件主题定位',900,-650,model=model,vision={'enabled':False},context={'enabled':False,'variable_selector':[]},
             prompt_template=[{'id':'process-selector','role':'system','text':
                 '根据真实资料目录选择用户所问流程/手册。只做定位，不回答步骤。文件主题比封面流程名更能区分分册。'
                 '例如多份分册封面都写“财务月结业务流程”，用户问整个财务月结时选文件主题为“财务月结操作手册”的总册；'
                 '用户问项目结转时选项目结转分册，不用总册冒充该分册。'
                 '允许忽略文件序号、空格和“流程/业务流程/操作手册”等称呼差异，保留上市/未上市、内外修和项目类型。'
                 '用户缺少区分候选的业务对象/条件，而且目录没有涵盖它们的通用总册时，必须留空process_key并追问，不能只凭相同动作选一个。'
                 '例如只问“预算调整流程”不能擅自当成日常经费预算：投资项目WBS预算调整与日常经费预算调整适用对象不同，应列出候选请用户选择。'
                 '没有封面名称也可按文件主题匹配，不需要用户知道模块。相同内容的重复副本选无(2)标记的一份；'
                 '不同版本、条件或多个对象同样匹配且影响解释时，process_key留空，clarification列出2至3个真实候选名称供选择。'
                 '目录无对应资料时process_key留空，说明未定位到该名称并请用户给出业务对象或手册名称；不能编造候选。'
                 'process_key只能照抄目录键。选定时clarification为空。\n目录：\n'+selection_catalog(process_records)},
                 {'id':'process-query','role':'user','text':'{{#normalize.structured_output.query#}}'}],
             structured_output_enabled=True,structured_output={'schema':{'type':'object','additionalProperties':False,
                 'properties':{'process_key':{'type':'string','enum':['']+[r['key'] for r in process_records]},'clarification':{'type':'string'}},
                 'required':['process_key','clarification']}}),
        node('process_found','if-else','是否定位到流程资料',1220,-650,cases=[{'id':'found','case_id':'found','logical_operator':'and','conditions':[{
            'id':'process-selected','variable_selector':['select_process','structured_output','process_key'],'comparison_operator':'not empty','value':'','varType':'string'}]}]),
        node('process_clarify','answer','选择流程或分支',1500,-920,answer='{{#select_process.structured_output.clarification#}}',variables=[]),
        node('retrieve_process','knowledge-retrieval','读取全书流程导航',1500,-650,dataset_ids=[process_dataset],
             query_variable_selector=['normalize','structured_output','search_query'],retrieval_mode='multiple',
             multiple_retrieval_config={'top_k':1,'score_threshold':None,'reranking_mode':'weighted_score','reranking_enable':False,
                 'weights':{'weight_type':'customized','vector_setting':{'vector_weight':.7,'embedding_provider_name':'langgenius/ollama/ollama','embedding_model_name':'nomic-embed-text:latest'},'keyword_setting':{'keyword_weight':.3}}},
             metadata_filtering_mode='manual',metadata_filtering_conditions={'logical_operator':'and','conditions':[
                 {'name':'process_key','comparison_operator':'is','value':'{{#select_process.structured_output.process_key#}}'},
                 {'name':'validity_status','comparison_operator':'is not','value':'retired'}]}),
        node('process_has_content','if-else','已定位资料是否读取成功',1790,-890,cases=[{'id':'content','case_id':'content','logical_operator':'and','conditions':[{
            'id':'overview-content','variable_selector':['retrieve_process','result'],'comparison_operator':'not empty','value':'','varType':'array[object]'}]}]),
        node('process_unavailable','answer','已定位资料暂不可读',2090,-1080,
             answer='已定位到对应资料，但本次未能读取其内容。请稍后重试，或补充想了解的具体环节以查询详细操作。',variables=[]),
        node('grounded_process','llm','回答流程概览并引导展开',1800,-650,model=model,vision={'enabled':False},
             context={'enabled':True,'variable_selector':['retrieve_process','result']},
             prompt_template=[{'id':'overview-system','role':'system','text':(ROOT/'prompts/process-overview.txt').read_text(encoding='utf-8')},
                 {'id':'overview-user','role':'user','text':'本轮问题：{{#sys.query#}}\n结合历史后的问题：{{#normalize.structured_output.query#}}'}]),
        node('answer_process','answer','返回流程概览',2110,-650,answer='{{#grounded_process.text#}}',variables=[])])
    edges = [edge('start','normalize','start','llm'), edge('normalize','answer_mode','llm','if-else'),
             edge('answer_mode','select_process','if-else','llm','overview'),edge('answer_mode','route','if-else','if-else','false'),
             edge('select_process','process_found','llm','if-else'),edge('process_found','process_clarify','if-else','answer','false'),
             edge('process_found','retrieve_process','if-else','knowledge-retrieval','found'),edge('retrieve_process','process_has_content','knowledge-retrieval','if-else'),
             edge('process_has_content','grounded_process','if-else','llm','content'),edge('process_has_content','process_unavailable','if-else','answer','false'),
             edge('grounded_process','answer_process','llm','answer'),edge('route','clarify','if-else','answer','false')]
    answer_prompt = (ROOT/'prompts/answer.txt').read_text(encoding='utf-8').replace('当前连接的是试点知识库', '当前连接的是按业务主题整理的运维知识库')
    answer_prompt += '\n15. 证据中的本地 OCR 文字可能有识别误差。事务码优先采用原文正文，不凭 OCR 改写事务码。标注“原文事务码存在疑点”的条目只能说明需要运维核对，不能给出确定操作指令。\n16. 父文档可能是长章节的一个部分；不要把标注续篇的局部步骤声称为全流程。回答全流程需要完整依据，否则明确说明当前只找到的步骤范围。\n17. 优先核对项目类型、组织和适用条件；投资、费用、数信、科技项目不能混用流程。标准与操作手册有冲突时分别说明来源，不能自行选择一个作为现行制度。'
    answer_prompt += '\n18. 操作步骤采用原文正文或截图讲解注释中明确要求的动作。截图讲解注释中完整的点击、输入、选择等动作句可以引用；截图只出现控件名、字段名、复选框标签或示例值，不代表原文要求操作它们；不得据此新增填写、勾选、测试运行、审批、提交等步骤。原文未要求测试运行或勾选明细清单时，不能自行补充这些建议。不要用一般ERP经验扩展原步骤。\n19. 直接面向业务用户回答，不解释检索路由、OCR引擎、复制图片链接等内部实现。配图标题只自然地说明内容、来源和页码，不为提供链接道歉。'
    answer_prompt += '\n20. 当前检索证据没有覆盖问题中的错误码、操作或条件时，回答“当前检索到的资料未提供该问题的处理依据”，不要断言整个知识库绝无相关资料。只简要说明缺少的依据和需要补充的关键信息；不要列举无关事务码、无关流程或附上无关图片。仅提供直接支持当前答案的配图，不为凑图展示相似业务图片。'
    answer_prompt += '\n21. 培训正文中的演示单位名称、编码、人员、日期和金额也属于示例，不只是截图数值。步骤写“输入目标组织名称/实际编码”，必要时括注原文示例；不要直接命令用户输入演示公司的名称或编号。精确查询、模糊查询、编码查询等是可选查询方式，应分别列出，不能把多个示例变成必须依次执行的步骤。'
    answer_prompt += '\n22. 用户说“第N部分、第二个、展开这一项”等时，指的是上一轮概览里的选项序号，不必等于原文的章节编号。整理后的问题已补全实际业务对象，应按补全后的对象和条件回答；不要因为原文没有同号章节就说没有依据，也不要把对话序号当成检索条件。'
    answer_prompt += '\n23. 从流程概览继续展开时，原手册已经入库；本次证据只覆盖部分操作，不代表整份手册缺失。先直接说明本次有依据的操作和范围，不要要求用户重新上传或补传已经存在的整本手册，也不要把资料中没有要求的检查、正式运行、审批等步骤预设为必然缺失的后续流程。需要继续细化时，询问用户关注的具体步骤或条件。'
    for i, (key, domains) in enumerate(ROUTES.items()):
        rid, lid, aid = 'retrieve_'+key, 'grounded_'+key, 'answer_'+key
        title = ' + '.join(DOMAINS[d] for d in domains)
        y = i * 220
        query_selector=['normalize','structured_output','search_query']
        filters=[{'name':'validity_status','comparison_operator':'is not','value':'retired'}]
        if 'equipment' in domains:
            filters.append({'name':'section_title','comparison_operator':'is not','value':'目录'})
        if key in ('master_ops','funds','finance'):
            inventory=json.loads((ROOT/'data/full-export/manifest.json').read_text(encoding='utf-8'))['documents']
            catalog={d['source_id']:d['source_name'] for d in inventory if d['domain']==key}
            selector_id='select_source_'+key
            selection_prompt=('根据手册目录选择与用户明确业务对象一致的一份资料。'
                '优先匹配业务对象，其次匹配创建/修改等动作；不能因为其他对象的动作相同就选错对象。'
                '即使用户请求的动作未在目录体现，也选择同一业务对象的管理手册，由回答节点核实是否支持。'
                '问题同时询问创建和查询时，优先选择标题同时覆盖这些动作的资料。'
                '具体报错、异常问题可以选择常见问题资料；不能确定对应来源时留空，不按目录猜测故障答案。'
                '只有多份同样相关且无法确定、明确需要跨手册或目录无对应对象时 source_id 为空字符串。'
                '必须照抄目录中的 source_id，不得编造；这里只选择资料，不回答操作。\n目录：\n'+
                '\n'.join(sid+' | '+title for sid,title in catalog.items()))
            selection_properties={'source_id':{'type':'string','enum':['']+list(catalog)}}
            if key == 'finance':
                scopes=finance_scopes(process_records)
                scope_text='\n'.join(s['source_id']+' | '+s['source_name']+' | '+s['prefix']+' | '+s['title'] for s in scopes)
                selection_prompt += ('\n以下为原书中改变适用条件的章节层级，格式：来源键 | 文件 | 子章节前缀 | 条件标题。'
                    '\n用户指定上市/未上市等条件时，优先选择专门分册，必须同时输出该来源对应的section_prefix；'
                    '不能因文件名同时写有两种条件就混检两个分支。上市不等于未上市。'
                    '原文上级条件适用于其编号下的子章节，子章节标题不必再次重复条件。'
                    '只可照抄本次所选来源对应的前缀。问题没有指定这些条件或所选来源没有适用分支时section_prefix为空。'
                    '查询整个财务月结可选总册；制造费用分摊具体操作优先制造费用分摊分册。'
                    '\n'+scope_text)
                selection_properties['section_prefix']={'type':'string','enum':['']+sorted({s['prefix'] for s in scopes})}
            nodes.append(node(selector_id,'llm','选择'+title+'对象资料',820,y,model=model,
                prompt_template=[{'id':'source-sys','role':'system','text':selection_prompt},
                                 {'id':'source-user','role':'user','text':'{{#normalize.structured_output.query#}}'}],
                context={'enabled':False,'variable_selector':[]},vision={'enabled':False},
                structured_output_enabled=True,structured_output={'schema':{'type':'object','additionalProperties':False,
                    'properties':selection_properties,'required':list(selection_properties)}}))
            filters.append({'name':'source_id','comparison_operator':'contains','value':'{{#'+selector_id+'.structured_output.source_id#}}'})
            if key == 'finance':
                filters.append({'name':'section_title','comparison_operator':'contains','value':'{{#'+selector_id+'.structured_output.section_prefix#}}'})
        branch_answer_prompt=answer_prompt
        if key == 'equipment':
            branch_answer_prompt += ('\n设备培训截图回答规则：若某页正文只有对象名称和“创建/查询”事务码，'
                '其他内容是截图中的字段标签、按钮、选项与示例值，则这些标签只能说明页面展示了什么，不能转写为操作步骤。'
                '分别说明创建与查询的原文入口和明确动作；其余截图用“原图展示初始屏幕/基本数据等界面”描述。'
                '原文明示的注释（如按现有序号加一、可复制可不复制、本单位成本中心）可转述。'
                '不要罗列截图示例编码、日期或OCR控制键值；不得凭“保存/取消”等按钮标签新增点击要求，'
                '不得把依次出现的界面当成原文已确认的必填字段/执行顺序。详细步骤依据不足时明确界限并展示原图。')
        if key == 'finance':
            branch_answer_prompt += ('\n以下为原文目录的条件层级，仅用于判断已检索操作的适用范围，不能替代操作正文。'
                '同一文件的子章节继承其上级编号的适用条件；不能因子章节未重复“上市/未上市”就否认原书的条件分支。'
                '与用户条件不符的章节不得作为操作依据。\n'+scope_text)
        nodes.extend([
            node(rid,'knowledge-retrieval',title,1000,y,dataset_ids=[dataset_ids[d] for d in domains],
                 query_variable_selector=query_selector,retrieval_mode='multiple',
                 multiple_retrieval_config={'top_k':6,'score_threshold':None,'reranking_mode':'weighted_score','reranking_enable':False,
                    'weights':{'weight_type':'customized','vector_setting':{'vector_weight':.7,'embedding_provider_name':'langgenius/ollama/ollama','embedding_model_name':'nomic-embed-text:latest'},'keyword_setting':{'keyword_weight':.3}}},
                 metadata_filtering_mode='manual',metadata_filtering_conditions={'logical_operator':'and','conditions':filters}),
            node(lid,'llm','依据'+title+'回答',1350,y,model=model,vision={'enabled':False},context={'enabled':True,'variable_selector':[rid,'result']},
                 prompt_template=[{'id':lid+'-system','role':'system','text':branch_answer_prompt},{'id':lid+'-user','role':'user','text':'用户问题：{{#sys.query#}}\n整理后的问题：{{#normalize.structured_output.query#}}'}]),
            node(aid,'answer','返回图文答案',1700,y,answer='{{#'+lid+'.text#}}',variables=[])])
        if key == 'finance':
            scope_gate='finance_scope'
            nodes.append(node(scope_gate,'if-else','是否已限定财务条件章节',840,y-160,cases=[{
                'id':'scoped','case_id':'scoped','logical_operator':'and','conditions':[
                    {'id':'finance-'+field,'variable_selector':[selector_id,'structured_output',field],
                     'comparison_operator':'not empty','value':'','varType':'string'} for field in ('source_id','section_prefix')]}]))
            scoped_ids={rid:rid+'_scoped',lid:lid+'_scoped',aid:aid+'_scoped'}
            for original_id in (rid,lid,aid):
                clone=deepcopy(next(n for n in nodes if n['id']==original_id))
                clone['id']=scoped_ids[original_id]
                clone['position']['y']+=140
                clone['positionAbsolute']['y']+=140
                clone['data']['title']+='（限定条件）'
                if original_id==rid: clone['data']['multiple_retrieval_config']['top_k']=20
                elif original_id==lid: clone['data']['context']['variable_selector']=[scoped_ids[rid],'result']
                else: clone['data']['answer']='{{#'+scoped_ids[lid]+'.text#}}'
                nodes.append(clone)
            edges.extend([edge('route',selector_id,'if-else','llm',key),edge(selector_id,scope_gate,'llm','if-else'),
                edge(scope_gate,rid,'if-else','knowledge-retrieval','false'),
                edge(scope_gate,scoped_ids[rid],'if-else','knowledge-retrieval','scoped'),
                edge(scoped_ids[rid],scoped_ids[lid],'knowledge-retrieval','llm'),
                edge(scoped_ids[lid],scoped_ids[aid],'llm','answer')])
        elif key == 'master_ops':
            # Resolve a requested operation within the selected book before ranking
            # body fragments: common MDG/menu words otherwise crowd out its steps.
            nav_id, section_id, gate_id = 'retrieve_master_outline', 'select_master_section', 'master_section_found'
            nav = deepcopy(next(n for n in nodes if n['id'] == 'retrieve_process'))
            nav['id'] = nav_id
            nav['data']['title'] = '读取所选主数据手册目录'
            nav['position'] = nav['positionAbsolute'] = {'x':1080, 'y':y-170}
            nav['data']['metadata_filtering_conditions']['conditions'][0]['value'] = '{{#select_source_master_ops.structured_output.source_id#}}'
            nodes.append(nav)
            nodes.append(node(section_id,'llm','定位本轮操作章节',1380,y-170,model=model,vision={'enabled':False},
                context={'enabled':True,'variable_selector':[nav_id,'result']},
                prompt_template=[{'id':'section-system','role':'system','text':
                    '你只定位章节，不回答操作。根据本轮问题和补全后的问题，在以下同一本手册的全书章节导航中选择对应的操作正文。\n{{#context#}}\n'
                    '用户展开某一步或字段录入时，优先选择详细操作步骤下包含该业务动作的最具体章节；'
                    '不能用前面的角色名称、菜单路径、步骤总表或其他审批步骤替代。'
                    'section_title只能逐字照抄全书章节导航中的一个完整标题（不要附来源、页码），保留标题内编号、标点和空格。'
                    '用户提问中的选项序号不是章节编号，应依据补全后的具体动作匹配。'
                    '一次问多个独立章节、没有匹配、目录为空或存在歧义时，section_title留空，回到该手册常规检索；不要猜标题。'
                    'search_query保留用户本次选中的具体动作和业务对象，不加入与所选步骤无关的审批角色、MDG等通用词或长文件名。'},
                    {'id':'section-user','role':'user','text':'本轮问题：{{#sys.query#}}\n已结合历史补全：{{#normalize.structured_output.query#}}'}],
                structured_output_enabled=True,structured_output={'schema':{'type':'object','additionalProperties':False,
                    'properties':{'section_title':{'type':'string'},'search_query':{'type':'string'}},'required':['section_title','search_query']}}))
            nodes.append(node(gate_id,'if-else','是否定位到具体章节',1680,y-170,cases=[{
                'id':'found','case_id':'found','logical_operator':'and','conditions':[
                    {'id':'master-section','variable_selector':[section_id,'structured_output','section_title'],'comparison_operator':'not empty','value':'','varType':'string'},
                    {'id':'master-source','variable_selector':[selector_id,'structured_output','source_id'],'comparison_operator':'not empty','value':'','varType':'string'}]}]))
            scoped_id = rid+'_section'
            scoped = deepcopy(next(n for n in nodes if n['id']==rid))
            scoped['id'] = scoped_id
            scoped['data']['title'] = '读取指定操作章节正文'
            scoped['data']['query_variable_selector'] = [section_id,'structured_output','search_query']
            scoped['data']['metadata_filtering_conditions']['conditions'].append({
                'name':'section_title','comparison_operator':'is','value':'{{#select_master_section.structured_output.section_title#}}'})
            scoped['position'] = scoped['positionAbsolute'] = {'x':1960,'y':y-170}
            nodes.append(scoped)
            content_gate = 'master_section_content'
            nodes.append(node(content_gate,'if-else','章节正文是否读取成功',2240,y-170,cases=[{
                'id':'content','case_id':'content','logical_operator':'and','conditions':[{
                    'id':'master-body','variable_selector':[scoped_id,'result'],'comparison_operator':'not empty','value':'','varType':'array[object]'}]}]))
            for original_id, new_id in ((lid,lid+'_section'),(aid,aid+'_section')):
                clone = deepcopy(next(n for n in nodes if n['id']==original_id))
                clone['id'] = new_id
                clone['data']['title'] += '（指定章节）'
                clone['position'] = clone['positionAbsolute'] = {'x':2520 if original_id==lid else 2820,'y':y-170}
                if original_id==lid: clone['data']['context']['variable_selector']=[scoped_id,'result']
                else: clone['data']['answer']='{{#'+lid+'_section.text#}}'
                nodes.append(clone)
            edges.extend([edge('route',selector_id,'if-else','llm',key),
                edge(selector_id,nav_id,'llm','knowledge-retrieval'),edge(nav_id,section_id,'knowledge-retrieval','llm'),
                edge(section_id,gate_id,'llm','if-else'),edge(gate_id,rid,'if-else','knowledge-retrieval','false'),
                edge(gate_id,scoped_id,'if-else','knowledge-retrieval','found'),edge(scoped_id,content_gate,'knowledge-retrieval','if-else'),
                edge(content_gate,rid,'if-else','knowledge-retrieval','false'),
                edge(content_gate,lid+'_section','if-else','llm','content'),edge(lid+'_section',aid+'_section','llm','answer')])
        elif key == 'funds':
            edges.extend([edge('route',selector_id,'if-else','llm',key),edge(selector_id,rid,'llm','knowledge-retrieval')])
        else:
            edges.append(edge('route',rid,'if-else','knowledge-retrieval',key))
        edges.extend([edge(rid,lid,'knowledge-retrieval','llm'),edge(lid,aid,'llm','answer')])
    for current in nodes:
        data = current['data']
        if data.get('structured_output_enabled'):
            # Routing needs machine-readable JSON, not reasoning mixed with schema examples.
            data['model'] = deepcopy(data['model'])
            data['model'].setdefault('completion_params', {}).update(thinking=False, response_format='json_object')
            data['prompt_template'][0]['text'] += '\n仅输出符合指定 schema 的 JSON 对象；不输出分析、schema 本身、Markdown 或其他文字。'
    return {'version':'0.7.0','kind':'app','app':{'name':'ERP运维知识助手-全量演示','description':'Dify 原生混合检索：9个业务主题库与流程导航，关键词/向量加权排序，原文图片由 Dify 提供。本地解析和OCR，资料适用性待复核。','mode':'advanced-chat','icon':'📚','icon_type':'emoji','icon_background':'#E0F2FE','use_icon_as_answer_icon':False},
        'dependencies':[], 'workflow':{'conversation_variables':[],'environment_variables':[],
        'features':{'opening_statement':'你好，可以直接输入流程名称（如“财务月结”）查看整体概览，再选择需要展开的环节；也可以描述具体操作或报错。回答附原文页码，有相关原图时会展示。资料适用性待业务复核。',
            'suggested_questions':['财务月结业务流程','油气田单元创建流程','项目结转后怎么撤销？'],
            'suggested_questions_after_answer':{'enabled':False},'retriever_resource':{'enabled':True},'file_upload':{'enabled':False},
            'speech_to_text':{'enabled':False},'text_to_speech':{'enabled':False},'sensitive_word_avoidance':{'enabled':False}},
        'graph':{'nodes':nodes,'edges':edges,'viewport':{'x':30,'y':50,'zoom':.35}}}}


if __name__ == '__main__':
    parser=argparse.ArgumentParser()
    parser.add_argument('--state',default=str(ROOT/'data/dify/full-state.json'))
    args=parser.parse_args()
    state=json.loads(Path(args.state).read_text(encoding='utf-8'))
    dsl=build({k:v['id'] for k,v in state['datasets'].items()})
    target=ROOT/'dify/chatflow-full.yml'
    target.write_text(yaml.safe_dump(dsl,allow_unicode=True,sort_keys=False),encoding='utf-8')
    print(target)
