# Ubuntu 服务器部署与 VS Code Remote-SSH 使用手册

本方案面向个人作品集、实验室服务器或小型内部知识库：API、BGE-M3 和 Qdrant 都在远程 Ubuntu 服务器运行，本地电脑只负责通过 VS Code 编辑代码和端口转发，因此不需要在本机加载模型。

如果是共享服务器、没有 sudo 权限或不允许安装 Docker，请优先使用第 5 节的“免 Docker GPU 部署”。它使用项目独立虚拟环境和嵌入式持久化 Qdrant，不修改系统服务。

## 1. 部署架构

```text
本地浏览器
    │ VS Code SSH 端口转发：localhost:8000
    ▼
远程 rag-api 容器（FastAPI + BGE-M3）
    ├── SQLite：文档、切片、任务、问答记录
    ├── Qdrant：BGE-M3 向量和权限 Payload
    └── 可选 Qwen/OpenAI 兼容模型服务
```

服务器默认只监听 `127.0.0.1:8000` 和 `127.0.0.1:6333`。外网只需要开放 SSH 端口，不要直接暴露 Qdrant。应用接口另外使用 `X-API-Key` 保护。

## 2. 推荐服务器配置

CPU 模式建议至少：

- Ubuntu 22.04/24.04；
- 8 核 CPU、16 GB 内存；
- 30 GB 可用磁盘；
- 可以访问 Hugging Face 下载 BGE-M3。

GPU 模式建议：

- NVIDIA GPU，显存 8 GB 以上；
- 已安装 NVIDIA 驱动；
- 已安装 NVIDIA Container Toolkit，执行 `docker run --rm --gpus all nvidia/cuda:12.4.1-base-ubuntu22.04 nvidia-smi` 能看到显卡。

如果服务器无法访问 Hugging Face，需要预先下载模型并挂载本地模型目录，再把 `EMBEDDING_MODEL` 改为容器内路径。

## 3. 用 VS Code 连接服务器

1. 本机 VS Code 安装扩展 `Remote - SSH`。
2. 按 `Ctrl+Shift+P`，运行 `Remote-SSH: Open SSH Configuration File`。
3. 在配置文件中填写：

```ssh-config
Host rag-server
    HostName 你的服务器IP
    User ubuntu
    IdentityFile C:\Users\90404\.ssh\id_ed25519
    ServerAliveInterval 60
```

4. 再次按 `Ctrl+Shift+P`，选择 `Remote-SSH: Connect to Host` → `rag-server`。
5. 连接成功后，VS Code 左下角会显示 `SSH: rag-server`，此时打开的是服务器文件系统和服务器终端。

官方说明：<https://code.visualstudio.com/docs/remote/ssh>

## 4. 把项目传到服务器

推荐把本项目提交到自己的 GitHub 仓库，然后在 VS Code 远程终端执行：

```bash
cd ~
git clone 你的仓库地址 enterprise-rag-agent
cd enterprise-rag-agent
```

如果暂时不使用 GitHub，可以将生成的 `enterprise-rag-agent-server.tar.gz` 拖到 VS Code 远程资源管理器的用户目录，然后执行：

```bash
cd ~
tar -xzf enterprise-rag-agent-server.tar.gz
cd enterprise-rag-agent
```

不要上传本机的 `.venv`、`data` 或模型缓存，它们不能跨 Windows/Linux 直接复用。

## 5. 免 Docker GPU 部署（共享服务器推荐）

此方式不需要 sudo。确认 `python3 -m venv --help` 可以运行后，在项目目录执行：

```bash
cd ~/enterprise-rag-agent
chmod +x deploy/*.sh
bash deploy/setup_direct.sh
bash deploy/start_direct.sh
bash deploy/logs_direct.sh
```

`setup_direct.sh` 会创建 `.venv-server`，安装 CUDA 12.4 版 PyTorch、BGE-M3 相关依赖和 Qdrant Python 客户端。首次启动时模型下载到项目的 `model-cache`，文档及向量保存在 `data-server`。

查看状态：

```bash
bash deploy/check_direct.sh
```

停止服务：

```bash
bash deploy/stop_direct.sh
```

