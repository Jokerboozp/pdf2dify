# pdf2dify

`pdf2dify` 是现有 `ops-pdf-rag` 解析引擎的可视化生产平台。用户通过浏览器上传 PDF 或指定服务器目录，后台自动执行扫描、原生文字提取、OCR、业务分类、章节 DOCX 构建、质量核查和 Dify 同步。

## 当前能力

- 浏览器上传多个 PDF，或指定本机文件/目录。
- SQLite 持久化任务、文件分类和运行日志。
- 当前任务通过事件流更新进度与日志，任务列表按运行状态调整刷新间隔。
- 独立 Worker；API 重启不会丢失排队任务。
- 自动业务分类，无法识别时在页面人工选择后继续。
- 阶段检查点、暂停、继续、失败重试和取消。
- 可删除已停止的任务及其本地上传副本、生成文件；原始来源文件与已同步到 Dify 的内容保留。
- 仓库内置固定版本的 `ops-pdf-rag` 解析引擎；克隆后无需另找源码。
- 生成按预置或自定义业务分类及资料导航整理的 `dify-ready.zip`、`manifest.xlsx` 和 HTML 质量报告。
- 配置 Dify Service API，自动创建或映射知识库、增量上传、写元数据、补检索标题并核查远端索引。
- 自动同步时只为本次导出包含文档的分类创建知识库，避免产生空分类库。
- 同一来源文件更新时，新版本核查通过后停用已被替换的旧文档；同步回执跨任务复用。

## 一条命令启动（Windows、macOS、Linux）

安装 Python 3.11+ 和与仓库内 Vite 版本兼容的 Node.js/npm，进入仓库目录后运行：

```bash
python run.py
```

首次运行会自动创建后端与解析引擎的虚拟环境、安装依赖并构建前端；后续直接启动。浏览器会自动打开 `http://127.0.0.1:8010`，在终端按 `Ctrl+C` 停止。Linux/macOS 如系统只有 `python3` 命令，改用 `python3 run.py`。服务器无图形界面可运行 `python run.py --no-browser`。旧的 PowerShell 脚本仍保留供已有安装使用。

只安装、不启动：`python run.py --install-only`。

开发前端：

```powershell
Set-Location D:\rag\pdf2dify\frontend
npm run dev
```

## 运行结构

```text
Vue Web UI → FastAPI → SQLite task queue → Worker → ops-pdf-rag engine
                                                   ├─ dify-ready.zip
                                                   └─ Dify Service API
```

默认使用仓库内 `engine/ops-pdf-rag` 固定版本，安装脚本会为它创建独立的 Python 环境。可以通过环境变量改为已有的解析引擎：

- `PDF2DIFY_ENGINE_ROOT`
- `PDF2DIFY_ENGINE_PYTHON`
- `PDF2DIFY_DATA_DIR`
- `PDF2DIFY_DATABASE`

Dify API Key 保存在本机 `data/secrets.json`，不会进入前端构建产物或 Git。

## 建议的 Dify 知识库布局

在页面的「Dify 设置」填写 Service API 地址（通常以 `/v1` 结尾）、知识库 API Key、嵌入模型及提供方。默认按业务分类自动创建知识库和一个独立的「资料导航」库，名称以 `pdf2dify-` 开头；也可以在设置中填写已有知识库 ID，一类对应一库。预置九类分别是财务核算、资金与预算、采购与物资、项目管理、内部交易、油气业务、设备管理、主数据操作、主数据标准；自定义分类同样会建立独立知识库。上传知识库应选择高质量索引、父子分段、混合检索；自动同步会按这些参数提交文档。

只想手工上传时，创建「仅导出」任务，下载 `dify-ready.zip`，按压缩包中的分类文件夹把 `.docx` 分别上传到对应知识库；`资料导航/` 上传到单独库。不要把清单、报告或整个 ZIP 当作知识文档上传。压缩包内的 `上传说明.md` 和 `manifest.xlsx` 用于逐类核对。

远端同步需要 Dify 知识库 API 可用，且所配置的嵌入模型在该 Dify 实例中已启用。自动核查仅证明文档、图片引用、页码、元数据和索引状态达到技术条件；内容正确性仍需人工复核。任务输出和同步回执默认留在本机 `data/`，其中可能含敏感原文，不应直接公开。

## 分类

预置财务核算、资金与预算、采购与物资、项目管理、内部交易、油气业务、设备管理、主数据操作和主数据标准九类。页面右上角「分类管理」可新增和改名自定义分类；新分类可用于任务整体归类或逐文件人工归类，并会生成独立的导出文件夹与 Dify 知识库。分类配置保存在本机 `data/categories.json`；分类 ID 不随改名改变。培训资料可以按业务内容进入对应分类，不强制建立培训库。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm run build
```
