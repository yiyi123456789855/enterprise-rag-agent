#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

pid_file="run/qwen-vllm.pid"
if [[ ! -f "$pid_file" ]]; then
  echo "No Qwen vLLM PID file was found."
  exit 0
fi

pid="$(cat "$pid_file")"
command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
if [[ -z "$command_line" ]]; then
  rm -f "$pid_file"
  echo "Qwen vLLM was not running; removed stale PID file."
  exit 0
fi
if [[ "$command_line" != *"vllm"* ]]; then
  echo "PID ${pid} does not look like vLLM; it was not stopped."
  exit 1
fi

kill "$pid"
for _ in {1..30}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "Stopped Qwen vLLM PID ${pid}."
    exit 0
  fi
  sleep 1
done

echo "Qwen vLLM PID ${pid} did not stop within 30 seconds. Inspect it before forcing termination."
exit 1
