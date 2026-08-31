# v0.3.0 Portfolio Hardening Upgrade

该增量版本不会包含或覆盖 `.env.direct`、`.env.qwen`、`data-server`、`model-cache`、`logs` 和 `run`。

## 安装

在服务器项目目录外解压：

```bash
cd /home/xyl/ly
tar -xzf rag-portfolio-hardening-v9.tar.gz -C enterprise-rag-agent
cd enterprise-rag-agent
chmod +x deploy/*.sh
```

首次使用 Qwen 管理脚本时：

```bash
cp .env.qwen.example .env.qwen
sed -i "s|__PROJECT_DIR__|$PWD|g" .env.qwen
chmod 600 .env.qwen
```

编辑 `.env.qwen` 的 `QWEN_API_KEY`，并确保 `.env.direct` 中的 `LLM_API_KEY` 与它一致。已有 `.env.qwen` 时不要重复复制。

## 检查脚本语法

```bash
for file in deploy/*.sh; do bash -n "$file" || exit 1; done
```

## 启停完整栈

```bash
bash deploy/stop_direct.sh
bash deploy/start_stack.sh
bash deploy/check_stack.sh
```

如果端口8001上已有手工启动且健康的 vLLM，`start_stack.sh` 会复用它，不会启动第二个模型进程；由于脚本没有该进程的PID所有权，后续 `stop_stack.sh` 也不会擅自终止它。

停止完整栈：

```bash
bash deploy/stop_stack.sh
```

## 重新生成 A/B 报告

```bash
.venv-server/bin/python evaluation/compare_acceptance_reports.py \
  --baseline evaluation/baselines/server_acceptance_extractive_summary.json \
  --candidate evaluation/baselines/server_acceptance_qwen_summary.json \
  --output evaluation/baselines/server_acceptance_ab.md
```

## 重新验收

```bash
set -a
source .env.direct
set +a
export NO_PROXY=127.0.0.1,localhost
export no_proxy=127.0.0.1,localhost
.venv-server/bin/python evaluation/run_server_acceptance.py \
  --base-url http://127.0.0.1:8000 \
  --tenant demo-company \
  --output evaluation/server_acceptance_report-qwen-v9.json
```
