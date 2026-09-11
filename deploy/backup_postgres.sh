#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ ! -f .env.server ]]; then
  echo "Missing .env.server."
  exit 1
fi

set -a
source .env.server
set +a

backup_dir="${BACKUP_DIR:-$project_dir/backups}"
mkdir -p "$backup_dir"
timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
output="$backup_dir/postgres-${timestamp}.dump"

docker compose --env-file .env.server -f docker-compose.server.yml exec -T postgres \
  pg_dump --format=custom --no-owner --username "${POSTGRES_USER:-rag}" "${POSTGRES_DB:-rag}" \
  > "$output"

chmod 600 "$output"
echo "PostgreSQL backup created: $output"
