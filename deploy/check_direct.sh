#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

set -a
source .env.direct
set +a

if [[ -f run/rag-agent.pid ]]; then
  pid="$(cat run/rag-agent.pid)"
  ps -p "$pid" -o pid,etime,cmd || true
fi
curl --fail --show-error --silent "http://127.0.0.1:${APP_PORT:-8000}/health"
echo

