# PDF 运维问答工程

**当前全量成果：** 257 份 PDF、5,244 页全部完成本地 OCR，0 失败页；4,840 个图文条目已全部入库并完成索引，分布在九个业务主题库。8,084 处原图引用、4,561 条检索子块及来源元数据通过远端逐条核查。工作流 #6 已发布：[登录后演示入口](http://192.168.24.133:8811/installed/25089298-f80f-42e9-95c9-01c75de9c0d7)。

入口、真实进度、续跑和验收边界见 [全量图文演示说明](docs/full-demo.md)。知识库 API 密钥已按授权保存在本机 `.env`；29 项代码测试通过。下文保留前期试点说明，其中“未创建 API 密钥”“API 尚未实测”等只代表试点当时状态。

已在本机完成可运行试点，并接入 Dify 1.17.1。原始 PDF 只读；PDF 渲染、截图裁切和 OCR 全部在本机运行。Dify 中的 DeepSeek 模型接收用户问题及检索到的文字。

2026-09-16 图文更新：已将 44 条问答改为图文入库，其中 43 条含原文截图，共 77 张图片。图片由 Dify 自身存储，回答可显示并点击放大。原 TXT 文档已禁用并保留回退。详见 [图文接入说明](docs/images.md)。

## 直接查看结果

