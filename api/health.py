from fastapi import APIRouter, Response, status

from api.dependencies import (
    get_answer_generator,
    get_ingestion_dispatcher,
    get_rate_limiter,
    get_repository,
    get_reranker,
    get_settings,
    get_vector_index,
)
from app.schemas import HealthResponse
from app.telemetry import DEPENDENCY_UP


router = APIRouter(tags=["health"])


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return _health_snapshot()


@router.get("/health/live", response_model=HealthResponse)
def liveness() -> HealthResponse:
    return HealthResponse(status="ok", details={"process": "ready"})


@router.get("/health/ready", response_model=HealthResponse)
def readiness(response: Response) -> HealthResponse:
    snapshot = _health_snapshot()
    if snapshot.status != "ok":
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return snapshot


def _health_snapshot() -> HealthResponse:
    settings = get_settings()
    repository = get_repository()
    vector_index = get_vector_index()
    reranker = get_reranker()
    generator = get_answer_generator()
    database_status = "ready" if repository.health() else "unavailable"
    queue_status = "ready" if get_ingestion_dispatcher().health() else "unavailable"
    rate_limit_status = "ready" if get_rate_limiter().health() else "unavailable"
    vector_status = "disabled" if vector_index is None else ("ready" if vector_index.health() else "unavailable")
    generator_status = (
        "extractive"
        if generator.name == "extractive"
        else ("ready" if generator.health() else "fallback")
    )
    if DEPENDENCY_UP is not None:
        for dependency, dependency_status in {
            "database": database_status,
            "task_queue": queue_status,
            "rate_limit": rate_limit_status,
            "vector_index": vector_status,
            "generator": "ready" if generator_status in {"ready", "extractive"} else "unavailable",
        }.items():
            DEPENDENCY_UP.labels(dependency=dependency).set(
                1 if dependency_status in {"ready", "disabled"} else 0
            )
    dependencies_ready = (
        database_status == "ready"
        and queue_status == "ready"
        and rate_limit_status == "ready"
        and vector_status != "unavailable"
        and (not settings.llm_required or generator_status == "ready")
    )
    overall_status = "ok" if dependencies_ready else "degraded"
    return HealthResponse(
        status=overall_status,
        details={
            "database": database_status,
            "database_backend": "postgresql" if settings.database_url else "sqlite",
            "task_queue": settings.task_queue_backend,
            "task_queue_status": queue_status,
            "rate_limit_backend": settings.rate_limit_backend,
            "rate_limit_status": rate_limit_status,
            "auth_mode": settings.auth_mode,
            "retrieval_backend": settings.retrieval_backend,
            "vector_index": vector_status,
            "embedding_model": settings.embedding_model if settings.retrieval_backend == "qdrant" else "hashing",
            "reranker": reranker.name,
            "generator": generator.name,
            "generator_status": generator_status,
            "generator_fallback": generator.fallback_name,
            "llm_required": settings.llm_required,
        },
    )
