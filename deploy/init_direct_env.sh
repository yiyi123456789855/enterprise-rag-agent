#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -f .env.direct ]]; then
  echo ".env.direct already exists; no changes were made."
  exit 0
fi

cp .env.direct.example .env.direct
app_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
sed -i "s|change-me-app-key|${app_key}|" .env.direct
sed -i "s|__PROJECT_DIR__|${project_dir}|g" .env.direct
chmod 600 .env.direct
mkdir -p data-server model-cache logs run

echo "Created .env.direct for: ${project_dir}"
echo "The API key is stored in .env.direct."

