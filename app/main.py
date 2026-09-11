from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, Response

from api.chat import router as chat_router
from api.audit import router as audit_router
from api.dependencies import get_repository, get_reranker, get_settings, get_vector_index
from api.documents import router as documents_router
from api.health import router as health_router
from api.observability import router as observability_router
from app.telemetry import (
    RequestTelemetryMiddleware,
    configure_logging,
    configure_open_telemetry,
    metrics_response,
)


@asynccontextmanager
async def lifespan(_: FastAPI):
    repository = get_repository()
    repository.initialize()
    # Server mode warms the model and Qdrant collection before accepting traffic.
    # This makes readiness meaningful and avoids a very slow first user request.
    if get_settings().retrieval_backend == "qdrant":
        get_vector_index()
    if get_settings().reranker_enabled:
        get_reranker()
    try:
        yield
    finally:
        repository.close()
        if tracer_provider is not None:
            tracer_provider.shutdown()


settings = get_settings()
configure_logging(settings)
app = FastAPI(
    title=settings.app_name,
    version="0.6.5",
    description="Citation-first enterprise knowledge-base RAG API",
    lifespan=lifespan,
)
app.add_middleware(RequestTelemetryMiddleware, settings=settings)
app.include_router(health_router)
app.include_router(documents_router)
app.include_router(chat_router)
app.include_router(observability_router)
app.include_router(audit_router)


@app.get("/internal/metrics", include_in_schema=False)
def prometheus_metrics(request: Request) -> Response:
    return metrics_response(request, settings)


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """Serve the dependency-free knowledge-base web interface."""
    return FileResponse(Path(__file__).resolve().parents[1] / "frontend" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)


tracer_provider = configure_open_telemetry(app, settings)
