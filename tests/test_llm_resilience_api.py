from __future__ import annotations

import os
import tempfile
from pathlib import Path
from unittest.mock import patch
from urllib import error

from fastapi.testclient import TestClient

from api.dependencies import (
    get_answer_generator,
    get_embedder,
    get_ingestion_dispatcher,
    get_ingestion_service,
    get_rate_limiter,
    get_rag_service,
    get_repository,
    get_reranker,
    get_settings,
    get_upload_store,
    get_vector_index,
)
from app.main import app


def _clear_dependencies() -> None:
    get_rag_service.cache_clear()
    get_answer_generator.cache_clear()
    get_rate_limiter.cache_clear()
    get_ingestion_dispatcher.cache_clear()
    get_ingestion_service.cache_clear()
    get_upload_store.cache_clear()
    get_repository.cache_clear()
    get_vector_index.cache_clear()
    get_embedder.cache_clear()
    get_reranker.cache_clear()
    get_settings.cache_clear()


def test_chat_returns_grounded_answer_when_remote_llm_is_down() -> None:
    names = (
        "DATA_DIR",
        "DATABASE_PATH",
        "LLM_BASE_URL",
        "LLM_MODEL",
        "LLM_MAX_RETRIES",
        "LLM_RETRY_BACKOFF_SECONDS",
    )
    previous = {name: os.environ.get(name) for name in names}
    with tempfile.TemporaryDirectory() as directory:
        os.environ.update(
            {
                "DATA_DIR": directory,
                "DATABASE_PATH": str(Path(directory) / "llm-resilience.db"),
                "LLM_BASE_URL": "http://127.0.0.1:8001/v1",
                "LLM_MODEL": "Qwen/Qwen2.5-3B-Instruct",
                "LLM_MAX_RETRIES": "0",
                "LLM_RETRY_BACKOFF_SECONDS": "0",
            }
        )
        _clear_dependencies()
        try:
            with TestClient(app) as client:
                upload = client.post(
                    "/api/v1/documents",
                    data={"tenant_id": "demo", "visibility": "public", "departments": "[]"},
                    files={
                        "file": (
                            "leave.md",
                            "# 休假制度\n\n连续休假七天需要提前十个工作日申请。".encode(),
                            "text/markdown",
                        )
                    },
                )
                assert upload.status_code == 202, upload.text

                with patch(
                    "agent.generators.request.urlopen",
                    side_effect=error.URLError("connection refused"),
                ):
                    response = client.post(
                        "/api/v1/chat",
                        json={
                            "question": "连续休假七天需要提前多久申请？",
                            "tenant_id": "demo",
                            "user_id": "tester",
                            "departments": [],
                        },
                    )

                assert response.status_code == 200, response.text
                body = response.json()
                assert body["status"] == "answered"
                assert "十个工作日" in body["answer"]
                assert body["citations"][0]["filename"] == "leave.md"
        finally:
            _clear_dependencies()
            for name, value in previous.items():
                if value is None:
                    os.environ.pop(name, None)
                else:
                    os.environ[name] = value
