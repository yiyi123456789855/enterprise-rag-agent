#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

echo "===== RAG Agent ====="
bash deploy/check_direct.sh
echo "===== Qwen vLLM ====="
bash deploy/check_qwen.sh

if command -v nvidia-smi >/dev/null 2>&1; then
  echo "===== GPU ====="
  nvidia-smi --query-gpu=index,name,temperature.gpu,memory.used,memory.total,utilization.gpu \
    --format=csv,noheader
  while IFS= read -r temperature; do
    if [[ "$temperature" =~ ^[0-9]+$ ]] && (( temperature >= 90 )); then
      echo "WARNING: GPU temperature is ${temperature}C. Stop heavy jobs and check cooling before benchmarking."
    fi
  done < <(nvidia-smi --query-gpu=temperature.gpu --format=csv,noheader,nounits)
fi
