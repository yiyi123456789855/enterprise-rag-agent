from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


ASYMMETRIC_JWT_ALGORITHMS = {
    "RS256", "RS384", "RS512",
    "PS256", "PS384", "PS512",
    "ES256", "ES384", "ES512",
    "EdDSA",
}


@dataclass(frozen=True)
class Settings:
    app_name: str = "Enterprise Knowledge RAG Agent"
    app_environment: str = "development"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/rag.db")
    database_url: str = ""
    database_pool_size: int = 10
    upload_dir: Path = Path("data/uploads")
    max_upload_mb: int = 30
    chunk_size: int = 320
    chunk_overlap: int = 60
    retrieval_top_k: int = 5
    evidence_min_coverage: float = 0.20
    evidence_min_anchor_coverage: float = 0.20
    retrieval_backend: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "enterprise_knowledge"
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "cpu"
    rerank_candidates: int = 20
    app_api_key: str = ""
    task_queue_backend: str = "sync"
    redis_url: str = ""
    celery_queue: str = "ingestion"
    celery_max_retries: int = 3
    celery_soft_time_limit: int = 840
    celery_time_limit: int = 900
    log_level: str = "INFO"
    json_logs: bool = False
    metrics_bearer_token: str = ""
    otel_enabled: bool = False
    otel_service_name: str = "enterprise-rag-api"
    otel_exporter_otlp_endpoint: str = ""
    rate_limit_backend: str = "memory"
    rate_limit_window_seconds: int = 60
    rate_limit_chat: int = 60
    rate_limit_upload: int = 10
    rate_limit_read: int = 300
    rate_limit_feedback: int = 30
    audit_hmac_key: str = ""
    auth_mode: str = "legacy"
    oidc_issuer: str = ""
    oidc_audience: str = ""
    oidc_jwks_url: str = ""
    oidc_algorithms: tuple[str, ...] = ("RS256",)
    oidc_tenant_claim: str = "tenant_id"
    oidc_departments_claim: str = "departments"
    oidc_roles_claim: str = "roles"
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""
    llm_timeout_seconds: int = 60
    llm_health_timeout_seconds: int = 2
    llm_max_retries: int = 1
    llm_retry_backoff_seconds: float = 0.25
    llm_failure_threshold: int = 3
    llm_circuit_reset_seconds: int = 30
    llm_required: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        app_environment = os.getenv("APP_ENV", "development").strip().lower()
        return cls(
            app_name=os.getenv("APP_NAME", cls.app_name),
            app_environment=app_environment,
            data_dir=data_dir,
            database_path=Path(os.getenv("DATABASE_PATH", str(data_dir / "rag.db"))),
            database_url=os.getenv("DATABASE_URL", "").strip(),
            database_pool_size=int(os.getenv("DATABASE_POOL_SIZE", "10")),
            upload_dir=Path(os.getenv("UPLOAD_DIR", str(data_dir / "uploads"))),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "30")),
            chunk_size=int(os.getenv("CHUNK_SIZE", "320")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "60")),
            retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "5")),
            evidence_min_coverage=float(os.getenv("EVIDENCE_MIN_COVERAGE", "0.20")),
            evidence_min_anchor_coverage=float(os.getenv("EVIDENCE_MIN_ANCHOR_COVERAGE", "0.20")),
            retrieval_backend=os.getenv("RETRIEVAL_BACKEND", "local").lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
            qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "enterprise_knowledge"),
            reranker_enabled=_env_bool("RERANKER_ENABLED", False),
            reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            reranker_device=os.getenv("RERANKER_DEVICE", os.getenv("EMBEDDING_DEVICE", "cpu")),
            rerank_candidates=int(os.getenv("RERANK_CANDIDATES", "20")),
            app_api_key=os.getenv("APP_API_KEY", ""),
            task_queue_backend=os.getenv("TASK_QUEUE_BACKEND", "sync").strip().lower(),
            redis_url=os.getenv("REDIS_URL", "").strip(),
            celery_queue=os.getenv("CELERY_QUEUE", "ingestion").strip(),
            celery_max_retries=int(os.getenv("CELERY_MAX_RETRIES", "3")),
            celery_soft_time_limit=int(os.getenv("CELERY_SOFT_TIME_LIMIT", "840")),
            celery_time_limit=int(os.getenv("CELERY_TIME_LIMIT", "900")),
            log_level=os.getenv("LOG_LEVEL", "INFO").strip().upper(),
            json_logs=_env_bool("JSON_LOGS", app_environment == "production"),
            metrics_bearer_token=os.getenv("METRICS_BEARER_TOKEN", "").strip(),
            otel_enabled=_env_bool("OTEL_ENABLED", False),
            otel_service_name=os.getenv("OTEL_SERVICE_NAME", "enterprise-rag-api").strip(),
            otel_exporter_otlp_endpoint=os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip(),
            rate_limit_backend=os.getenv(
                "RATE_LIMIT_BACKEND", "redis" if app_environment == "production" else "memory"
            ).strip().lower(),
            rate_limit_window_seconds=int(os.getenv("RATE_LIMIT_WINDOW_SECONDS", "60")),
            rate_limit_chat=int(os.getenv("RATE_LIMIT_CHAT", "60")),
            rate_limit_upload=int(os.getenv("RATE_LIMIT_UPLOAD", "10")),
            rate_limit_read=int(os.getenv("RATE_LIMIT_READ", "300")),
            rate_limit_feedback=int(os.getenv("RATE_LIMIT_FEEDBACK", "30")),
            audit_hmac_key=os.getenv("AUDIT_HMAC_KEY", "").strip(),
            auth_mode=os.getenv("AUTH_MODE", "legacy").strip().lower(),
            # Issuer comparison is exact by OIDC design; preserve a provider's trailing slash.
            oidc_issuer=os.getenv("OIDC_ISSUER", "").strip(),
            oidc_audience=os.getenv("OIDC_AUDIENCE", ""),
            oidc_jwks_url=os.getenv("OIDC_JWKS_URL", ""),
            oidc_algorithms=tuple(
                item.strip() for item in os.getenv("OIDC_ALGORITHMS", "RS256").split(",") if item.strip()
            ),
            oidc_tenant_claim=os.getenv("OIDC_TENANT_CLAIM", "tenant_id").strip(),
            oidc_departments_claim=os.getenv("OIDC_DEPARTMENTS_CLAIM", "departments").strip(),
            oidc_roles_claim=os.getenv("OIDC_ROLES_CLAIM", "roles").strip(),
            llm_base_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
            llm_timeout_seconds=int(os.getenv("LLM_TIMEOUT_SECONDS", "60")),
            llm_health_timeout_seconds=int(os.getenv("LLM_HEALTH_TIMEOUT_SECONDS", "2")),
            llm_max_retries=int(os.getenv("LLM_MAX_RETRIES", "1")),
            llm_retry_backoff_seconds=float(os.getenv("LLM_RETRY_BACKOFF_SECONDS", "0.25")),
            llm_failure_threshold=int(os.getenv("LLM_FAILURE_THRESHOLD", "3")),
            llm_circuit_reset_seconds=int(os.getenv("LLM_CIRCUIT_RESET_SECONDS", "30")),
            llm_required=_env_bool("LLM_REQUIRED", False),
        )

    def validate(self) -> None:
        if self.app_environment not in {"development", "test", "production"}:
            raise RuntimeError("APP_ENV must be development, test, or production")
        if self.auth_mode not in {"legacy", "oidc"}:
            raise RuntimeError("AUTH_MODE must be legacy or oidc")
        if self.task_queue_backend not in {"sync", "celery"}:
            raise RuntimeError("TASK_QUEUE_BACKEND must be sync or celery")
        if self.task_queue_backend == "celery" and not self.redis_url:
            raise RuntimeError("TASK_QUEUE_BACKEND=celery requires REDIS_URL")
        if self.celery_max_retries < 0:
            raise RuntimeError("CELERY_MAX_RETRIES must be non-negative")
        if self.celery_soft_time_limit < 1 or self.celery_time_limit <= self.celery_soft_time_limit:
            raise RuntimeError("CELERY_TIME_LIMIT must be greater than CELERY_SOFT_TIME_LIMIT")
        if self.database_pool_size < 1:
            raise RuntimeError("DATABASE_POOL_SIZE must be positive")
        if self.log_level not in {"DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"}:
            raise RuntimeError("LOG_LEVEL is invalid")
        if self.rate_limit_backend not in {"disabled", "memory", "redis"}:
            raise RuntimeError("RATE_LIMIT_BACKEND must be disabled, memory, or redis")
        if self.rate_limit_backend == "redis" and not self.redis_url:
            raise RuntimeError("RATE_LIMIT_BACKEND=redis requires REDIS_URL")
        if self.rate_limit_window_seconds < 1 or min(
            self.rate_limit_chat,
            self.rate_limit_upload,
            self.rate_limit_read,
            self.rate_limit_feedback,
        ) < 1:
            raise RuntimeError("Rate-limit window and request limits must be positive")
        if self.otel_enabled and not self.otel_exporter_otlp_endpoint:
            raise RuntimeError("OTEL_ENABLED=true requires OTEL_EXPORTER_OTLP_ENDPOINT")
        if min(
            self.llm_timeout_seconds,
            self.llm_health_timeout_seconds,
            self.llm_failure_threshold,
            self.llm_circuit_reset_seconds,
        ) < 1:
            raise RuntimeError("LLM timeout and circuit-breaker settings must be positive")
        if self.llm_max_retries < 0 or self.llm_retry_backoff_seconds < 0:
            raise RuntimeError("LLM retry settings must be non-negative")
        if self.llm_required and not (self.llm_base_url and self.llm_model):
            raise RuntimeError("LLM_REQUIRED=true requires LLM_BASE_URL and LLM_MODEL")
        if self.app_environment == "production" and self.auth_mode != "oidc":
            raise RuntimeError("Production requires AUTH_MODE=oidc; legacy identity is not trusted")
        if self.app_environment == "production" and not self.database_url.startswith(
            ("postgresql://", "postgres://")
        ):
            raise RuntimeError("Production requires a PostgreSQL DATABASE_URL")
        if self.app_environment == "production" and self.task_queue_backend != "celery":
            raise RuntimeError("Production requires TASK_QUEUE_BACKEND=celery")
        if self.app_environment == "production" and self.rate_limit_backend != "redis":
            raise RuntimeError("Production requires RATE_LIMIT_BACKEND=redis")
        if self.app_environment == "production" and len(self.metrics_bearer_token) < 32:
            raise RuntimeError("Production requires a METRICS_BEARER_TOKEN of at least 32 characters")
        if self.app_environment == "production" and len(self.audit_hmac_key) < 32:
            raise RuntimeError("Production requires an AUDIT_HMAC_KEY of at least 32 characters")
        if self.auth_mode == "oidc":
            missing = [
                name
                for name, value in {
                    "OIDC_ISSUER": self.oidc_issuer,
                    "OIDC_AUDIENCE": self.oidc_audience,
                    "OIDC_JWKS_URL": self.oidc_jwks_url,
                    "OIDC_ALGORITHMS": self.oidc_algorithms,
                }.items()
                if not value
            ]
            if missing:
                raise RuntimeError(f"OIDC configuration is incomplete: {', '.join(missing)}")
            unsupported = set(self.oidc_algorithms).difference(ASYMMETRIC_JWT_ALGORITHMS)
            if unsupported:
                raise RuntimeError(
                    "OIDC_ALGORITHMS must use supported asymmetric algorithms; rejected: "
                    + ", ".join(sorted(unsupported))
                )
            if self.app_environment == "production" and (
                not self.oidc_issuer.startswith("https://")
                or not self.oidc_jwks_url.startswith("https://")
            ):
                raise RuntimeError("Production OIDC issuer and JWKS URL must use HTTPS")
            if self.app_environment == "production" and (
                "example.com" in self.oidc_issuer or "example.com" in self.oidc_jwks_url
            ):
                raise RuntimeError("Replace example OIDC endpoints before production startup")

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if not self.database_url:
            self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self.upload_dir.mkdir(parents=True, exist_ok=True)

    @property
    def database_dsn(self) -> str | Path:
        return self.database_url or self.database_path


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
