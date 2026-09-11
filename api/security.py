from __future__ import annotations

import secrets
from functools import lru_cache
from typing import Any

import jwt
from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader, HTTPAuthorizationCredentials, HTTPBearer
from jwt import PyJWKClient

from api.dependencies import get_settings
from app.auth import AuthContext
from app.config import Settings


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)
bearer_scheme = HTTPBearer(auto_error=False)

ADMIN_ROLES = frozenset({"knowledge-admin"})
DOCUMENT_WRITE_ROLES = frozenset({"knowledge-admin", "document-editor"})
METRICS_READ_ROLES = frozenset({"knowledge-admin", "auditor"})


def require_api_key(provided_key: str | None = Security(api_key_header)) -> None:
    """Validate the compatibility API key used only by legacy/demo mode."""

    expected_key = get_settings().app_api_key
    if not expected_key:
        return
    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key",
        )


def get_auth_context(
    credentials: HTTPAuthorizationCredentials | None = Security(bearer_scheme),
    provided_key: str | None = Security(api_key_header),
) -> AuthContext:
    settings = get_settings()
    if settings.auth_mode == "legacy":
        require_api_key(provided_key)
        return AuthContext(
            user_id="",
            tenant_id="",
            authenticated=bool(provided_key),
            legacy=True,
        )

    if credentials is None or credentials.scheme.lower() != "bearer":
        raise _unauthorized("Missing bearer token")
    claims = _decode_oidc_token(credentials.credentials, settings)
    return _claims_to_context(claims, settings)


def require_roles(context: AuthContext, *allowed: str) -> None:
    """Enforce RBAC in OIDC mode while preserving the local legacy workflow."""

    if context.legacy:
        return
    if not context.has_any_role(*allowed):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Required role: one of {', '.join(sorted(allowed))}",
        )


def _decode_oidc_token(token: str, settings: Settings) -> dict[str, Any]:
    try:
        signing_key = _get_jwk_client(settings.oidc_jwks_url).get_signing_key_from_jwt(token)
        return jwt.decode(
            token,
            signing_key.key,
            algorithms=list(settings.oidc_algorithms),
            audience=settings.oidc_audience,
            issuer=settings.oidc_issuer,
            options={"require": ["exp", "iss", "sub"]},
        )
    except jwt.PyJWTError as exc:
        raise _unauthorized("Invalid or expired bearer token") from exc
    except Exception as exc:
        # Identity-provider/JWKS outages fail closed and never fall back to user input.
        raise _unauthorized("Unable to verify bearer token") from exc


def _claims_to_context(claims: dict[str, Any], settings: Settings) -> AuthContext:
    user_id = _required_scalar_claim(claims, "sub")
    tenant_id = _required_scalar_claim(claims, settings.oidc_tenant_claim)
    departments = tuple(_claim_values(claims.get(settings.oidc_departments_claim)))
    roles = frozenset(_claim_values(claims.get(settings.oidc_roles_claim)))
    return AuthContext(
        user_id=user_id,
        tenant_id=tenant_id,
        departments=departments,
        roles=roles,
    )


def _required_scalar_claim(claims: dict[str, Any], name: str) -> str:
    value = claims.get(name)
    if not isinstance(value, str) or not value.strip():
        raise _unauthorized(f"Bearer token is missing required claim: {name}")
    return value.strip()


def _claim_values(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        candidates = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        candidates = value
    else:
        raise _unauthorized("Bearer token contains an invalid multi-value claim")
    if not all(isinstance(item, str) for item in candidates):
        raise _unauthorized("Bearer token contains a non-string multi-value claim")
    return sorted({item.strip() for item in candidates if item.strip()})


@lru_cache(maxsize=8)
def _get_jwk_client(jwks_url: str) -> PyJWKClient:
    return PyJWKClient(jwks_url, cache_keys=True, lifespan=300, timeout=5)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )
