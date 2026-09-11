from __future__ import annotations

import hashlib
import hmac

from fastapi import Request

from app.auth import AuthContext


def audit_actor(auth: AuthContext) -> str:
    return auth.user_id if not auth.legacy else "legacy-api-client"


def audit_request(request: Request, auth: AuthContext, secret: str) -> dict[str, str]:
    host = request.client.host if request.client else "unknown"
    key = (secret or "development-only-audit-key").encode("utf-8")
    source_hash = hmac.new(key, host.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "actor_id": audit_actor(auth),
        "request_id": getattr(request.state, "request_id", ""),
        "source_ip_hash": source_hash,
    }
