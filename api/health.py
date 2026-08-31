from fastapi import APIRouter

from api.dependencies import get_repository, get_reranker, get_settings, get_vector_index
from app.schemas import HealthResponse


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    get_repository()
    settings = get_settings()
    vector_index = get_vector_index()
    reranker = get_reranker()
    vector_status = "disabled" if vector_index is None else ("ready" if vector_index.health() else "unavailable")
    overall_status = "ok" if vector_status != "unavailable" else "degraded"
    return HealthResponse(
        status=overall_status,
        details={
            "database": "ready",
            "retrieval_backend": settings.retrieval_backend,
            "vector_index": vector_status,
            "embedding_model": settings.embedding_model if settings.retrieval_backend == "qdrant" else "hashing",
            "reranker": reranker.name,
            "generator": settings.llm_model or "extractive",
        },
    )
