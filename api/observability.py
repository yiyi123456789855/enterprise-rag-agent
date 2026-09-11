from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, Request

from api.dependencies import get_repository
from api.security import METRICS_READ_ROLES, get_auth_context, require_roles
from api.traffic import limit_feedback, limit_read
from app.auth import AuthContext
from app.auditing import audit_request
from api.dependencies import get_settings
from app.schemas import (
    ConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    MetricsResponse,
)


router = APIRouter(prefix="/api/v1", tags=["observability"])


@router.get(
    "/conversations",
    response_model=list[ConversationResponse],
    dependencies=[Depends(limit_read)],
)
def list_conversations(
    tenant_id: str = "default",
    user_id: str = "web-user",
    session_id: str = "",
    limit: int = Query(default=20, ge=1, le=100),
    auth: AuthContext = Depends(get_auth_context),
) -> list[dict]:
    effective_tenant_id = tenant_id if auth.legacy else auth.tenant_id
    effective_user_id = user_id if auth.legacy else auth.user_id
    return get_repository().list_conversations(
        tenant_id=effective_tenant_id,
        user_id=effective_user_id,
        session_id=session_id,
        limit=limit,
    )


@router.post(
    "/feedback", response_model=FeedbackResponse, dependencies=[Depends(limit_feedback)]
)
def create_feedback(
    request: Request,
    payload: FeedbackRequest,
    auth: AuthContext = Depends(get_auth_context),
) -> FeedbackResponse:
    effective_tenant_id = payload.tenant_id if auth.legacy else auth.tenant_id
    try:
        feedback_id = get_repository().save_feedback(
            conversation_id=payload.conversation_id,
            tenant_id=effective_tenant_id,
            user_id=None if auth.legacy else auth.user_id,
            rating=payload.rating,
            comment=payload.comment,
            audit=audit_request(request, auth, get_settings().audit_hmac_key),
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    return FeedbackResponse(id=feedback_id)


@router.get(
    "/metrics", response_model=MetricsResponse, dependencies=[Depends(limit_read)]
)
def metrics(
    tenant_id: str = "default",
    auth: AuthContext = Depends(get_auth_context),
) -> MetricsResponse:
    require_roles(auth, *METRICS_READ_ROLES)
    effective_tenant_id = tenant_id if auth.legacy else auth.tenant_id
    return MetricsResponse(
        tenant_id=effective_tenant_id,
        metrics=get_repository().get_metrics(effective_tenant_id),
    )
