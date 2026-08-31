#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -f .env.server ]]; then
  echo "Missing .env.server."
  exit 1
fi

app_port="$(awk -F= '$1 == "APP_PORT" {print $2}' .env.server | tail -n1)"
app_port="${app_port:-8000}"
docker compose --env-file .env.server -f docker-compose.server.yml ps
echo
curl --fail --show-error --silent "http://127.0.0.1:${app_port}/health"
echo

