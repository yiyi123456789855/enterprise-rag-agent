from __future__ import annotations

import secrets

from fastapi import HTTPException, Security, status
from fastapi.security import APIKeyHeader

from api.dependencies import get_settings


api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def require_api_key(provided_key: str | None = Security(api_key_header)) -> None:
    """Protect server APIs when APP_API_KEY is configured.

    Local development remains frictionless because an empty APP_API_KEY disables
    authentication. The server deployment template always supplies a key.
    """

    expected_key = get_settings().app_api_key
    if not expected_key:
        return
    if not provided_key or not secrets.compare_digest(provided_key, expected_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing or invalid X-API-Key",
        )

