#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -f .env.server ]]; then
  echo ".env.server already exists; no changes were made."
  exit 0
fi

cp .env.server.example .env.server
app_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
qdrant_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
sed -i "s|change-me-app-key|${app_key}|" .env.server
sed -i "s|change-me-qdrant-key|${qdrant_key}|" .env.server
chmod 600 .env.server

echo "Created .env.server with random API keys."
echo "Review the file before deployment: nano .env.server"

