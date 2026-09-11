#!/usr/bin/env bash
set -euo pipefail
umask 077

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(realpath "$project_dir")"
cd "$project_dir"

backup_root="$project_dir/backups/automatic"
mkdir -p "$backup_root" "$project_dir/run"
backup_root="$(realpath "$backup_root")"

if [[ "$backup_root" != "$project_dir/backups/automatic" ]]; then
  echo "Backup directory validation failed: $backup_root" >&2
  exit 1
fi

exec 9>"$project_dir/run/backup.lock"
if ! flock -n 9; then
  echo "Another backup is already running; skipping this invocation."
  exit 0
fi

if [[ ! -f .env.server ]]; then
  echo "Missing $project_dir/.env.server" >&2
  exit 1
fi

set -a
source .env.server
set +a

timestamp="$(date -u +%Y%m%dT%H%M%SZ)"
final_dir="$backup_root/backup-$timestamp"
work_dir="$(mktemp -d "$backup_root/.backup-$timestamp.XXXXXX")"

cleanup() {
  if [[ -n "${work_dir:-}" && -d "$work_dir" ]]; then
    rm -rf -- "$work_dir"
  fi
}
trap cleanup EXIT

compose=(
  docker compose
  --env-file .env.server
  -f docker-compose.server.yml
)

"${compose[@]}" up -d postgres qdrant

postgres_container="$("${compose[@]}" ps -q postgres)"
if [[ -z "$postgres_container" ]]; then
  echo "PostgreSQL container was not found." >&2
  exit 1
fi

postgres_ready=false
for _ in $(seq 1 60); do
  if [[ "$(docker inspect -f '{{.State.Health.Status}}' "$postgres_container" 2>/dev/null || true)" == "healthy" ]]; then
    postgres_ready=true
    break
  fi
  sleep 2
done
if [[ "$postgres_ready" != "true" ]]; then
  echo "PostgreSQL did not become healthy within 120 seconds." >&2
  exit 1
fi

"${compose[@]}" exec -T postgres sh -lc '
  PGPASSWORD="$POSTGRES_PASSWORD" \
  pg_dump \
    -h 127.0.0.1 \
    -U "$POSTGRES_USER" \
    -d "$POSTGRES_DB" \
    -Fc
' > "$work_dir/postgres.dump"

test -s "$work_dir/postgres.dump"

qdrant_port="${QDRANT_LOCAL_PORT:-6333}"
collection="${QDRANT_COLLECTION:-enterprise_knowledge}"
qdrant_base_url="http://127.0.0.1:${qdrant_port}"

qdrant_ready=false
for _ in $(seq 1 60); do
  if curl --noproxy '*' -fsS \
    -H "api-key: ${QDRANT_API_KEY}" \
    "$qdrant_base_url/readyz" >/dev/null; then
    qdrant_ready=true
    break
  fi
  sleep 2
done
if [[ "$qdrant_ready" != "true" ]]; then
  echo "Qdrant did not become ready within 120 seconds." >&2
  exit 1
fi

curl --noproxy '*' -fsS \
  -X POST \
  -H "api-key: ${QDRANT_API_KEY}" \
  "$qdrant_base_url/collections/${collection}/snapshots" \
  > "$work_dir/qdrant-create.json"

snapshot_name="$(
  python3 - "$work_dir/qdrant-create.json" <<'PY'
import json
import sys

with open(sys.argv[1], encoding="utf-8") as file:
    response = json.load(file)

if response.get("status") != "ok":
    raise SystemExit("Qdrant snapshot creation failed")

name = response.get("result", {}).get("name")
if not name:
    raise SystemExit("Qdrant response did not include a snapshot name")

print(name)
PY
)"

curl --noproxy '*' -fsS \
  -H "api-key: ${QDRANT_API_KEY}" \
  -o "$work_dir/$snapshot_name" \
  "$qdrant_base_url/collections/${collection}/snapshots/${snapshot_name}"

test -s "$work_dir/$snapshot_name"

curl --noproxy '*' -fsS \
  -X POST \
  -H "api-key: ${QDRANT_API_KEY}" \
  -H 'Content-Type: application/json' \
  -d '{"exact":true}' \
  "$qdrant_base_url/collections/${collection}/points/count" \
  > "$work_dir/qdrant-count.json"

if [[ -f evaluation/server_acceptance_report.json ]]; then
  cp -p evaluation/server_acceptance_report.json \
    "$work_dir/server_acceptance_report.json"
fi

{
  date -u '+created_at=%Y-%m-%dT%H:%M:%SZ'
  echo "hostname=$(hostname)"
  echo "collection=$collection"
  echo "snapshot=$snapshot_name"
  echo "api=$(systemctl is-active enterprise-rag-api.service || true)"
  echo "worker=$(systemctl is-active enterprise-rag-worker.service || true)"
  echo "qwen=$(systemctl is-active enterprise-rag-qwen.service || true)"
} > "$work_dir/metadata.txt"

(cd "$work_dir" && sha256sum -- * > SHA256SUMS)

mv "$work_dir" "$final_dir"
work_dir=""

curl --noproxy '*' -fsS \
  -X DELETE \
  -H "api-key: ${QDRANT_API_KEY}" \
  "$qdrant_base_url/collections/${collection}/snapshots/${snapshot_name}" \
  >/dev/null

find "$backup_root" \
  -mindepth 1 \
  -maxdepth 1 \
  -type d \
  -name 'backup-*' \
  -mtime +14 \
  -print \
  -exec rm -rf -- {} +

echo "Backup completed: $final_dir"
du -sh "$final_dir"
