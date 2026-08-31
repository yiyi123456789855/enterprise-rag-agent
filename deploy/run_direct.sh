#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -f .env.direct ]]; then
  echo "Missing .env.direct. Run: bash deploy/setup_direct.sh"
  exit 1
fi
if [[ ! -x .venv-server/bin/python ]]; then
  echo "Missing .venv-server. Run: bash deploy/setup_direct.sh"
  exit 1
fi

set -a
source .env.direct
set +a

exec .venv-server/bin/python -m uvicorn app.main:app \
  --host "${APP_BIND_IP:-127.0.0.1}" \
  --port "${APP_PORT:-8000}" \
  --workers 1

