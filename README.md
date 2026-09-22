# pdf2dify

`pdf2dify` 是现有 `ops-pdf-rag` 解析引擎的可视化生产平台。用户通过浏览器上传 PDF 或指定服务器目录，后台自动执行扫描、原生文字提取、OCR、业务分类、章节 DOCX 构建、质量核查和 Dify 同步。

## 当前能力

- 浏览器上传多个 PDF，或指定本机文件/目录。
- SQLite 持久化任务、文件分类和运行日志。
- 独立 Worker；API 重启不会丢失排队任务。
- 自动业务分类，无法识别时在页面人工选择后继续。
- 阶段检查点、暂停、继续、失败重试和取消。
- 复用 `D:\rag\ops-pdf-rag` 的解析、OCR、DOCX 和 Dify 同步能力。
- 生成按九个业务域加资料导航分类的 `dify-ready.zip`、`manifest.xlsx` 和 HTML 质量报告。
- 配置 Dify Service API，自动创建/映射知识库、增量上传、写元数据并等待索引。

## 安装和启动

```powershell
Set-Location D:\rag\pdf2dify
.\setup.ps1
.\start.ps1
```

浏览器访问 `http://127.0.0.1:8010`。停止服务：

```powershell
.\stop.ps1
```

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

## 分类

输出按财务核算、资金与预算、采购与物资、项目管理、内部交易、油气业务、设备管理、主数据操作和主数据标准九类组织。培训资料按业务内容进入对应业务域，不单独建立培训库。

## 验证

```powershell
.\.venv\Scripts\python.exe -m pytest -q
Set-Location frontend
npm run build
```
