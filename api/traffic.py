from __future__ import annotations

from fastapi import Depends, HTTPException, Request, Response, status

from api.dependencies import get_rate_limiter, get_settings
from api.security import get_auth_context
from app.auth import AuthContext
from app.telemetry import RATE_LIMIT_REJECTIONS


def _subject(request: Request, auth: AuthContext) -> str:
    if not auth.legacy:
        return f"tenant:{auth.tenant_id}:user:{auth.user_id}"
    host = request.client.host if request.client else "unknown"
    return f"legacy-client:{host}"


def _enforce(
    policy: str,
    limit: int,
    request: Request,
    response: Response,
    auth: AuthContext,
) -> None:
    try:
        result = get_rate_limiter().check(_subject(request, auth), policy, limit)
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    response.headers["X-RateLimit-Limit"] = str(result.limit)
    response.headers["X-RateLimit-Remaining"] = str(result.remaining)
    if not result.allowed:
        if RATE_LIMIT_REJECTIONS is not None:
            RATE_LIMIT_REJECTIONS.labels(policy=policy).inc()
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Rate limit exceeded",
            headers={"Retry-After": str(result.retry_after)},
        )


def limit_chat(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
) -> None:
    _enforce("chat", get_settings().rate_limit_chat, request, response, auth)


def limit_upload(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
) -> None:
    _enforce("upload", get_settings().rate_limit_upload, request, response, auth)


def limit_read(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
) -> None:
    _enforce("read", get_settings().rate_limit_read, request, response, auth)


def limit_feedback(
    request: Request,
    response: Response,
    auth: AuthContext = Depends(get_auth_context),
) -> None:
    _enforce("feedback", get_settings().rate_limit_feedback, request, response, auth)
