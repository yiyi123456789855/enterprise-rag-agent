from __future__ import annotations

import os
import tempfile
from pathlib import Path

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
from api.security import get_auth_context
from app.auth import AuthContext
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


def test_oidc_scope_overrides_untrusted_request_identity() -> None:
    with tempfile.TemporaryDirectory() as directory:
        previous_data_dir = os.environ.get("DATA_DIR")
        previous_database_path = os.environ.get("DATABASE_PATH")
        os.environ["DATA_DIR"] = directory
        os.environ["DATABASE_PATH"] = str(Path(directory) / "oidc-scope.db")
        _clear_dependencies()

        editor = AuthContext(
            user_id="trusted-editor",
            tenant_id="trusted-company",
            departments=("研发部",),
            roles=frozenset({"document-editor"}),
        )
        app.dependency_overrides[get_auth_context] = lambda: editor
        try:
            with TestClient(app) as client:
                upload = client.post(
                    "/api/v1/documents",
                    data={
                        "tenant_id": "attacker-company",
                        "visibility": "department",
                        "departments": '["研发部"]',
                    },
                    files={"file": ("trusted.md", "# 内部规则\n\n可信项目预算为八百万元。".encode(), "text/markdown")},
                )
                assert upload.status_code == 202, upload.text
                document = get_repository().get_document(upload.json()["document_id"])
                assert document["tenant_id"] == "trusted-company"

                forbidden_department = client.post(
                    "/api/v1/documents",
                    data={"visibility": "department", "departments": '["财务部"]'},
                    files={"file": ("forbidden.md", b"forbidden", "text/markdown")},
                )
                assert forbidden_department.status_code == 403

                app.dependency_overrides[get_auth_context] = lambda: AuthContext(
                    user_id="trusted-reader",
                    tenant_id="trusted-company",
                    departments=("研发部",),
                    roles=frozenset(),
                )
                chat = client.post(
                    "/api/v1/chat",
                    json={
                        "question": "可信项目预算是多少？",
                        "tenant_id": "attacker-company",
                        "user_id": "attacker-user",
                        "departments": ["财务部"],
                    },
                )
                assert chat.status_code == 200, chat.text
                assert chat.json()["status"] == "answered"

                conversations = client.get(
                    "/api/v1/conversations",
                    params={"tenant_id": "attacker-company", "user_id": "attacker-user"},
                )
                assert conversations.status_code == 200
                assert conversations.json()[0]["id"] == chat.json()["conversation_id"]

                metrics = client.get("/api/v1/metrics", params={"tenant_id": "attacker-company"})
                assert metrics.status_code == 403

                other_user_feedback = client.post(
                    "/api/v1/feedback",
                    json={
                        "conversation_id": chat.json()["conversation_id"],
                        "tenant_id": "trusted-company",
                        "rating": 1,
                    },
                )
                assert other_user_feedback.status_code == 200

                app.dependency_overrides[get_auth_context] = lambda: AuthContext(
                    user_id="finance-user",
                    tenant_id="trusted-company",
                    departments=("财务部",),
                )
                same_tenant_job = client.get(f"/api/v1/jobs/{upload.json()['job_id']}")
                assert same_tenant_job.status_code == 404
                visible_documents = client.get("/api/v1/documents")
                assert visible_documents.status_code == 200
                assert visible_documents.json() == []

                app.dependency_overrides[get_auth_context] = lambda: AuthContext(
                    user_id="different-user",
                    tenant_id="other-company",
                )
                denied_feedback = client.post(
                    "/api/v1/feedback",
                    json={
                        "conversation_id": chat.json()["conversation_id"],
                        "rating": 1,
                    },
                )
                assert denied_feedback.status_code == 404

                cross_tenant_job = client.get(f"/api/v1/jobs/{upload.json()['job_id']}")
                assert cross_tenant_job.status_code == 404

                app.dependency_overrides[get_auth_context] = lambda: AuthContext(
                    user_id="other-auditor",
                    tenant_id="other-company",
                    roles=frozenset({"auditor"}),
                )
                cross_tenant_audit = client.get(
                    "/api/v1/audit-events", params={"tenant_id": "trusted-company"}
                )
                assert cross_tenant_audit.status_code == 200
                assert cross_tenant_audit.json() == []
        finally:
            app.dependency_overrides.pop(get_auth_context, None)
            _clear_dependencies()
            if previous_data_dir is None:
                os.environ.pop("DATA_DIR", None)
            else:
                os.environ["DATA_DIR"] = previous_data_dir
            if previous_database_path is None:
                os.environ.pop("DATABASE_PATH", None)
            else:
                os.environ["DATABASE_PATH"] = previous_database_path
