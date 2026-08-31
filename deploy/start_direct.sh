#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
mkdir -p logs run

pid_file="run/rag-agent.pid"
if [[ -f "$pid_file" ]]; then
  old_pid="$(cat "$pid_file")"
  if kill -0 "$old_pid" 2>/dev/null; then
    echo "RAG Agent is already running with PID ${old_pid}."
    exit 0
  fi
fi

nohup bash deploy/run_direct.sh > logs/rag-agent.log 2>&1 &
new_pid=$!
echo "$new_pid" > "$pid_file"
echo "Started RAG Agent with PID ${new_pid}."
echo "First startup downloads BGE-M3. Follow logs with: bash deploy/logs_direct.sh"

