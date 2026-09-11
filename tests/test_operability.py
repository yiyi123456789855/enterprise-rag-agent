from __future__ import annotations

import sqlite3
import tempfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import HTTPException, Request
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.config import Settings
from app.database import Repository
from app.rate_limit import RateLimiter
from app.main import app
from api.health import _health_snapshot
from app.telemetry import configure_open_telemetry, metrics_response


def test_request_id_and_prometheus_metrics_are_exposed() -> None:
    with TestClient(app) as client:
        health = client.get("/health", headers={"X-Request-ID": "trace-123"})
        assert health.status_code == 200
        assert health.headers["X-Request-ID"] == "trace-123"
        assert client.get("/health/live").status_code == 200
        assert client.get("/health/ready").status_code == 200
        metrics = client.get("/internal/metrics")
        assert metrics.status_code == 200
        assert "rag_http_requests_total" in metrics.text
        assert 'route="/health"' in metrics.text


def test_prometheus_metrics_reject_wrong_bearer_token() -> None:
    request = Request(
        {
            "type": "http",
            "method": "GET",
            "path": "/internal/metrics",
            "headers": [(b"authorization", b"Bearer wrong")],
        }
    )
    with pytest.raises(HTTPException) as context:
        metrics_response(request, Settings(metrics_bearer_token="correct-token"))
    assert context.value.status_code == 401


def test_open_telemetry_initializes_with_server_dependencies() -> None:
    traced_app = FastAPI()
    provider = configure_open_telemetry(
        traced_app,
        Settings(
            otel_enabled=True,
            otel_exporter_otlp_endpoint="http://127.0.0.1:9/v1/traces",
        ),
    )
    assert provider is not None
    provider.shutdown()


def test_memory_token_bucket_rejects_after_capacity() -> None:
    settings = Settings(
        rate_limit_backend="memory",
        rate_limit_window_seconds=3600,
    )
    limiter = RateLimiter(settings)
    assert limiter.check("tenant:a:user:b", "chat", 2).allowed
    assert limiter.check("tenant:a:user:b", "chat", 2).allowed
    rejected = limiter.check("tenant:a:user:b", "chat", 2)
    assert not rejected.allowed
    assert rejected.retry_after > 0
    assert limiter.check("tenant:a:user:other", "chat", 2).allowed


def test_redis_rate_limiter_uses_atomic_lua_result() -> None:
    calls = []
    redis_client = SimpleNamespace(
        eval=lambda *args: calls.append(args) or [0, 0, 1500],
        ping=lambda: True,
    )
    limiter = RateLimiter(
        Settings(
            rate_limit_backend="redis",
            redis_url="redis://valkey:6379/0",
            rate_limit_window_seconds=60,
        ),
        redis_client=redis_client,
    )
    result = limiter.check("sensitive-subject", "upload", 10)
    assert not result.allowed
    assert result.retry_after == 2
    assert calls[0][0].strip().startswith("local key")
    assert "sensitive-subject" not in str(calls)


def test_audit_chain_detects_tampering_and_action_rolls_back_with_audit() -> None:
    with tempfile.TemporaryDirectory() as directory:
        database = Path(directory) / "audit.db"
        repository = Repository(database, audit_hmac_key="test-secret-key-for-audit-chain")
        repository.initialize()
        audit = {
            "actor_id": "editor-1",
            "request_id": "request-1",
            "source_ip_hash": "hashed-ip",
        }
        document, _, duplicate = repository.claim_ingestion(
            tenant_id="tenant-a",
            filename="policy.md",
            sha256="a" * 64,
            visibility="public",
            departments=[],
            audit=audit,
        )
        assert not duplicate
        assert repository.verify_audit_chain("tenant-a") == {
            "valid": True,
            "event_count": 1,
            "first_invalid_sequence": None,
        }
        event = repository.list_audit_events("tenant-a")[0]
        assert event["resource_id"] == document["id"]
        assert event["action"] == "document.upload.accepted"

        connection = sqlite3.connect(database)
        try:
            connection.execute(
                "UPDATE audit_events SET action = 'tampered' WHERE tenant_id = ?",
                ("tenant-a",),
            )
            connection.commit()
        finally:
            connection.close()
        assert repository.verify_audit_chain("tenant-a")["valid"] is False

        with patch.object(repository, "_audit_hash", side_effect=RuntimeError("audit failed")):
            with pytest.raises(RuntimeError, match="audit failed"):
                repository.claim_ingestion(
                    tenant_id="tenant-b",
                    filename="must-rollback.md",
                    sha256="b" * 64,
                    visibility="public",
                    departments=[],
                    audit=audit,
                )
        assert repository.list_documents("tenant-b") == []


def test_production_rejects_missing_operational_controls() -> None:
    base = dict(
        app_environment="production",
        auth_mode="oidc",
        oidc_issuer="https://id.company.test",
        oidc_audience="rag-api",
        oidc_jwks_url="https://id.company.test/jwks",
        database_url="postgresql://rag:secret@postgres:5432/rag",
        task_queue_backend="celery",
        redis_url="redis://:secret@valkey:6379/0",
        rate_limit_backend="redis",
    )
    with pytest.raises(RuntimeError, match="METRICS_BEARER_TOKEN"):
        Settings(**base).validate()
    with pytest.raises(RuntimeError, match="AUDIT_HMAC_KEY"):
        Settings(**base, metrics_bearer_token="m" * 32).validate()


def test_llm_required_needs_a_configured_remote_generator() -> None:
    with pytest.raises(RuntimeError, match="LLM_REQUIRED"):
        Settings(llm_required=True).validate()


def test_llm_resilience_settings_must_be_positive() -> None:
    with pytest.raises(RuntimeError, match="circuit-breaker"):
        Settings(llm_failure_threshold=0).validate()


@pytest.mark.parametrize(
    ("llm_required", "expected_status"),
    [(False, "ok"), (True, "degraded")],
)
def test_health_reports_llm_fallback_and_honors_required_policy(
    llm_required: bool,
    expected_status: str,
) -> None:
    healthy = SimpleNamespace(health=lambda: True)
    unavailable_generator = SimpleNamespace(
        name="Qwen/Qwen2.5-3B-Instruct",
        fallback_name="extractive",
        health=lambda: False,
    )
    with (
        patch(
            "api.health.get_settings",
            return_value=Settings(
                llm_base_url="http://127.0.0.1:8001/v1",
                llm_model="Qwen/Qwen2.5-3B-Instruct",
                llm_required=llm_required,
            ),
        ),
        patch("api.health.get_repository", return_value=healthy),
        patch("api.health.get_ingestion_dispatcher", return_value=healthy),
        patch("api.health.get_rate_limiter", return_value=healthy),
        patch("api.health.get_vector_index", return_value=None),
        patch("api.health.get_reranker", return_value=SimpleNamespace(name="lexical")),
        patch("api.health.get_answer_generator", return_value=unavailable_generator),
    ):
        snapshot = _health_snapshot()

    assert snapshot.status == expected_status
    assert snapshot.details["generator_status"] == "fallback"
    assert snapshot.details["generator_fallback"] == "extractive"