嵌入式 Qdrant 仅允许一个应用进程，因此脚本固定使用一个 Uvicorn worker。这适合个人演示和小型知识库；多人高并发或正式生产环境应使用下面的 Docker/Qdrant 独立服务方案。

### 5.1 启用二阶段语义重排

默认先使用轻量词法重排，确保首次部署稳定。RTX 4090 可以在 `.env.direct` 中启用 CrossEncoder：

```dotenv
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=cuda
RERANK_CANDIDATES=20
```

然后重启：

```bash
bash deploy/stop_direct.sh
bash deploy/start_direct.sh
bash deploy/logs_direct.sh
```

首次启用会下载重排模型。启用后 `/health` 的 `reranker` 字段应显示模型名称。共享 GPU 显存紧张时将 `RERANKER_ENABLED` 改回 `false`。

### 5.2 升级已有直部署实例

升级前保留 `.env.direct`、`data-server` 和 `model-cache`。新代码中的 SQLite 初始化会自动增加会话、耗时和反馈字段，不需要删除数据库或重新上传文档。更新代码后执行：

```bash
cd /home/xyl/ly/enterprise-rag-agent
bash deploy/stop_direct.sh
.venv-server/bin/python -m pip install -e ".[server]"
bash deploy/start_direct.sh
bash deploy/check_direct.sh
```

若修改了 Embedding 模型或向量维度，应使用新的 Qdrant Collection 名称并重新索引；普通 Python、前端和门控规则更新不需要重建向量。

### 5.3 启动本地 Qwen2.5 + vLLM 完整栈

首次配置独立模型环境：

```bash
cd /home/xyl/ly/enterprise-rag-agent
python3 -m venv .venv-llm
.venv-llm/bin/python -m pip install --upgrade pip
.venv-llm/bin/python -m pip install vllm
cp .env.qwen.example .env.qwen
sed -i "s|__PROJECT_DIR__|$PWD|g" .env.qwen
chmod 600 .env.qwen
```

编辑 `.env.qwen`，替换 `QWEN_API_KEY`。然后在 `.env.direct` 中配置同一个密钥：

```dotenv
LLM_BASE_URL=http://127.0.0.1:8001/v1
LLM_API_KEY=与QWEN_API_KEY一致
LLM_MODEL=Qwen/Qwen2.5-3B-Instruct
```

一键启动、检查、停止完整栈：

```bash
bash deploy/start_stack.sh
bash deploy/check_stack.sh
bash deploy/stop_stack.sh
```

也可以分别管理服务：

```bash
bash deploy/start_qwen.sh
bash deploy/logs_qwen.sh
bash deploy/check_qwen.sh
bash deploy/stop_qwen.sh
```

`start_stack.sh` 会等待 vLLM 健康检查通过后再启动 RAG API。`check_stack.sh` 同时检查两个端口并显示GPU温度；温度达到90°C时会给出警告，此时不要继续跑密集压测，应先停止无关GPU任务并检查散热。

## 6. Docker 部署：安装服务器前置环境

服务器需要 Docker Engine 和 Docker Compose 插件。按照 Docker 官方 Ubuntu 安装文档完成安装：

<https://docs.docker.com/engine/install/ubuntu/>

验证：

```bash
docker --version
docker compose version
```

如果当前用户没有 Docker 权限，可以将用户加入 `docker` 组并重新登录；不要长期依赖 `sudo docker` 与普通用户混用数据目录。

GPU 部署还需要 NVIDIA Container Toolkit：

<https://docs.nvidia.com/datacenter/cloud-native/container-toolkit/latest/install-guide.html>

## 7. Docker 部署：初始化配置

在 VS Code 远程终端执行：

```bash
cd ~/enterprise-rag-agent
chmod +x deploy/*.sh
bash deploy/init_env.sh
nano .env.server
```

`init_env.sh` 会生成随机的 `APP_API_KEY` 和 `QDRANT_API_KEY`，并把 `.env.server` 权限设置为仅当前用户可读写。

CPU 服务器保持：

```dotenv
EMBEDDING_DEVICE=cpu
```

GPU 服务器会由 GPU Compose 覆盖为：

```dotenv
EMBEDDING_DEVICE=cuda
```

如有独立 Qwen 服务，再填写：

