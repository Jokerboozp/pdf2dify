# 本地混合检索与重排

> 历史方案：2026-09-21 起正式应用已切换为 #11 Dify 原生混合检索，旧 8765 服务已停止。本页保留独立 BGE 检索的实现和回退说明，日常运行请看 [原生检索运行与维护](native-dify-operation.md)。下文“当前”均指 #10 验收时点。

当前状态（2026-09-21）：Dify 本地混合检索版 **#10 已发布**。用户完成网络放行后，草稿的项目撤销结转、上市/未上市制造费用分摊均成功调用本地服务并返回图文；正式入口的“财务月结”流程概览也已通过。发布和验证证据见 [本地检索验收](hybrid-acceptance.md)。

这条链路使用已有 PDF 转换产物，不重新进行云端 OCR：

`原文正文 / 表格 / 本地 OCR / 章节和流程名 → BM25 与中文向量双路召回 → RRF 合并 → BGE 交叉编码器重排 → 返回原文父章节、页码与图片 → Dify 生成答案`

## 覆盖与模型

- 索引读取 `data/full-export/manifest.json` 的当前有效父章节，以及 `data/process-navigation/catalog.json` 的流程导航。历史上传回执中已退出当前清单的资料不会进入索引。
- 向量模型：`BAAI/bge-small-zh-v1.5`，512 维；重排：`BAAI/bge-reranker-base`。通过 FastEmbed / ONNX Runtime 在本机 CPU 推理。模型首次从 Qdrant、BAAI 官方模型仓库下载，后续推理只读本机缓存。
- 300 字检索窗口，重叠 60 字，每段重复真实资料主题和章节标题。用于向量匹配的窗口与返回给回答模型的原文父章节分开保存，避免大 PDF 全文截断后只剩第一页。
- 两路各召回最多 60 个父章节，按 RRF 融合后取 24 个候选重排，同时保证两路各自前三名进入候选池，避免只有语义命中的结果被排除。每个候选同时检查关键词和语义命中的窗口；最终按重排分数排序。分数不是答案正确率。
- 业务主题、来源和条件章节在两路召回前过滤。“上市”和“未上市”等条件沿用现有工作流的原文目录判断。
- 文件名、封面别名进入流程导航；语义检索不自行编造专业简称的释义。未出现在语料、模型也不认识的内部简称仍需要业务人员补充定义。

## 日常使用

在工程目录运行：

```powershell
cd D:\rag\ops-pdf-rag
.venv\Scripts\python.exe -m ops_rag.cli search "项目结转后怎么撤销？" --domain projects --kind detail
```

可以使用 `--engine bm25`、`--engine vector`、`--engine fusion`、`--engine hybrid` 对比同一份全量索引；默认是 `hybrid`。早期试点卡片 BM25 保留为 `--engine pilot`。

启动供 Dify 调用的服务：

```powershell
.\scripts\start-local-search.ps1
```

默认只绑定本机 VMware 网卡 `192.168.24.1:8765`，供现有 Dify 虚拟机访问。`/health` 返回 ready 才表示模型完成加载。服务以隐藏进程运行，日志在 `logs/local-search.*.log`；不记录查询文本或访问密钥。重启 Windows 后需要再次启动；没有设置系统开机自启。

当前环境已联通，无需重复放行。新电脑首次连接时，可由用户在管理员 PowerShell 运行以下脚本，仅允许 `192.168.24.133 → 192.168.24.1:8765/TCP`，不会关闭防火墙：

```powershell
& 'D:\rag\ops-pdf-rag\scripts\enable-dify-local-search.ps1'
```

迁移或更新连接配置后，应在 Dify 草稿预览验证“项目结转后怎么撤销？”和财务上市/未上市条件，确认步骤与原图正常，再发布。本机 API 验证通过不等于 Dify 已联通。

检索接口为 `POST /search`（JSON）或 `/search-form`（URL 编码表单），需要 `Authorization: Bearer <LOCAL_RETRIEVAL_API_KEY>`。字段：`query`、`route`、`source_id`、`section_prefix`、`kind`、`top_k`。未知业务路由会拒绝，缺省路由才查全库。模型串行推理，默认最多接纳 8 个请求（包含执行中的请求），等待模型最长 60 秒；超过容量或等待时限才返回 429 和 `Retry-After: 5`。通过 `retrieval_service.max_pending_requests` 和 `retrieval_service.queue_wait_seconds` 调整；Dify HTTP 读取超时需要覆盖排队和推理耗时。队列参数独立于索引参数，修改后重启服务即可，无需重建索引。

