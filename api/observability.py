from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from api.dependencies import get_repository
from app.schemas import (
    ConversationResponse,
    FeedbackRequest,
    FeedbackResponse,
    MetricsResponse,
)


router = APIRouter(prefix="/api/v1", tags=["observability"])


@router.get("/conversations", response_model=list[ConversationResponse])
def list_conversations(
    tenant_id: str = "default",
    user_id: str = "web-user",
    session_id: str = "",
    limit: int = Query(default=20, ge=1, le=100),
) -> list[dict]:
    return get_repository().list_conversations(
        tenant_id=tenant_id,
        user_id=user_id,
        session_id=session_id,
        limit=limit,
    )


@router.post("/feedback", response_model=FeedbackResponse)
def create_feedback(payload: FeedbackRequest) -> FeedbackResponse:
    try:
        feedback_id = get_repository().save_feedback(
            conversation_id=payload.conversation_id,
            tenant_id=payload.tenant_id,
            rating=payload.rating,
            comment=payload.comment,
        )
    except KeyError as exc:
        raise HTTPException(status_code=404, detail="Conversation not found") from exc
    return FeedbackResponse(id=feedback_id)


@router.get("/metrics", response_model=MetricsResponse)
def metrics(tenant_id: str = "default") -> MetricsResponse:
    return MetricsResponse(tenant_id=tenant_id, metrics=get_repository().get_metrics(tenant_id))