```dotenv
LLM_BASE_URL=http://你的模型服务:端口/v1
LLM_API_KEY=模型服务密钥
LLM_MODEL=模型名称
```

不填写 LLM 时仍可运行，系统使用严格基于证据的抽取式回答。

如需 Docker 模式语义重排，再设置：

```dotenv
RERANKER_ENABLED=true
RERANKER_MODEL=BAAI/bge-reranker-v2-m3
RERANKER_DEVICE=cpu   # 使用 GPU Compose 时改为 cuda
RERANK_CANDIDATES=20
```

## 8. Docker 部署：一键启动

CPU 模式：

```bash
bash deploy/deploy.sh
```

GPU 模式：

```bash
bash deploy/deploy.sh --gpu
```

第一次部署需要构建镜像并下载 BGE-M3，时间取决于服务器网络。查看日志：

```bash
bash deploy/logs.sh
```

出现以下内容表示 API 已启动：

```text
Application startup complete.
Uvicorn running on http://0.0.0.0:8000
```

检查容器和健康状态：

```bash
bash deploy/check.sh
```

正常结果应包含：

```json
{
  "status": "ok",
  "details": {
    "database": "ready",
    "retrieval_backend": "qdrant",
    "vector_index": "ready"
  }
}
```

## 9. 在本机打开服务器应用

由于服务仅绑定服务器回环地址，需要使用 VS Code 转发：

1. 打开 VS Code 底部的“端口/Ports”面板；
2. 点击“转发端口/Forward a Port”；
3. 输入 `8000`；
4. 在本地打开 <http://127.0.0.1:8000/> 使用知识库操作页面；接口调试页面为 <http://127.0.0.1:8000/docs>。

主页顶部可以直接填写 API Key；使用 Swagger 时点击右上角 `Authorize`。密钥来自 `.env.server`，也可以在远程终端查看：

```bash
grep '^APP_API_KEY=' .env.server
```

## 10. 导入文档和提问

在主页中可以直接上传文档并提问。如果使用 Swagger，依次操作：

1. `POST /api/v1/documents`：上传 PDF、DOCX、TXT 或 Markdown；
2. `GET /api/v1/jobs/{job_id}`：确认状态变为 `completed`；
3. `POST /api/v1/chat`：填写问题、租户和用户部门；
4. 检查答案是否包含引用、原文片段、文件名和页码。

旧 SQLite 数据迁移到 Qdrant 时运行：

```bash
docker compose --env-file .env.server -f docker-compose.server.yml exec rag-api \
  python scripts/reindex.py --batch-size 32
```

## 11. 常用维护命令

查看状态：

```bash
docker compose --env-file .env.server -f docker-compose.server.yml ps
```

查看日志：

```bash
bash deploy/logs.sh
```

停止但保留数据：

```bash
bash deploy/stop.sh
```

重新部署新代码：

```bash
git pull
bash deploy/deploy.sh          # CPU
# 或 bash deploy/deploy.sh --gpu
```

不要运行 `docker compose down -v`，其中 `-v` 会删除 SQLite、Qdrant 向量和模型缓存卷。

## 12. 安全与生产边界

- Qdrant 已配置 API Key，并只发布到服务器 `127.0.0.1`。
- FastAPI 已配置 `X-API-Key`；`.env.server` 不得上传 GitHub。
- 当前是单机 Docker Compose，适合作品集、实验室和小型内部使用，不是高可用集群。
- 若要面向公网，应增加 HTTPS 反向代理、正式用户登录/RBAC、速率限制、备份和监控。
- Qdrant 官方建议生产部署配置持久化、高可用、备份和安全策略：<https://qdrant.tech/documentation/installation/>。

## 13. 无法启动时的排查顺序

```bash
docker compose --env-file .env.server -f docker-compose.server.yml ps
docker compose --env-file .env.server -f docker-compose.server.yml logs --tail=200 qdrant
docker compose --env-file .env.server -f docker-compose.server.yml logs --tail=200 rag-api
df -h
free -h
nvidia-smi   # 仅 GPU 服务器
```

常见原因：服务器不能访问 Hugging Face、磁盘不足、GPU 容器运行时未安装、`.env.server` 中密钥仍为占位符、或者 8000 端口已被其他服务占用。
