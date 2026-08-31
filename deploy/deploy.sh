#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if ! command -v docker >/dev/null 2>&1; then
  echo "Docker is not installed. Install Docker Engine and the Compose plugin first."
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "The Docker Compose plugin is not available."
  exit 1
fi
if [[ ! -f .env.server ]]; then
  echo "Missing .env.server. Run: bash deploy/init_env.sh"
  exit 1
fi

compose_args=(--env-file .env.server -f docker-compose.server.yml)
if [[ "${1:-}" == "--gpu" ]]; then
  compose_args+=(-f docker-compose.gpu.yml)
  echo "Starting the GPU deployment profile."
else
  echo "Starting the CPU deployment profile."
fi

docker compose "${compose_args[@]}" up -d --build

app_port="$(awk -F= '$1 == "APP_PORT" {print $2}' .env.server | tail -n1)"
app_port="${app_port:-8000}"
echo "Containers started. BGE-M3 may take several minutes to download on first use."
echo "Check status with: bash deploy/check.sh"
echo "Forward server port ${app_port} in VS Code, then open http://127.0.0.1:${app_port}/docs"

