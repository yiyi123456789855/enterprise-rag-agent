#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

pid_file="run/rag-agent.pid"
if [[ ! -f "$pid_file" ]]; then
  echo "No PID file was found."
  exit 0
fi

pid="$(cat "$pid_file")"
command_line="$(ps -p "$pid" -o args= 2>/dev/null || true)"
if [[ "$command_line" != *"deploy/run_direct.sh"* && "$command_line" != *"uvicorn app.main:app"* ]]; then
  echo "PID ${pid} does not look like this RAG Agent; it was not stopped."
  exit 1
fi

kill "$pid"
for _ in {1..30}; do
  if ! kill -0 "$pid" 2>/dev/null; then
    rm -f "$pid_file"
    echo "Stopped RAG Agent PID ${pid}."
    exit 0
  fi
  sleep 1
done

echo "RAG Agent PID ${pid} did not stop within 30 seconds. Inspect it before forcing termination."
exit 1
