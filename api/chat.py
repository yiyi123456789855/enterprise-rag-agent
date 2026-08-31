from fastapi import APIRouter

from api.dependencies import get_rag_service
from app.schemas import ChatRequest, ChatResponse


router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest) -> dict:
    return get_rag_service().ask(
        question=payload.question,
        tenant_id=payload.tenant_id,
        user_id=payload.user_id,
        departments=payload.departments,
        top_k=payload.top_k,
        session_id=payload.session_id,
    )
