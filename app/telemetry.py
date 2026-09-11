from __future__ import annotations

import contextvars
import json
import logging
import re
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from fastapi import FastAPI, HTTPException, Request, status
from fastapi.responses import Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import Settings


request_id_context: contextvars.ContextVar[str] = contextvars.ContextVar(
    "request_id", default=""
)
_SAFE_REQUEST_ID = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


class JsonFormatter(logging.Formatter):
    """One-line logs suitable for collectors; no headers, tokens, or bodies."""

    def format(self, record: logging.LogRecord) -> str:
        payload: dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        request_id = getattr(record, "request_id", "") or request_id_context.get()
        if request_id:
            payload["request_id"] = request_id
        for name in ("method", "route", "status_code", "duration_ms", "error_type"):
            value = getattr(record, name, None)
            if value is not None:
                payload[name] = value
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


def configure_logging(settings: Settings) -> None:
    handler = logging.StreamHandler()
    if settings.json_logs:
        handler.setFormatter(JsonFormatter())
    else:
        handler.setFormatter(
            logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s")
        )
    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(settings.log_level)


try:
    from prometheus_client import Counter, Gauge, Histogram, CONTENT_TYPE_LATEST, generate_latest

    HTTP_REQUESTS = Counter(
        "rag_http_requests_total",
        "HTTP requests completed",
        ("method", "route", "status"),
    )
    HTTP_DURATION = Histogram(
        "rag_http_request_duration_seconds",
        "HTTP request duration",
        ("method", "route"),
        buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
    )
    HTTP_IN_PROGRESS = Gauge(
        "rag_http_requests_in_progress",
        "HTTP requests currently being handled",
        ("method",),
    )
    RATE_LIMIT_REJECTIONS = Counter(
        "rag_rate_limit_rejections_total",
        "Requests rejected by policy",
        ("policy",),
    )
    DEPENDENCY_UP = Gauge(
        "rag_dependency_up",
        "Whether a required runtime dependency is ready",
        ("dependency",),
    )
except ImportError:  # pragma: no cover - configuration validation covers server installs
    HTTP_REQUESTS = HTTP_DURATION = HTTP_IN_PROGRESS = RATE_LIMIT_REJECTIONS = None
    DEPENDENCY_UP = None
    CONTENT_TYPE_LATEST = "text/plain; version=0.0.4"
    generate_latest = None


class RequestTelemetryMiddleware(BaseHTTPMiddleware):
    def __init__(self, app, settings: Settings):
        super().__init__(app)
        self.settings = settings
        self.logger = logging.getLogger("rag.access")

    async def dispatch(self, request: Request, call_next):
        supplied_id = request.headers.get("X-Request-ID", "")
        request_id = supplied_id if _SAFE_REQUEST_ID.fullmatch(supplied_id) else str(uuid.uuid4())
        request.state.request_id = request_id
        token = request_id_context.set(request_id)
        method = request.method
        started = time.perf_counter()
        status_code = 500
        if HTTP_IN_PROGRESS is not None:
            HTTP_IN_PROGRESS.labels(method=method).inc()
        try:
            response = await call_next(request)
            status_code = response.status_code
            response.headers["X-Request-ID"] = request_id
            return response
        except Exception as exc:
            self.logger.error(
                "request failed",
                extra={"error_type": type(exc).__name__, "request_id": request_id},
            )
            raise
        finally:
            duration = time.perf_counter() - started
            route = getattr(request.scope.get("route"), "path", "unmatched")
            if HTTP_IN_PROGRESS is not None:
                HTTP_IN_PROGRESS.labels(method=method).dec()
                if request.url.path != "/internal/metrics":
                    HTTP_REQUESTS.labels(
                        method=method, route=route, status=str(status_code)
                    ).inc()
                    HTTP_DURATION.labels(method=method, route=route).observe(duration)
            self.logger.info(
                "request completed",
                extra={
                    "request_id": request_id,
                    "method": method,
                    "route": route,
                    "status_code": status_code,
                    "duration_ms": round(duration * 1000, 2),
                },
            )
            request_id_context.reset(token)


def metrics_response(request: Request, settings: Settings) -> Response:
    if generate_latest is None:
        raise HTTPException(status_code=503, detail="Prometheus client is unavailable")
    expected = settings.metrics_bearer_token
    if expected:
        import secrets

        authorization = request.headers.get("Authorization", "")
        provided = authorization[7:] if authorization.startswith("Bearer ") else ""
        if not provided or not secrets.compare_digest(provided, expected):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Missing or invalid metrics bearer token",
                headers={"WWW-Authenticate": "Bearer"},
            )
    return Response(content=generate_latest(), media_type=CONTENT_TYPE_LATEST)


def configure_open_telemetry(app: FastAPI, settings: Settings):
    if not settings.otel_enabled:
        return None
    try:
        from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
    except ImportError as exc:  # pragma: no cover - depends on production extra
        raise RuntimeError("OpenTelemetry is enabled but server telemetry dependencies are missing") from exc

    provider = TracerProvider(
        resource=Resource.create({"service.name": settings.otel_service_name})
    )
    provider.add_span_processor(
        BatchSpanProcessor(OTLPSpanExporter(endpoint=settings.otel_exporter_otlp_endpoint))
    )
    FastAPIInstrumentor.instrument_app(
        app,
        tracer_provider=provider,
        excluded_urls="health,internal/metrics",
    )
    return provider
