# 全量分库与图文演示

`D:\PDF版本` 的 257 份 PDF、5,244 页已全部完成本地 OCR，失败页为 0。当前 4,840 个图文父文档已全部上传并完成索引，8,084 处原图引用和 4,561 条检索子块通过远端逐条核查。52 个旧章节已标记失效并保留审计记录。最新验收证据见 [全量验收记录](acceptance.md)。

## 演示入口

[ERP运维知识助手-全量演示](http://192.168.24.133:8811/installed/25089298-f80f-42e9-95c9-01c75de9c0d7)，登录 Dify 后直接问答。工作流版本 **#14 已发布**；[编辑与预览](http://192.168.24.133:8811/app/c68c4490-aee8-496a-85c7-9f0dd3574168/workflow)。具体问题使用 Dify 原生关键词与向量混合检索、加权排序，流程概览保留精确导航。当前维护说明见 [原生检索运行与维护](native-dify-operation.md)；下方早期证据保留历史版本记录。

演示不需要启动 Windows 的 8765 服务。图片由 Dify 自身提供；#10 的旧对话仍保留旧图片地址，不会随发布改写，请开启新对话测试。用户已确认此前 Chrome 图片不可见由广告拦截插件导致，本次未修改插件设置。

新增流程名称演示：新对话输入“财务月结业务流程”，先返回全书主要环节和页码，再输入“展开制造费用分摊，只看上市单位”。另可试“油气田单元创建流程”“设备管理操作手册”和“预算调整流程”，分别验证流程图、无封面名称和多个候选追问。全部 257 份资料的导航已索引并通过远端内容审计，详见 [流程名称问答](process-navigation.md)。

2026-09-21 最终演示顺序：

1. 问“结转怎么撤销？”：先澄清项目、维修工单等对象。
2. 接着问“是项目结转，已经结转后怎么撤销？”：检索项目管理和财务核算，引用《财务模块常见问题》PDF 第17页，回答 CJ88、保持变式/期间/年度一致、“结算→冲销”。原图可点击放大。
3. 问“换成维修工单，结转后怎么取消？”：切换为 KO8G 与 PDF 第18页原图。
4. 问“付款申请岗如何创建并查询付款单？”：展示跨章节检索及配图。
5. 问“MDG组织机构如何查询和分发？”：展示对象资料选择、可选查询方式与原图。
6. 问“维修工单结转报错 ZOPS999：星际结算闸门失效，怎么修复？”：说明没有处理依据，不编造修复步骤或附无关图片。

这是功能抽查，不代表全库回答准确率。九个业务主题均已通过实际页面抽查；最终证据为 `data/reports/final-ui-*.txt`，具体问法和结果见 [全量验收记录](acceptance.md)。

后续发现近义问法“项目结转后怎么撤销？”会漏掉原文“项目结转后如何取消结转”。在同一父文档下添加仅含原文标题的检索子块后，Dify API 实测该问法的目标来源升至 Top 1（分数约 0.773）。此分数不是正确率。该改进由 `enrich_search_anchors.py` 覆盖全部适用章节；标题来自原文，不生成新的业务答案。

正式演示页面也已复测此问法，正常返回三步操作与原图；最终记录在 `data/reports/final-demo-project.txt`。前期放大原图的截图在 `data/reports/full-demo-image.png`。

版本 #2 修正了把截图控件名称扩展为新操作的问题。多轮切换到维修工单后，复测只给出 KO8G、与结转时一致的变式/期间/年度、“结算→冲销”三步，并显示 PDF 第18页原图；不再添加原文没有要求的“勾选测试运行/明细清单”。证据在 `data/reports/equipment-after-prompt-fix.txt`。追问资料是否适用于 S/4HANA 2023 时，明确回答无法确认，没有冒充已验证版本；证据在 `data/reports/full-version-unknown-ui.txt`。

匿名 Web App 入口已停用，演示使用已登录的工作区。访问点自动生成的地址缺少 `:8811`，暂不把它作为有效入口。

## 九个主题库

财务核算、资金与预算、采购与物资、项目管理、内部交易、油气业务、设备管理、主数据操作、主数据标准。每个库的真实 ID 及文档回执在 `data/dify/full-state.json`。

另有独立的流程导航库，用于按流程名或文件主题定位整份资料、介绍覆盖范围，再引导用户展开具体环节。导航卡来自本地已处理的原文，不重新把整份 PDF 混入业务检索。名称、目录、页码与更新方法见 [按流程名称问答](process-navigation.md)。

机器人根据问题限定一个业务主题，或项目/财务、设备/财务、采购/主数据、内部交易/资金、财务/资金中的一个主题组合，在对应 Dify 知识库中检索。缺少会改变流程的关键信息时追问。没有依据时不能补写操作。

## 文档如何进入知识库

- 本地提取原生文字，RapidOCR/ONNX 识别截图；已识别的装饰图哈希不参与截图 OCR。
- 使用 PDF 书签、章节坐标和原生标题划分；保留否定条件、表格、原图、页码、来源哈希。
- 一节或一个有明确续篇标记的部分，生成一个带图片 DOCX，作为 Dify 的完整父文档。子块 500 token、重叠 60；命中子块后返回父文档。
- 上传文档及当前 #14 回答的原图由 Dify 保存和提供。云端回答模型视觉关闭，只收到文本证据与图片链接，输出原有链接供页面显示。
- 标注原文事务码疑点、低置信 OCR、适用版本未知和业务待复核。原始页面作为证据时保留原貌，可能仍含页眉 logo。

## 查看真实进度

```powershell
Set-Location D:\rag\ops-pdf-rag
.\.venv\Scripts\python.exe scripts/full_progress.py
.\.venv\Scripts\python.exe scripts/sync_full.py status --compact
# 对已完成索引的父文档补充简短、取自原文的检索子块
.\.venv\Scripts\python.exe scripts/enrich_search_anchors.py --workers 2
# 九个主题的来源召回抽查；失败项必须分析，不作为全库准确率
.\.venv\Scripts\python.exe scripts/evaluate_full_retrieval.py
```

`data/full-export/manifest.json` 是当前来源清单；`data/reports/full-indexing.json` 是某一时刻的 Dify 索引快照。每库 `target.counts` 单独统计当前内容哈希匹配、元数据写入、索引完成且启用的条目，保留的旧文档不能算作当前版本验收通过。只有所有目标文档均满足这些条件，才能声明全部可检索。

`data/reports/ingestion-coordinator.json` 记录续跑阶段、进程号和最近检查时间。总控依次等待索引、上传待更新条目、补充检索标题、核对当前版本，全部可用后才标记旧章节失效。它运行期间不要另起上传、补充标题或失效处理进程；需要停止时创建 `data/reports/stop-ingestion` 文件，总控会在本轮操作完成后停止。再次启动前移走该停止文件。

```powershell
.\.venv\Scripts\python.exe scripts/complete_full_ingestion.py --max-hours 12 --interval 120
```

总控完成仅代表入库及索引完成，之后仍须运行九个主题召回抽查和真实页面回答验收。

## 续跑与更新

同一时刻只运行一个 OCR 总控、一个构建进程、一个同步进程；不要重复启动正在执行的任务。

```powershell
# 修改/新增原始 PDF 后先重建清单与原生文字
.\.venv\Scripts\python.exe -m ops_rag.cli scan
.\.venv\Scripts\python.exe -m ops_rag.cli native --all
# 四个本地进程执行 OCR；相同来源与配置命中缓存
.\.venv\Scripts\python.exe scripts/process_full.py
# 全部或部分完成的 PDF 整理成可导入父文档
.\.venv\Scripts\python.exe scripts/build_full_corpus.py
.\.venv\Scripts\python.exe scripts/verify_full_corpus.py
# 分库、增量上传；首次运行 setup 创建主题库
.\.venv\Scripts\python.exe scripts/sync_full.py setup
.\.venv\Scripts\python.exe scripts/sync_full.py upload --workers 2
.\.venv\Scripts\python.exe scripts/sync_full.py status --compact
# 只对完整构建允许处理旧章节，默认打印清单
.\.venv\Scripts\python.exe scripts/sync_full.py retire-stale
# 确认清单后标记失效，保留远端原文和来源供核查
.\.venv\Scripts\python.exe scripts/sync_full.py retire-stale --apply
```

等待当前索引全部完成后，运行 `scripts/enrich_search_anchors.py --workers 2` 补齐或更新检索标题，再执行召回检查与远端完整性核查。也可在构建校验通过后直接用 `complete_full_ingestion.py` 总控完成上传、等待、补充标题和旧章节失效；不要与手动同步进程同时运行。

更新业务文档后，也需按 [导航更新流程](process-navigation.md#更新与恢复) 重建并同步流程导航，再生成和发布工作流，使名称目录与当前资料一致。

知识库 API 密钥经授权创建，仅写入本机 `.env`。同步依据唯一文档名、内容哈希和回执续跑；中断后先核对远端同名文件，不盲目重复创建。失效文档通过元数据过滤排除。正文和导航更新后，运行 `scripts/build_full_chatflow.py` 重建资料选择目录，在现有应用导入 `dify/chatflow-full.yml`、检查并发布更新，最后用真实问题验收。完整顺序见 [新增 PDF 指南](add-pdfs.md)。

## 验收边界

技术检查覆盖来源页码、DOCX 图片完整性、图片大小、远端索引及真实问答。业务负责人仍需确认适用版本、角色权限、流程现行性和截图示例值。低置信 OCR 数量不是已确认错误数量。#14 使用 Dify 原生混合检索和向量/关键词 0.7/0.3 加权排序；普通回答取6个结果，明确财务来源与条件时最多20个，流程导航取1个。当前不调用独立 BGE 重排。实际业务准确率仍需业务问题集评估。
