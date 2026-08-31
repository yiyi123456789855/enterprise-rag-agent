from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse, Response

from api.chat import router as chat_router
from api.dependencies import get_repository, get_reranker, get_settings, get_vector_index
from api.documents import router as documents_router
from api.health import router as health_router
from api.observability import router as observability_router
from api.security import require_api_key


@asynccontextmanager
async def lifespan(_: FastAPI):
    get_repository().initialize()
    # Server mode warms the model and Qdrant collection before accepting traffic.
    # This makes readiness meaningful and avoids a very slow first user request.
    if get_settings().retrieval_backend == "qdrant":
        get_vector_index()
    if get_settings().reranker_enabled:
        get_reranker()
    yield


settings = get_settings()
app = FastAPI(
    title=settings.app_name,
    version="0.2.0",
    description="Citation-first enterprise knowledge-base RAG API",
    lifespan=lifespan,
)
app.include_router(health_router)
app.include_router(documents_router, dependencies=[Depends(require_api_key)])
app.include_router(chat_router, dependencies=[Depends(require_api_key)])
app.include_router(observability_router, dependencies=[Depends(require_api_key)])


@app.get("/", include_in_schema=False)
def root() -> FileResponse:
    """Serve the dependency-free knowledge-base web interface."""
    return FileResponse(Path(__file__).resolve().parents[1] / "frontend" / "index.html")


@app.get("/favicon.ico", include_in_schema=False)
def favicon() -> Response:
    return Response(status_code=204)
