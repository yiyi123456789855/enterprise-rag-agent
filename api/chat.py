from fastapi import APIRouter, Depends

from api.dependencies import get_rag_service
from api.security import get_auth_context
from api.traffic import limit_chat
from app.auth import AuthContext
from app.schemas import ChatRequest, ChatResponse


router = APIRouter(prefix="/api/v1", tags=["chat"])


@router.post("/chat", response_model=ChatResponse, dependencies=[Depends(limit_chat)])
def chat(payload: ChatRequest, auth: AuthContext = Depends(get_auth_context)) -> dict:
    tenant_id = payload.tenant_id if auth.legacy else auth.tenant_id
    user_id = payload.user_id if auth.legacy else auth.user_id
    departments = payload.departments if auth.legacy else list(auth.departments)
    return get_rag_service().ask(
        question=payload.question,
        tenant_id=tenant_id,
        user_id=user_id,
        departments=departments,
        top_k=payload.top_k,
        session_id=payload.session_id,
    )
