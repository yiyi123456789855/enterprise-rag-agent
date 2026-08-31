#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

set -a
source .env.qwen
set +a

bash deploy/start_qwen.sh

health_url="http://${QWEN_BIND_IP:-127.0.0.1}:${QWEN_PORT:-8001}/health"
echo "Waiting for Qwen vLLM readiness at ${health_url} ..."
for attempt in {1..180}; do
  if curl --fail --silent "$health_url" >/dev/null 2>&1; then
    echo "Qwen vLLM is ready after ${attempt} check(s)."
    bash deploy/start_direct.sh
    echo "The complete RAG stack is running."
    exit 0
  fi
  if [[ -f run/qwen-vllm.pid ]] && ! kill -0 "$(cat run/qwen-vllm.pid)" 2>/dev/null; then
    echo "Qwen vLLM exited during startup. Last log lines:"
    tail -n 80 logs/qwen-vllm.log || true
    exit 1
  fi
  sleep 2
done

echo "Qwen vLLM was not ready within 6 minutes. Inspect logs/qwen-vllm.log."
exit 1
