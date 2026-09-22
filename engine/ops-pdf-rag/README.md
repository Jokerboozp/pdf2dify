# PDF 运维图文问答工程

257 份 PDF、5,244 页已全部完成本地解析和 OCR，分入 9 个业务知识库。当前 4,840 个图文父文档全部完成 Dify 索引，8,084 处原图引用、4,561 条补充检索标题及来源元数据通过远端逐条核查。另有 257 张整份资料导航卡，覆盖流程名称、文件主题、4,074 项章节及页码，独立导航库已全部索引并通过远端内容审计。

## 直接演示

[打开 ERP 运维知识助手](http://192.168.24.133:8811/installed/25089298-f80f-42e9-95c9-01c75de9c0d7)，需要登录该 Dify 工作区。工作流版本 **#14 已发布**，使用 Dify 原生关键词与向量混合检索，图片由 Dify 提供并可点击放大。Windows 8765 服务已停止，停止后正式入口图文问答实测通过。操作顺序见 [演示与维护说明](docs/full-demo.md)，原生迁移证据见 [迁移验收](data/reports/native-migration-20260921.md)，#12 图片修复见 [凭证配图验收](data/reports/voucher-image-fix-20260921.md)，#13 事务码查询修复见 [验收记录](data/reports/transaction-route-fix-20260921.md)，#14 设备章节检索见 [工作中心修复](data/reports/workcenter-fix-20260921.md)。

建议先问“财务月结业务流程”，查看主要环节和页码，再问“展开制造费用分摊，只看上市单位”。也可问“结转怎么撤销？”，回答追问“是项目结转”，演示澄清、具体步骤和图片。全程是资料问答，不执行 ERP 业务操作。

## 已完成能力

- Dify 原生混合检索，使用已有服务器 Ollama 向量模型，按向量 70% / 关键词 30% 加权排序；支持来源及条件过滤。日常问答无需额外部署本工程检索服务，见 [原生检索运行与维护](docs/native-dify-operation.md)。旧 BM25 + BGE 重排实现保留供回退，当前不调用它。
- 财务核算、资金与预算、采购与物资、项目管理、内部交易、油气业务、设备管理、主数据操作、主数据标准，九库按问题选择。
- 直接输入流程名称或文件主题可查看整体概览，再选择环节；同名分册和多个业务对象无法区分时先追问。219 份使用封面名称，38 份以文件名建立入口，详见 [按流程名称问答](docs/process-navigation.md)。
- PDF 书签和章节边界切分，保留正文、截图文字、表格、原图、原 PDF 文件名和页码。已核对的装饰图不参与截图 OCR；证据原图保留原貌，可能含页眉 logo。
- 检索返回原文父章节；资金和主数据操作先按真实手册目录选择业务对象，减少不同对象的“创建/审批”相互干扰。
- 断点续跑、内容哈希增量同步、索引状态核查、旧章节失效过滤。52 条旧章节保留但不参与回答。
- 没有依据时说明资料不足，关键对象不明确时先追问。适用系统版本和业务时效仍待业务确认。

本轮 52 项代码测试通过。Dify 原生九主题来源抽查 9/9，导航来源限定检索 5/5、财务条件过滤 3/3；十库配置及三个项目结转问法检查通过。草稿验证流程概览及上市/未上市追问，正式入口在旧服务停止后验证项目撤销与 Dify 原图。这些功能抽查不代表全库回答准确率。

## 本机和 Dify 配置

当前直接使用已有 Linux 服务器上的 Dify 和 Ollama，无需再部署独立检索容器。日常依赖与迁移注意事项见 [原生检索运行与维护](docs/native-dify-operation.md)。旧 `deploy/linux/` 和 [独立服务器部署指南](docs/server-deployment.md) 仅保留为历史可选方案。

工程位于 `D:\rag\ops-pdf-rag`，原始 PDF 位于 `D:\PDF版本`，原文件只读。当前 Python 3.12 虚拟环境已就绪，依赖锁定在 `requirements.lock.txt`；新机器运行 `scripts/setup.ps1`。

OCR 使用本机 RapidOCR ONNX CPU。Dify 知识库使用 Ollama `nomic-embed-text:latest`，已核实模型地址为服务器 `http://192.168.24.133:11434`。云端 DeepSeek `deepseek-v4-flash` 仅接收问题、文本证据与图片链接，所有节点视觉输入关闭；PDF 和图片未发往云端 OCR。Dify 1.17.1 使用内置节点，未依赖代码沙箱。Windows 仅用于文档转换和增量入库，不需要启动 `scripts/start-local-search.ps1`。

知识库 API 密钥经授权保存在本机 `.env`，不要写进聊天或提交到仓库。匿名 Web App 停用，使用已登录工作区演示入口。没有创建应用 API 密钥。

## 检查与更新

日常新增 PDF 的完整操作顺序见 [新增 PDF：转换、分库上传和发布](docs/add-pdfs.md)，包含新增目录要求、可复制命令、完成判断和 Dify 发布步骤。

```powershell
Set-Location D:\rag\ops-pdf-rag
.\.venv\Scripts\python.exe scripts/sync_full.py status --compact
.\.venv\Scripts\python.exe scripts/verify_full_corpus.py
.\.venv\Scripts\python.exe scripts/evaluate_full_retrieval.py
.\.venv\Scripts\python.exe scripts/audit_remote_corpus.py
.\.venv\Scripts\python.exe -m pytest -q --basetemp=data/test-tmp
```

本次全量总控已完成并退出。新增或修改 PDF 后的完整增量流程见 [续跑与更新](docs/full-demo.md#续跑与更新)。生成目录中的文件会重建，业务修订请保存在独立复核记录中。

## 工程入口

| 路径 | 内容 |
|---|---|
| `src/ops_rag/` | 清点、OCR、章节整理、同步和检索标题 |
| `scripts/` | 全量处理、校验、同步总控与工作流生成 |
| `prompts/` | 问题路由和依据资料回答的提示词 |
| `dify/chatflow-full.yml` | 当前 #14 Dify 原生混合检索工作流 |
| `dify/chatflow-local.yml` | 历史 #10 独立检索工作流模板（不含密钥） |
| `evaluation/full-smoke.yaml` | 九个主题的来源召回检查 |
| `data/full-export/manifest.json` | 当前入库清单，以此为准而非目录文件总数 |
| `data/dify/full-state.json` | 九库 ID 和同步回执 |
| `data/reports/` | 本地、远端和真实页面验收证据 |

试点应用和资料保留供追溯；前期说明见 [试点历史](docs/pilot-readme-history.md)，其中旧进度不代表当前状态。远程仓库仅包含工程代码和配置模板；原始资料、生成内容、运行数据、虚拟环境与 `.env` 已加入 `.gitignore`，仍保留在本地。
