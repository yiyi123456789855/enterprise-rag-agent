#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
mkdir -p logs
touch logs/qwen-vllm.log
tail -n 100 -f logs/qwen-vllm.log
