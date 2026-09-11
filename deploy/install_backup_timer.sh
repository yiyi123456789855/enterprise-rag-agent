#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(realpath "$project_dir")"
cd "$project_dir"

bash -n deploy/backup_runtime.sh

service_user="${SUDO_USER:-$USER}"
service_group="$(id -gn "$service_user")"
rendered_service="$(mktemp)"
trap 'rm -f -- "$rendered_service"' EXIT

sed \
  -e "s|__RAG_USER__|$service_user|g" \
  -e "s|__RAG_GROUP__|$service_group|g" \
  -e "s|__PROJECT_DIR__|$project_dir|g" \
  deploy/systemd/enterprise-rag-backup.service \
  > "$rendered_service"

sudo install -m 0644 \
  "$rendered_service" \
  /etc/systemd/system/enterprise-rag-backup.service
sudo install -m 0644 \
  deploy/systemd/enterprise-rag-backup.timer \
  /etc/systemd/system/enterprise-rag-backup.timer

sudo systemctl daemon-reload
sudo systemd-analyze verify \
  /etc/systemd/system/enterprise-rag-backup.service \
  /etc/systemd/system/enterprise-rag-backup.timer

echo "Backup units installed. Run the service manually before enabling the timer."
