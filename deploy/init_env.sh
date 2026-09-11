#!/usr/bin/env bash
set -euo pipefail

project_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$project_dir"

if [[ -f .env.server ]]; then
  echo ".env.server already exists; no changes were made."
  exit 0
fi

cp .env.server.example .env.server
qdrant_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
postgres_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
redis_password="$(python3 -c 'import secrets; print(secrets.token_urlsafe(36))')"
metrics_token="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
audit_hmac_key="$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"
sed -i "s|change-me-qdrant-key|${qdrant_key}|" .env.server
sed -i "s|change-me-postgres-password|${postgres_password}|g" .env.server
sed -i "s|change-me-redis-password|${redis_password}|g" .env.server
sed -i "s|change-me-metrics-token|${metrics_token}|g" .env.server
sed -i "s|change-me-audit-hmac-key|${audit_hmac_key}|g" .env.server
chmod 600 .env.server
mkdir -p data/secrets
printf '%s' "$metrics_token" > data/secrets/metrics_token
chmod 600 data/secrets/metrics_token

echo "Created .env.server plus monitoring/audit secrets with restrictive permissions."
echo "Set OIDC_ISSUER, OIDC_AUDIENCE, and OIDC_JWKS_URL before deployment."
