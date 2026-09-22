# 新增 PDF：转换、分库上传和发布

适用于本机现有工程 `D:\rag\ops-pdf-rag` 和 Dify `http://192.168.24.133:8811`。原始 PDF 放在 `D:\PDF版本`。当前已配置知识库 API 密钥、九个业务库和一个流程导航库。

整个流程为：新增 PDF → 本地文字提取和 OCR → 带原图、页码的章节 DOCX → 对应业务库 → 整份资料导航 → 更新工作流中的资料目录 → 发布并试问。

## 1. 放入新文件

把新 PDF 放进 `D:\PDF版本` 下对应的现有业务目录。例如财务核算资料可放到：

```text
D:\PDF版本\ERP系统运维支持中心业务操作手册\核算模块\新流程操作手册.pdf
```

文件名应说明业务主题，适合时带上岗位、版本。没有封面流程名称也可以处理，文件主题会成为名称入口。原有 PDF 保持原位；不要把来源目录清空后只放新文件，因为它是整套有效资料清单，同步总控会将已不在清单中的旧章节标记失效。

当前分类使用目录和文件名规则，并非通用自动分类模型。财务、资金、预算、内部交易、主数据等资料应沿用现有业务目录。不能分类时，构建会报 `Unclassified source` 并停止：先在 `src/ops_rag/corpus.py` 的 `classify()` 中补充映射。全新的业务类别还需增加知识库与工作流路由，不能直接视为现有九类之一。原有《财务模块常见问题.pdf》有按页分库规则，若更新了它的页码，应同步检查这些规则。

## 2. 本地转换

打开 PowerShell，按顺序执行。每条完成且没有报错后，再执行下一条；同一阶段不要重复开多个终端运行。

```powershell
Set-Location D:\rag\ops-pdf-rag
.\.venv\Scripts\python.exe -m ops_rag.cli scan
.\.venv\Scripts\python.exe -m ops_rag.cli native --all
.\.venv\Scripts\python.exe scripts/process_full.py
.\.venv\Scripts\python.exe scripts/build_full_corpus.py
.\.venv\Scripts\python.exe scripts/verify_full_corpus.py
```

扫描会遍历来源目录；未变化且配置相同的文字提取、OCR 和章节产物会复用缓存。内容变化的 PDF 会重新处理，不需要删除缓存或旧回执。

继续上传前检查：

- `data/inventory.json` 中没有 `status: error` 的 PDF。
- `data/reports/full-processing.json` 的 `failed` 为空。
- 构建结果及 `data/reports/full-corpus-verification.json` 的 `pending_sources` 为零/空列表，`errors` 为空。
- 在 `data/full-export/<业务分类>/` 抽查新文档的 DOCX：业务分类、章节、条件、原图和页码正确。以 `data/full-export/manifest.json` 为当前清单；目录可能保留旧产物。

新模板、扫描质量差或无章节结构的文档尤其要检查切分。现有 logo 排除规则仅覆盖已核对的装饰图片，新的 logo 不保证自动识别干净，必要时补规则后重建。

## 3. 上传到业务知识库

```powershell
.\.venv\Scripts\python.exe scripts/complete_full_ingestion.py --max-hours 12 --interval 120
Get-Content data/reports/ingestion-coordinator.json
```

该总控会上传新增/变化章节、等待索引完成、补充原文检索标题，最后处理已失效的旧章节；相同内容不会再次上传。复用本机 `.env` 中的授权密钥。

只有报告中的 `phase` 为 `completed`，才能继续。若为 `time_limit`，重跑同一命令续接；报错则先检查报告原因。若为 `stopped`，说明存在停止标记 `data/reports/stop-ingestion`，确认要恢复后移走该标记再运行。不要在总控运行时另开上传、补充标题或失效处理命令。

完成后核查远端内容：

```powershell
.\.venv\Scripts\python.exe scripts/audit_remote_corpus.py
```

`data/reports/remote-corpus-audit.json` 应为 `passed: true`。

## 4. 更新流程导航

新增文档的详细章节和整份资料导航需要一起维护，否则流程名称入口可能仍使用旧目录。

```powershell
.\.venv\Scripts\python.exe scripts/process_navigation.py build
.\.venv\Scripts\python.exe scripts/complete_process_navigation.py
.\.venv\Scripts\python.exe scripts/configure_finance_retrieval.py
```

导航总控自动上传并审计。检查 `data/reports/process-navigation-coordinator.json` 为 `phase: completed`、`audit_passed: true`，并确认 `process-navigation-audit.json` 中 `total`、`current`、`ready` 相等、`passed: true`。达到一小时时限可续跑同一命令；若有 `stop-process-navigation` 停止标记，按恢复意图处理后再运行。

## 5. 更新并发布工作流

当前已发布 #14 使用 Dify 原生混合检索。完成第 4 步后，更新工作流中的资料目录并验证 Dify 检索；不需要构建独立 BGE 索引、启动 8765 服务或生成检索服务部署包。

```powershell
.\.venv\Scripts\python.exe scripts/evaluate_full_retrieval.py
.\.venv\Scripts\python.exe scripts/evaluate_process_navigation.py
.\.venv\Scripts\python.exe scripts/evaluate_finance_scope.py
.\.venv\Scripts\python.exe scripts/build_full_chatflow.py
.\.venv\Scripts\python.exe scripts/verify_native_readiness.py
```

这些用例检查原有资料，不代表新 PDF 自动验收。如果替换的是用例引用的原文件，其来源哈希也会变化，需要先核对新版本再更新对应评测用例。

打开现有应用的[编排页面](http://192.168.24.133:8811/app/c68c4490-aee8-496a-85c7-9f0dd3574168/workflow)：

1. 从应用名称旁的更多操作选择“导入 DSL”。
2. 选择 `D:\rag\ops-pdf-rag\dify\chatflow-full.yml`，覆盖并导入到现有应用草稿。该版本不含独立检索服务密钥。
3. 检查清单无错误后，在预览中试问新资料，再点击“发布 → 发布更新”。

生成器依据工程中的提示词和配置重建工作流。如果以后手动改过 Dify 编排，先导出并保留当前版本，将所需改动合并到工程生成器后再覆盖草稿。

## 6. 用新资料验收

在[现有机器人](http://192.168.24.133:8811/installed/25089298-f80f-42e9-95c9-01c75de9c0d7)开启新对话，至少检查：

1. 直接输入新流程名称或文件主题：能否给出正确概览。
2. 选择一个具体环节：步骤、适用岗位/条件和图片是否来自该文档。
3. 检查原文页码；有上市/未上市、内修/外修等条件时，分别测试。

技术校验通过表示转换、入库和抽查通过；新模板的切分质量、业务版本和具体答案仍以原 PDF 核对。
