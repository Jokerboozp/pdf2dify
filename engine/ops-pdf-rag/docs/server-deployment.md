# Linux + Docker 服务器部署（与 Dify 同机）

> 历史可选方案：正式应用 #11 已使用 Dify 原生混合检索，不需要部署本页的独立检索容器。当前服务器依赖与维护方式见 [原生检索运行与维护](native-dify-operation.md)。以下步骤仅适用于明确恢复独立 BGE 检索服务的场景。

本部署包把现有混合检索服务从 Windows 电脑搬到 Linux 服务器。Dify 仍负责问题路由与回答，独立检索容器负责 BM25、中文向量、BGE 重排和原图。现有 Dify 数据库、知识库和已发布 #10 不会被打包脚本修改。

示例地址使用当前 Dify 主机 `192.168.24.133`。确认 Linux 上 `ip -4 addr` 确实包含此地址；若是另一台机器，请替换下面的 IP。最终是 Dify 和用户浏览器访问 `http://192.168.24.133:8765`，不再访问 Windows 的 `192.168.24.1`。

## 准备条件

- Linux x86_64、已安装 Docker Engine 与 Compose 插件，宿主机能运行 `python3`。
- 这批数据建议为检索额外预留 4 个 CPU、8 GB 内存；同机 Dify 自身的资源另算。Compose 将检索容器限制为 4 CPU / 8 GB，真实并发与耗时需服务器实测；当前服务串行推理，最多接纳 8 个请求（含正在执行者），等待上限 60 秒，超出容量或等待时限才返回 429。
- 建议至少预留 15 GB 磁盘，容纳迁移压缩包、解压数据、依赖与镜像；不是全部 Dify 磁盘需求。
- 首次构建镜像需要访问 Docker 官方 Python 镜像、Debian 软件仓库和 Python 包源。模型已随包携带，运行时离线加载，不下载模型、不向云端 OCR 发送资料。完全断网服务器需先在可联网的 Linux x86_64 构建并用 `docker save` / `docker load` 搬镜像，本包不包含预构建镜像。
- 当前包用于**已转换资料的问答服务**。新增 PDF 继续在 Windows 工程转换、同步导航并建索引，再重新打包更新。包不含原 PDF、OCR 全部中间产物或 Dify 数据库，因此不能用它直接替代整套 PDF 转换工程。

## 1. 在 Windows 生成迁移包

首次交付已生成的文件位于 `D:\rag\ops-pdf-rag\data\deploy`；后续资料有变化时运行：

2026-09-21 并发修复后的包为 `ops-retrieval-server-20260921-queuefix.tar.gz`；之前不带 `queuefix` 的同日首次包仍采用两秒等待，不包含本次修复。

```powershell
Set-Location D:\rag\ops-pdf-rag
.\.venv\Scripts\python.exe scripts/package_retrieval_server.py
```

输出 `ops-retrieval-server-日期时间.tar.gz` 和同名 `.sha256` 文件。只包含当前有效快照、索引清单、模型、被引用原图、源码和部署工具；不包含 `.env`、API 密钥、Windows 虚拟环境及历史无效快照。包内包含内部文档正文和图片，请按内部资料管理。

将这两个文件传到 Linux 服务器，例如 `/opt/ops-retrieval-upload`。可用已有 SFTP 工具；如果有 SSH 账号，也可用 `scp`。此处不假设或创建服务器账号。

## 2. 在 Linux 校验并解压

下面将文件名替换为实际生成的包名；使用一个新的部署目录，不覆盖 Dify 自身目录。

```bash
cd /opt/ops-retrieval-upload
sha256sum -c ops-retrieval-server-日期时间.tar.gz.sha256
mkdir -p /opt/ops-retrieval
tar -xzf ops-retrieval-server-日期时间.tar.gz -C /opt/ops-retrieval
cd /opt/ops-retrieval
python3 verify_bundle.py
```

两个校验都通过后继续。解压目录中可直接看到 `src/ops_rag/hybrid.py`、`search_api.py`、`Dockerfile`、`compose.yaml` 和 `data/`。

## 3. 配置服务器地址并启动

```bash
cd /opt/ops-retrieval
python3 configure.py --url http://192.168.24.133:8765 --bind-ip 192.168.24.133
docker compose config --quiet
docker compose up -d --build
docker compose ps
docker compose logs --tail=80 retrieval
```

`configure.py` 在此目录生成 `.env` 和 `dify/chatflow-server-private.yml`；仅创建服务器检索专用密钥，不需要 Dify 管理员密码或知识库 API 密钥。重复配置会保留既有检索密钥。两份生成文件含该密钥，不要粘贴进聊天或提交到仓库。脚本不会访问 Windows 的 `.env`。

等服务状态变为 `healthy`。首次启动会读入模型和索引，可能需要数十秒。

```bash
curl --fail http://192.168.24.133:8765/health
python3 smoke_test.py
```