- [Dify 试点机器人](http://192.168.24.133:8811/app/f21b0820-5104-4b75-ac5a-fd9c272758c6/workflow)：点击右上角“预览”即可问答，当前为未发布草稿。
- [Dify 试点知识库](http://192.168.24.133:8811/datasets/6b748dc2-dd03-4b0a-8eb8-23e186153658/documents)：44 条完整问答已完成索引。
- [50 页原图与 OCR 对照报告](data/reports/pilot-review.html)：本机浏览器打开，左右核对原图、正文和截图识别结果。
- [待复核事项](docs/review-queue.md)、[实施与验收状态](docs/status.md)。

当前处理路径为：PDF 清点 → 原生文字与本地截图 OCR → 保留页码和坐标的证据 → 按业务问题整理卡片 → 校验与复核 → Dify 检索 → 按证据回答。

## 已完成的范围

| 工作 | 实际结果 |
|---|---|
| 全库清点 | 257 份 PDF，5,244 页，约 670 MiB |
| 全库原生文字提取 | 257 份、5,244 页；不代表截图内容全部识别 |
| 试点 OCR | 50 页、91 张截图，35,003 个 OCR 字符 |
| 装饰图处理 | 按人工核对的图片哈希排除 5 类 logo/背景；小图保留待审记录 |
| FAQ 整理 | 50 条抽取式草稿，原文字段溯源校验无错误 |
| Dify 入库 | 44 条；另 6 条因截图依赖或原文事务码疑点排除 |
| 跨页流程 | 6 份流程证据包，保留前后页和截图，待复核，未入库 |
| 离线评测 | 60 个用例；40 个可回答问题的 BM25 检索 hit@1=39/40、hit@5=40/40 |

以上命中率是本地检索基线，不能当作 Dify 回答准确率。业务适用版本尚未由业务负责人确认。

## 本机运行

已安装 Python 虚拟环境，可直接在 PowerShell 中运行：

```powershell
Set-Location D:\rag\ops-pdf-rag
.\scripts\run-pilot.ps1
```

脚本依次清点、生成试点任务、提取文字、OCR、生成卡片及流程包、导出、生成报告、做离线评测。重复运行会跳过内容和配置未变化的已完成 OCR 页；源文件改变会阻止旧证据被重用。失败页面会记录并返回非零退出码，可在修复后续跑。

**当前 `cards` 和 `procedures` 是草稿生成器，会重新生成对应文件。业务修改请先保存在独立复核记录中，不要把唯一修订直接写在生成物上。**

新机器需 Python 3.11+（当前实测 3.12），先运行 `.\scripts\setup.ps1`。安装依赖需要访问常规 Python 包源；OCR 不调用云端服务。锁定版本见 `requirements.lock.txt`。PaddleOCR 的 layout 可选依赖尚未安装、未集成验证，当前实际引擎为 RapidOCR ONNX CPU。

常用命令：

```powershell
# 全库原生文字提取（本次已完成）
.\.venv\Scripts\python.exe -m ops_rag.cli native --all
# 生成全库 OCR 清单；不会直接执行
.\.venv\Scripts\python.exe -m ops_rag.cli plan --full
# 按清单处理，支持断点续跑；limit 用于分批
.\.venv\Scripts\python.exe -m ops_rag.cli process --manifest data/full-manifest.json --limit 100
# 本地词法检索，仅用于排查卡片覆盖
.\.venv\Scripts\python.exe -m ops_rag.cli search '凭证冲销原因01和02'
# 验证与评测
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ops_rag.cli evaluate
```

全量截图 OCR 与全量业务卡片整理尚未完成。通用手册不能直接套用当前“财务 FAQ 标签”抽取器；先按目录建立流程边界，结合前后页复核步骤、图片箭头和表格关系，再扩展知识卡片。

## Dify 当前配置

实际模型为 `langgenius/deepseek/deepseek` 下的 `deepseek-v4-flash`；向量模型为本地 Ollama 的 `nomic-embed-text:latest`。当前环境未配置重排模型，因此没有启用 Rerank。知识库使用高质量索引、混合检索，向量/关键词权重 0.7/0.3，Top K=5，未启用分数阈值；这些是试点起点，需要用业务评测调参。

这批 FAQ 使用普通分段模式，一个完整问题与答案作为一段。TXT 的自定义分隔符为 `<OPS_CARD_BOUNDARY>`，分段上限 1024 字符（最长卡片 381），UI 重叠设为最低可用值 1。关闭空白清洗、网址清洗、自动问答生成，避免改变原文。跨页长流程后续采用父子分段，需要单独建立知识库和验收。

工作流为：问题理解与多轮指代补全 → 判断是否缺少关键条件 → 追问，或检索 → 核对适用条件后回答并给出原 PDF 页码。结构化输出使用 Dify 内置能力，无代码节点。

`dify/chatflow-pilot.yml` 可导入或作为迁移备份。修改提示词后，重新生成 DSL，再在**试点应用**“更多操作 → 导入 DSL”更新：

```powershell
.\.venv\Scripts\python.exe scripts/build_chatflow.py --dataset-id 6b748dc2-dd03-4b0a-8eb8-23e186153658
```

本次发现服务器代码沙箱报 `DifySeccomp` 错误，已通过去掉代码节点让机器人正常运行，没有更改服务器安全配置。其他应用的代码节点是否可用仍需单独排查。

## 导出、增量同步与图片

`export --include-drafts` 仅供试点，仍排除存在复核疑点的卡片；不带该参数只导出 `business_review=approved` 且无错误/疑点的卡片。当前尚无已完成业务审批的卡片。

当前使用浏览器登录态完成 TXT 入库与 Chatflow 测试，未创建 API 密钥。`.env` 中密钥保持为空；`LLM_*` 是预留字段，当前没有本地云模型归纳器。不要把密钥填到聊天或提交到仓库。

按卡片 API 同步是另一种可选入库方式，需在 `.env` 配置知识库 API 密钥，并指向**另一个普通分段知识库**；不要与现有 TXT 合集重复入库。`dify-sync` 默认只打印计划，`dify-sync --apply` 才提交。同步按卡片名称与内容哈希增量更新、不自动删除文档；提交成功不等于索引完成，需要在 Dify 检查状态。API 适配经过模拟测试，尚未在当前实例用密钥实测。

本地图片保存在 `data/assets`，原始 PDF 页码、截图 ID、坐标、OCR 置信度保存在 `data/parsed`。当前使用保留嵌入图片的 DOCX 导入包，Dify 自动生成自身文件链接，回答节点保留命中卡片的图片 Markdown；不需要 `ASSET_BASE_URL` 或另开图片服务。云模型视觉输入仍关闭，模型仅复制文字中的配图链接，不读取图片做云端 OCR。截图中的示例值、红框和箭头仍需与实际业务核对。

## 工程结构

```text
config.yaml             原始 PDF、试点页码、OCR 参数、已核对装饰图哈希
src/ops_rag/             清点、OCR、溯源卡片、导出、同步、评测命令
scripts/                初始化、一键试点、Chatflow 生成器
prompts/                问题整理和依据资料回答的提示词
dify/                   可导入 Chatflow DSL
evaluation/cases.yaml   60 个评测用例和检查点
tests/                  溯源、分页、检索、同步和工作流兼容性测试
data/inventory.json     PDF 文件清单与 SHA256
data/native/            全库逐页原生文字
data/parsed/            试点逐页 OCR 与证据坐标
data/assets/            本机原页和截图 PNG
data/cards/             FAQ JSON 和 Markdown 草稿
data/procedure-packets/ 跨页流程证据包
data/export/            Dify TXT 与纳入/排除清单
data/reports/           对照 HTML、处理与评测结果
```

原始资料、生成的业务内容、虚拟环境及 `.env` 已加入 `.gitignore`。项目尚未提交到远程仓库。
