# Dify 原生检索运行与维护

2026-09-21，现有应用已发布为 #15，使用 Dify 原生知识检索节点，旧 Windows 8765 检索服务已停止。入口和已入库资料沿用原应用。

## 运行结构

`PDF → 本地解析/OCR → 带原图和页码的章节 DOCX、流程导航 → Dify 知识库 → 原生混合检索 → 云端文本模型回答`

- Dify：`http://192.168.24.133:8811`，已有九个业务库和一个流程导航库。
- 向量模型：已有 Ollama `nomic-embed-text:latest`。模型配置页实测基础地址为 `http://192.168.24.133:11434`，位于服务器，不依赖 Windows。该模型服务仍需运行。
- 检索：高质量索引，关键词与向量混合召回，向量 70% / 关键词 30% 加权排序。当前不调用独立 BGE 重排模型；这与原 BM25 + BGE + 交叉编码器方案并非相同算法。
- 图片：Dify `/files/.../file-preview`，由原生工作流生成签名链接。正文保留原 PDF 名称及页码。
- 回答：现有 DeepSeek 文本模型。视觉输入关闭，PDF OCR 仍在本地处理。

日常问答不需要运行本工程服务；本工程用于新增、修改 PDF 时的转换、质量检查和增量入库。服务器需要已有 Dify、其数据库/存储/向量组件和 Ollama；无需再部署本工程的检索容器。

## 新增 PDF

按 [新增 PDF：转换、分库上传和发布](add-pdfs.md) 执行。主工作流是 `dify/chatflow-full.yml`，由 `scripts/build_full_chatflow.py` 生成。新增资料后同时维护正文、原文检索标题、流程导航及工作流资料目录。

不要按历史 #10 步骤运行 `build_local_chatflow.py` 并覆盖正式应用，否则会重新引入 8765 依赖。旧代码、模型和部署包保留供回退，没有删除。

## 验证和问题定位

```powershell
Set-Location D:\rag\ops-pdf-rag
.\.venv\Scripts\python.exe scripts/sync_full.py status --compact
.\.venv\Scripts\python.exe scripts/evaluate_full_retrieval.py
.\.venv\Scripts\python.exe scripts/evaluate_process_navigation.py
.\.venv\Scripts\python.exe scripts/evaluate_finance_scope.py
.\.venv\Scripts\python.exe scripts/verify_native_readiness.py
```

`verify_native_readiness.py` 检查十库配置、三个项目结转问法、Dify 图片引用及无外部检索的本地 DSL。它不代替正式页面验收：知识库 Service API 返回的原始图片引用没有签名，直接请求可能为 HTTP 400；原生工作流会签名，实际图片应在机器人页面验证。

建议开启新对话测试“项目结转后怎么撤销？”及“财务月结”，再追问“展开制造费用分摊，只看上市单位”和“改看未上市单位的制造费用分摊”。检索抽查通过不等于全库业务正确率；长答案的措辞和重复配图仍需对照原文。

此前一例 Chrome 图片不显示由广告拦截插件导致；2026-09-21 的“凭证时提示计量单位不能为空”则是模型把 URL 改为 `https://...`，已在 #12 强化完整相对地址复制规则。不要仅凭空白图片就判断为插件拦截：应区分回答缺少 Markdown、链接被改写、签名过期和浏览器加载失败。详见 [凭证配图修复验收](../data/reports/voucher-image-fix-20260921.md)。旧版本对话中的 `192.168.24.1:8765` 链接不会自动改写，停止旧服务后需重新提问获取 Dify 图片。Dify 签名链接失效时也应重新提问。

## 事务码查询验收

#13 将“事务码 - 功能名称”按具体操作查询处理，避免误走流程概览。对混合章节，回答仅引用匹配事务码的连续操作页和图片。`ZP0PSADG0019 - 物资需求提报` 应对应采购培训第 10、11 页的新增、检查、保存和 BPM 审批；明确指定文件名时应保留该来源。回归用例见 `evaluation/transaction-route-ui.yaml`，发布记录见 [事务码查询修复](../data/reports/transaction-route-fix-20260921.md)。

## 设备操作章节检索

#14 支持“工作中心主数据创建、查询”等操作章节名直接查询正文；设备手册内的原文对象标题用于选库，避免仅凭“主数据”误入 MDG。纯目录片段标记为 `目录` 并从设备操作检索排除，原文与图片仍保留。新增/修改 PDF 后应运行 `scripts/build_full_chatflow.py` 更新内置对象目录；设备正文召回回归运行 `scripts/evaluate_equipment_topics.py`，页面用例见 `evaluation/equipment-operation-ui.yaml`。详情见 [工作中心修复验收](../data/reports/workcenter-fix-20260921.md)。

## 流程概览后继续追问

#15 增加主数据流程的章节展开：先保留上一轮手册主题与本轮操作名称，读取所选手册导航，按原文章节标题过滤正文；无法明确定位时回退同手册检索。结构化路由/定位节点使用非思考 JSON 输出，避免分析内容干扰 source_id 等变量解析。回归脚本 `scripts/check_section_retrieval.py`，连续对话用例 `evaluation/process-followup-ui.yaml`，验收见 [流程追问修复](../data/reports/process-followup-fix-20260921.md)。旧回复不会自动重写，重新发送问题后使用新流程。

## 迁移和回退

以后迁移整套 Dify 时，需一并迁移数据库、上传文件存储、向量数据和现有模型服务；仅导入 DSL 不会复制知识库内容。若更换了知识库 ID，应更新工程同步配置和工作流后重新验收。

应用版本历史保留 #10；本机备份为 `data/dify/backups/chatflow-local-before-native-20260921.yml`，该文件包含原检索服务密钥，只留在本机。恢复 #10 需要同时恢复旧检索服务和图片可达性，不能只恢复工作流。独立服务部署文件见历史 [服务器部署指南](server-deployment.md)。
