#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
project_dir="$(realpath "$project_dir")"
cd "$project_dir"

python3 -m py_compile deploy/log_prometheus_alerts.py

service_user="${SUDO_USER:-$USER}"
service_group="$(id -gn "$service_user")"
state_dir="$project_dir/data/monitoring"
rendered_service="$(mktemp)"
trap 'rm -f -- "$rendered_service"' EXIT

mkdir -p "$state_dir"
chmod 700 "$state_dir"

sed \
  -e "s|__RAG_USER__|$service_user|g" \
  -e "s|__RAG_GROUP__|$service_group|g" \
  -e "s|__PROJECT_DIR__|$project_dir|g" \
  deploy/systemd/enterprise-rag-alert-logger.service \
  > "$rendered_service"

sudo install -m 0644 \
  "$rendered_service" \
  /etc/systemd/system/enterprise-rag-alert-logger.service
sudo install -m 0644 \
  deploy/systemd/enterprise-rag-alert-logger.timer \
  /etc/systemd/system/enterprise-rag-alert-logger.timer

sudo systemctl daemon-reload
sudo systemd-analyze verify \
  /etc/systemd/system/enterprise-rag-alert-logger.service \
  /etc/systemd/system/enterprise-rag-alert-logger.timer

echo "Alert logger units installed. Run the service manually before enabling the timer."
