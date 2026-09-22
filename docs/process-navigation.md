# 按流程名称问答

用户可以直接输入“财务月结”“财务月结业务流程”或某份手册的主题。系统先定位整份资料，返回原文支持的流程概览或章节范围，再引导选择具体环节。具体事务码、报错和操作问题仍使用原来的九个业务知识库。

2026-09-21 已发布到现有应用版本 **#9**。257 张导航卡全部完成索引，远端审计无缺项；名称来源为 219 份封面名称与 38 份文件主题，涵盖 4,074 项章节及 160 处原流程图引用。这些引用来自已有原图，不代表新增 160 张不同图片。

## 本次问题与修复

实际复现了两种失败：

- “财务月结业务流程”主要命中多份分册首页，机器人误以为缺少正文。原始《0.财务月结操作手册.pdf》实际有 152 页，包含多个业务环节。
- “油气田单元创建流程”被分到油气销售库，虽然主数据库已经有对应手册，仍回答没有依据。

新增独立的 **ERP运维-流程导航-全量演示** 私有知识库。它是九个业务库的导航层，不重复上传整批 PDF。每份 PDF 对应一张导航卡，保留源文件哈希、名称来源、完整章节及页码，并摘录原有流程说明、步骤表和流程图。

本地目录覆盖 257 份 PDF：219 份提取到封面流程名称，38 份通过文件名建立主题。文件名和封面名称都用于定位。封面名称可能在不同分册重复使用，所以选择时优先核对文件主题；不同条件或版本无法确定时给出真实候选让用户选择。

综合手册的目录顺序不等于每项都必须执行的业务顺序。财务月结概览会保留维修工单、项目成本、制造费用、主营及其他业务成本、油气生产成本和输油输气月结等章节，上市/未上市分支分别解释。没有正文依据的环节只介绍覆盖范围，不生成具体步骤。

PDF、原图和 OCR 均沿用本地处理结果。云端模型仍只有文本输入，视觉关闭。流程导航不改变九个业务库的旧章节过滤和图片溯源方式。

## 演示用例

在 [现有机器人](http://192.168.24.133:8811/installed/25089298-f80f-42e9-95c9-01c75de9c0d7) 开启新对话：

1. “财务月结业务流程”：应显示总册主要环节和页码，再询问想展开哪部分。
2. “展开制造费用分摊，只看上市单位”：应切回具体操作检索，保留上市条件。
3. 新对话“油气田单元创建流程”：应定位主数据创建流程，而非天然气销售。
4. 新对话“设备管理操作手册”：即使未提取到正式流程名称，也应按文件主题给出手册概览。
5. “预算调整流程”：有多个类型时应列出候选并追问，不任意拼接。

也可以接着说“展开第 5 部分”。这里的序号按上一轮回答中的选项解析，不当作原 PDF 的章节编号。详细回答仍只使用实际召回的原文；没有覆盖的部分可以继续细化查询，不要求重复上传已入库手册。

财务具体问答会进一步按原书选择分册及条件章节。例：《制造费用分摊（上市、未上市）》的 `1.1` 为上市、`1.2` 为未上市，子章节继承该条件。只有同时确定来源和条件章节，才将检索节点的候选数扩大到 20；普通节点仍为 6。财务知识库的底层候选数也设为 20，否则即使节点设为 20，仍可能在第一阶段只取到 6 个子块，合并父文档后遗漏环节。该行为已核对 [Dify 1.17.1 的检索实现](https://github.com/langgenius/dify/blob/1.17.1/api/core/rag/retrieval/dataset_retrieval.py)。

## 更新与恢复

原 PDF 改动后，先完成原有清点、OCR、全量章节构建与校验，再执行：

```powershell
Set-Location D:\rag\ops-pdf-rag
.\.venv\Scripts\python.exe scripts/process_navigation.py build
.\.venv\Scripts\python.exe scripts/process_navigation.py setup
.\.venv\Scripts\python.exe scripts/process_navigation.py upload --workers 2
.\.venv\Scripts\python.exe scripts/complete_process_navigation.py
.\.venv\Scripts\python.exe scripts/evaluate_process_navigation.py
.\.venv\Scripts\python.exe scripts/configure_finance_retrieval.py
.\.venv\Scripts\python.exe scripts/evaluate_finance_scope.py
.\.venv\Scripts\python.exe scripts/build_full_chatflow.py
```

总控等待已有索引完成后更新内容已改变的导航卡，避免修改正在索引的文档。只运行一个导航同步总控。最终审计检查每张导航卡的全部章节、页码、来源元数据及图片数量。移除来源时，先完整构建和同步替代内容，再用 `process_navigation.py retire-stale` 查看旧卡，确认后 `--apply` 标记失效，保留原记录。

在现有应用导入 `dify/chatflow-full.yml` 覆盖草稿，检查清单无错误后预览、发布并用上述问题回归。原 #6 工作流保存在 `dify/chatflow-full-v6.yml`，可用于回退；导航库与业务库回执隔离。

## 证据位置

- `data/process-navigation/catalog.json`：可追溯的名称、别称、章节和说明摘录。
- `data/process-navigation/full-export/manifest.json`：当前 257 张导航卡的导入清单。
- `data/process-navigation/dify/full-state.json`：导航库及逐文档同步回执。
- `data/reports/process-navigation-status.json`：当前内容匹配与索引状态。
- `data/reports/process-navigation-audit.json`：全量远端内容审计，由总控成功完成时生成。
- `data/reports/process-navigation-retrieval.json`：五个来源限定的检索用例；流程名称选择和答案另用真实页面验证。
- `data/reports/finance-branch-retrieval.json`：上市、未上市及未指定条件三组过滤验证；上市实际返回五个操作章节，未上市返回六个，互不混用。
- `data/reports/finance-retrieval-settings.json`：财务知识库候选数调整前后回执，保留原设置供恢复。
- `data/reports/process-baseline-month-close.txt`、`process-baseline-oilfield.txt`：修复前的真实失败。

37 项代码测试通过，来源限定的导航检索用例 5/5、财务条件过滤 3/3 通过。页面验证涵盖正式流程名、简称、无封面名称、多个候选、虚构名称、短手册正文和连续追问。完整性和功能抽查分别记录，不以检索命中率代替业务答案准确率。

实现采用 Dify 的完整父文档返回与元数据过滤，具体机制参考 [官方父子检索说明](https://dify.ai/blog/introducing-parent-child-retrieval-for-enhanced-knowledge) 和 [知识检索节点文档](https://github.com/langgenius/dify-docs/blob/main/en/cloud/use-dify/nodes/knowledge-retrieval.mdx)。目录命中、索引完整性和功能抽查均不能代替业务适用性审批。
