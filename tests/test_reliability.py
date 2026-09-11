from __future__ import annotations

import sys
import tempfile
import asyncio
from concurrent.futures import ThreadPoolExecutor
from io import BytesIO
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import UploadFile

from app.config import Settings
from app.database import Repository, _PostgresConnection
from ingestion.dispatcher import IngestionDispatcher
from ingestion.service import IngestionService
from ingestion.upload_store import UploadStore, UploadTooLargeError


def test_upload_store_streams_bounds_and_deletes() -> None:
    with tempfile.TemporaryDirectory() as directory:
        store = UploadStore(directory)
        upload = UploadFile(BytesIO(b"bounded-content"), filename="policy.md")
        path = asyncio.run(store.save(upload, max_bytes=1024))
        assert path.read_bytes() == b"bounded-content"
        store.delete(path)
        assert not path.exists()

        queued = asyncio.run(store.save(UploadFile(BytesIO(b"queued"), filename="q.md"), 1024))
        job_id = "8fe08e49-4cba-42df-aa5e-8fbef34daf09"
        promoted = store.promote(queued, job_id)
        assert promoted == store.path_for_job(job_id)
        assert promoted.read_bytes() == b"queued"
        store.delete(promoted)

        oversized = UploadFile(BytesIO(b"too-large"), filename="large.md")
        with pytest.raises(UploadTooLargeError):
            asyncio.run(store.save(oversized, max_bytes=3))
        assert list(Path(directory).iterdir()) == []


def test_concurrent_duplicate_uploads_share_one_document_and_job() -> None:
    with tempfile.TemporaryDirectory() as directory:
        repository = Repository(Path(directory) / "concurrent.db")
        repository.initialize()
        service = IngestionService(repository)

        def enqueue():
            return service.enqueue(
                filename="policy.md",
                content=b"# Policy\n\nThe same immutable content.",
                tenant_id="tenant-a",
            )

        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(executor.map(lambda _: enqueue(), range(2)))

        assert len({result.document["id"] for result in results}) == 1
        assert len({result.job["id"] for result in results}) == 1
        assert sorted(result.duplicate for result in results) == [False, True]
        assert len(repository.list_documents("tenant-a")) == 1


def test_celery_dispatch_sends_identifiers_not_document_bytes() -> None:
    sent: list[dict] = []

    def send_task(name, **kwargs):
        sent.append({"name": name, **kwargs})

    fake_tasks = SimpleNamespace(
        TASK_NAME="enterprise_rag.ingestion.process",
        celery_app=SimpleNamespace(send_task=send_task),
    )
    repository = SimpleNamespace(update_job=lambda *args: None)
    settings = Settings(
        task_queue_backend="celery",
        redis_url="redis://localhost:6379/0",
        celery_queue="ingestion",
    )
    upload_store = SimpleNamespace(
        delete=lambda path: None,
        validate_job_path=lambda job_id, path: path,
    )
    dispatcher = IngestionDispatcher(
        settings,
        repository,
        SimpleNamespace(),
        upload_store,
    )
    with patch.dict(sys.modules, {"ingestion.tasks": fake_tasks}):
        dispatcher.dispatch(
            job_id="job-1",
            document_id="doc-1",
            filename="policy.md",
            content_path="/shared/uploads/1.upload",
        )

    assert sent == [
        {
            "name": "enterprise_rag.ingestion.process",
            "args": ["job-1", "doc-1", "policy.md", "/shared/uploads/1.upload"],
            "task_id": "job-1",
            "queue": "ingestion",
        }
    ]
    assert all(not isinstance(value, bytes) for value in sent[0]["args"])


def test_postgres_adapter_translates_placeholders() -> None:
    calls: list[tuple[str, tuple[str, ...]]] = []
    sentinel = object()
    connection = SimpleNamespace(
        execute=lambda query, parameters: calls.append((query, parameters)) or sentinel
    )
    adapter = _PostgresConnection(connection)
    assert adapter.execute("SELECT * FROM documents WHERE id = ?", ("doc-1",)) is sentinel
    assert calls == [("SELECT * FROM documents WHERE id = %s", ("doc-1",))]


def test_production_requires_postgres_and_celery() -> None:
    settings = Settings(
        app_environment="production",
        auth_mode="oidc",
        oidc_issuer="https://id.company.test",
        oidc_audience="rag-api",
        oidc_jwks_url="https://id.company.test/jwks",
    )
    with pytest.raises(RuntimeError, match="PostgreSQL"):
        settings.validate()

    valid = Settings(
        app_environment="production",
        auth_mode="oidc",
        oidc_issuer="https://id.company.test",
        oidc_audience="rag-api",
        oidc_jwks_url="https://id.company.test/jwks",
        database_url="postgresql://rag:secret@postgres:5432/rag",
        task_queue_backend="celery",
        redis_url="redis://:secret@valkey:6379/0",
        rate_limit_backend="redis",
        metrics_bearer_token="m" * 32,
        audit_hmac_key="a" * 32,
    )
    valid.validate()
