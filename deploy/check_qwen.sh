#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

set -a
source .env.qwen
set +a

if [[ -f run/qwen-vllm.pid ]]; then
  pid="$(cat run/qwen-vllm.pid)"
  ps -p "$pid" -o pid,etime,%cpu,%mem,cmd || true
fi

base_url="http://${QWEN_BIND_IP:-127.0.0.1}:${QWEN_PORT:-8001}"
curl --fail --show-error --silent "${base_url}/health"
echo

auth_args=()
if [[ -n "${QWEN_API_KEY:-}" ]]; then
  auth_args=(-H "Authorization: Bearer ${QWEN_API_KEY}")
fi
curl --fail --show-error --silent "${base_url}/v1/models" "${auth_args[@]}"
echo
