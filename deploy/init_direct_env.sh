#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -f .env.direct ]]; then
  echo ".env.direct already exists; no changes were made."
  exit 0
fi

cp .env.direct.example .env.direct
sed -i "s|__PROJECT_DIR__|${project_dir}|g" .env.direct
chmod 600 .env.direct
mkdir -p data-server model-cache logs run

echo "Created .env.direct for: ${project_dir}"
echo "Set OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL before startup."