应看到健康状态 `ready`，冒烟检查 `passed: true`、`engine: hybrid`、来源第17页且 `image_readable: true`。冒烟脚本真实调用已运行的服务，检查“项目结转后怎么撤销？”排第一的原文及图片，不打印密钥或图片签名。

还需在**使用机器人的浏览器所在电脑**打开 `http://192.168.24.133:8765/health`。如果服务器自测成功但浏览器无法访问，图片仍不能显示；需要让内部使用者和 Dify 容器能访问这个地址。Compose 指定服务器网卡发布端口，不能把 `127.0.0.1` 写给另一个容器或远程浏览器。[Docker 端口映射说明](https://docs.docker.com/engine/network/port-publishing/)

## 4. 将 Dify 切换到服务器检索

从服务器取回 `dify/chatflow-server-private.yml` 到受控本机目录，然后打开现有 Dify 应用的编排页：

1. 先导出当前草稿作为备份。
2. 导入服务器生成的 `chatflow-server-private.yml`，覆盖现有应用草稿。
3. 检查本地检索 HTTP 节点地址已经变为 `http://192.168.24.133:8765/search-form`，检查清单无错误。
4. 预览“项目结转后怎么撤销？”并点击原图；再测“财务月结”和上市/未上市制造费用分摊。
5. 预览成功后“发布 → 发布更新”，在正式入口**开启新对话**再测。确认图文成功后，才停止 Windows 检索服务。

这里复用现有 Dify，因此导航库 ID 和已配置的 DeepSeek 模型不变。若迁移的是整台 Dify 到一个空的新实例，需要另外迁移它的数据库、知识库、文件存储和模型配置；导入检索 DSL 本身不会复制这些数据。

可点击：[当前编排页](http://192.168.24.133:8811/app/c68c4490-aee8-496a-85c7-9f0dd3574168/workflow)、[正式演示入口](http://192.168.24.133:8811/installed/25089298-f80f-42e9-95c9-01c75de9c0d7)。没有可用的服务器登录会话时，Codex 生成部署包不代表已在服务器部署。

## 日常运行、更新和回退

```bash
cd /opt/ops-retrieval
docker compose ps
docker compose logs --tail=100 retrieval
docker compose restart retrieval
# 有意停止服务时使用：
docker compose stop retrieval
```

容器进程退出或 Docker 重启后，`restart: unless-stopped` 会按策略启动；手动 stop 的服务不会因此恢复。Docker 自身需要开机启动。`unhealthy` 状态本身不等于自动重启，检查日志和资源。[Compose 服务配置](https://docs.docker.com/reference/compose-file/services/)

新增资料先按 Windows 工程的新增 PDF 指南同步 Dify 导航、重建本地索引，再生成新包。服务器更新前备份旧部署目录与服务器 `.env`，停止检索容器后完整解压新包（保留 `.env`），运行 `verify_bundle.py` 和相同的 `configure.py` 命令，重新构建启动、冒烟检查，最后导入新 DSL 并发布。不要在正在服务的目录中逐个替换半套索引。回退时恢复旧部署数据和对应 Dify 版本，不能只回退一端。

原图签名一小时有效；切换服务器后旧聊天记录里的 Windows 图片地址不会自动改写，使用新对话重新提问。

## 排错与验收边界

| 现象 | 检查位置 |
|---|---|
| 构建时下载失败 | Docker / Debian / Python 包源的连通性，不是文档或索引损坏 |
| 容器不断重启 | `docker compose logs`；文件完整性、模型缓存、Linux CPU 架构、8 GB 内存限制 |
| HTTP 401 | 服务器 `.env` 与导入 DSL 是否来自同一次 configure；不要打印密钥排查 |
| HTTP 409 | 资料清单和索引不一致，完整重建并重新打包 |
| HTTP 429 | 排队容量已满或等待超过 60 秒；检查是否部署了 queuefix 新包、请求数量和单次推理耗时。配置位于 `retrieval_service`，调整时须同时考虑 Dify 读取超时与内存限制 |
| Dify 503/超时，但服务器健康正常 | Dify HTTP 节点是否仍指向 192.168.24.1；代理、容器网络及服务器端口连通性 |
| 有文字但图片失败 | 用户浏览器是否可达服务器 URL、是否 HTTPS 页面加载 HTTP 图片、链接是否已过期 |

本机验证包括打包内容、哈希、配置工具与现有检索测试；Linux 容器构建、容器到 Dify 的连通、真实用户浏览器图片显示必须在服务器完成。当前 Dockerfile 使用 Python 3.12 Debian 镜像及锁定 Python 依赖；Windows 虚拟环境不能直接搬进 Linux，模型缓存按真实文件打包以避开跨系统符号链接差异。[Hugging Face 缓存说明](https://huggingface.co/docs/huggingface_hub/v1.32.0/guides/manage-cache)