原文图片由服务根据当前索引白名单提供，链接签名有效期一小时；过期的历史回答需要重新查询以生成新链接。浏览器也需要能访问服务地址。Dify 回答模型仍关闭视觉，不把原始 PDF 或截图发送到云端 OCR。

## 新增 PDF 后怎么更新

先按 [新增 PDF 指南](add-pdfs.md) 完成扫描、转换、原文清单及流程导航更新，然后执行：

```powershell
.venv\Scripts\python.exe -m ops_rag.cli index
```

相同内容和模型的向量会复用，只有新增或变化窗口需要计算。中断后重新运行同一命令可续跑。索引完整后才切换 `data/local-index/current.json`，服务会在下一次请求加载新快照。清单已变而索引未更新时返回 409，避免悄悄使用陈旧索引。

现有 Dify 分库上传、原图和流程导航同步继续按原流程执行。新加手册会改变工作流中的来源目录，因此完成同步后还需生成并在 Dify 导入新的本地版 DSL：

```powershell
.venv\Scripts\python.exe scripts/build_local_chatflow.py
```

`dify/chatflow-local.yml` 是不含密钥的模板；可直接导入本机生成的 `data/dify/chatflow-local-private.yml`，该文件携带本地服务专用密钥，和 `.env` 一样只保留在本机。导入后预览验证，再发布到原演示应用。仅重建索引不会更新 Dify 的来源选择目录。

## 部署结构与回退

迁移到 Linux + Docker 并与 Dify 同机时，使用 [服务器部署指南](server-deployment.md) 和 `deploy/linux/` 中的部署工具。包携带当前索引、离线模型与原图；Dify 草稿验证服务器地址后再发布，切换完成前保留 Windows 服务。

Dify 的流程概览保持原有“流程选择 → 精确流程导航 → 概览/追问”链路。具体操作查询使用本地检索 HTTP 节点，接收整理后的自然问句，保留现有业务分支、来源选择和财务条件过滤。回答节点仍根据原文内容及配图回答。

配置位于 `config.yaml` 的 `local_retrieval` 和本机 `.env` 的 `LOCAL_RETRIEVAL_URL`、`LOCAL_RETRIEVAL_API_KEY`。模板中只引用 Dify 的 secret 环境变量。迁移电脑或改变服务地址时要同步更新配置、生成 DSL 并重新导入。

`dify/chatflow-full.yml` 保留原有 Dify 内置混合检索版本，可导入并发布以回退；此前上传的九个业务知识库及流程导航没有被删除。不要把本地 HTTP 检索误认为是在 Dify 内置知识库中启用了某个重排供应商。

## 验证

```powershell
.venv\Scripts\python.exe -m pytest -q
.venv\Scripts\python.exe scripts/evaluate_hybrid.py
.venv\Scripts\python.exe scripts/evaluate_hybrid.py --cases evaluation/hybrid-validation.yaml --output data/reports/hybrid-validation.json --via-api
```

评估题固定在 `evaluation/hybrid-cases.yaml`；报告输出到 `data/reports/hybrid-evaluation.json`，列出相同语料下 BM25、向量、融合和重排的 Hit@1、Hit@5、MRR 与耗时。该固定集合用于发现并修复候选截断问题，因此最终结果属于回归验证；修复后另写了 8 道未参与调试的题，位于 `hybrid-validation.yaml`，通过真实本机 API 运行。样本规模有限，主要覆盖财务常见问题及流程导航，不代表所有文档或最终业务答案均已验收。

模型依据：[FastEmbed 支持模型](https://qdrant.github.io/fastembed/examples/Supported_Models/)、[Qdrant 重排文档](https://qdrant.tech/documentation/fastembed/fastembed-rerankers/)、[BGE 重排模型](https://bge-model.com/tutorial/5_Reranking/5.2.html)。
