#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"
docker compose --env-file .env.server -f docker-compose.server.yml logs --tail=200 -f rag-api qdrant

