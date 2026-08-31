#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
mkdir -p logs run

if [[ ! -f .env.qwen ]]; then
  echo "Missing .env.qwen. Copy .env.qwen.example and replace __PROJECT_DIR__ and the API key."
  exit 1
fi

set -a
source .env.qwen
set +a

pid_file="run/qwen-vllm.pid"
if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "Qwen vLLM is already running with PID ${old_pid}."
    exit 0
  fi
  rm -f "$pid_file"
fi

health_url="http://${QWEN_BIND_IP:-127.0.0.1}:${QWEN_PORT:-8001}/health"
if command -v curl >/dev/null 2>&1 && curl --fail --silent "$health_url" >/dev/null 2>&1; then
  echo "A healthy Qwen-compatible service is already available at ${health_url}."
  echo "It has no project PID file, so this script will reuse it without taking process ownership."
  exit 0
fi

vllm_bin="${VLLM_BIN:-$project_dir/.venv-llm/bin/vllm}"
if [[ ! -x "$vllm_bin" ]]; then
  echo "vLLM executable not found: ${vllm_bin}"
  echo "Create .venv-llm and install vLLM before starting the model service."
  exit 1
fi

export PATH="$project_dir/.venv-llm/bin:$PATH"
export HF_HOME="${HF_HOME:-$project_dir/model-cache/huggingface}"

args=(
  serve "${QWEN_MODEL:-Qwen/Qwen2.5-3B-Instruct}"
  --host "${QWEN_BIND_IP:-127.0.0.1}"
  --port "${QWEN_PORT:-8001}"
  --dtype "${QWEN_DTYPE:-half}"
  --max-model-len "${QWEN_MAX_MODEL_LEN:-4096}"
  --gpu-memory-utilization "${QWEN_GPU_MEMORY_UTILIZATION:-0.35}"
  --max-num-seqs "${QWEN_MAX_NUM_SEQS:-2}"
)

if [[ -n "${QWEN_API_KEY:-}" ]]; then
  args+=(--api-key "$QWEN_API_KEY")
fi
if [[ "${QWEN_ENFORCE_EAGER:-true}" == "true" ]]; then
  args+=(--enforce-eager)
fi

nohup "$vllm_bin" "${args[@]}" > logs/qwen-vllm.log 2>&1 &
new_pid=$!
echo "$new_pid" > "$pid_file"
echo "Started Qwen vLLM with PID ${new_pid} on ${QWEN_BIND_IP:-127.0.0.1}:${QWEN_PORT:-8001}."
echo "Model loading can take several minutes. Follow logs with: bash deploy/logs_qwen.sh"
