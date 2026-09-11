from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import threading
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Iterator

from app.types import ChunkDraft, StoredChunk


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class Repository:
    """Repository supporting SQLite for development and PostgreSQL in production.

    SQLite uses short-lived connections. PostgreSQL uses a bounded, health-checked
    process-local pool. Tenant and department filters are enforced before chunks
    reach the retriever.
    """

    def __init__(
        self,
        database_path: str | Path,
        pool_size: int = 10,
        audit_hmac_key: str = "",
    ):
        self.database_path = str(database_path)
        self.is_postgres = self.database_path.startswith(("postgresql://", "postgres://"))
        self.pool_size = pool_size
        self.audit_hmac_key = audit_hmac_key.encode("utf-8")
        self._pool: Any = None
        self._pool_lock = threading.Lock()
        self._schema_lock = threading.Lock()

    @contextmanager
    def _connect(self) -> Iterator[Any]:
        if self.is_postgres:
            pool = self._get_pool()
            with pool.connection(timeout=10) as raw_connection:
                yield _PostgresConnection(raw_connection)
            return

        raw_connection = sqlite3.connect(self.database_path, timeout=30)
        raw_connection.row_factory = sqlite3.Row
        raw_connection.execute("PRAGMA foreign_keys = ON")
        raw_connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield raw_connection
            raw_connection.commit()
        except Exception:
            raw_connection.rollback()
            raise
        finally:
            raw_connection.close()

    def _get_pool(self):
        if self._pool is not None:
            return self._pool
        with self._pool_lock:
            if self._pool is not None:
                return self._pool
            try:
                from psycopg.rows import dict_row
                from psycopg_pool import ConnectionPool
            except ImportError as exc:
                raise RuntimeError(
                    "PostgreSQL requires psycopg with the pool extra; install server dependencies"
                ) from exc
            self._pool = ConnectionPool(
                self.database_path,
                min_size=1,
                max_size=self.pool_size,
                kwargs={"row_factory": dict_row, "connect_timeout": 5},
                open=True,
                timeout=10,
                max_waiting=self.pool_size * 4,
                name="enterprise-rag",
            )
            self._pool.wait(timeout=10)
            return self._pool

    def close(self) -> None:
        if self._pool is not None:
            self._pool.close(timeout=5)

    def initialize(self) -> None:
        if not self.is_postgres:
            Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._schema_lock, self._connect() as connection:
            if self.is_postgres:
                # Serialize startup schema changes across API and worker processes.
                connection.execute("SELECT pg_advisory_xact_lock(7429005)")
            schema = """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    sha256 TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    visibility TEXT NOT NULL,
                    departments_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );
                CREATE UNIQUE INDEX IF NOT EXISTS idx_document_hash
                    ON documents(tenant_id, sha256);
                CREATE INDEX IF NOT EXISTS idx_documents_tenant_created
                    ON documents(tenant_id, created_at);

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_jobs_document
                    ON ingestion_jobs(document_id);

                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    chunk_index INTEGER NOT NULL,
                    content TEXT NOT NULL,
                    heading TEXT,
                    page_number INTEGER,
                    visibility TEXT NOT NULL,
                    departments_json TEXT NOT NULL,
                    token_count INTEGER NOT NULL,
                    metadata_json TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_chunks_tenant ON chunks(tenant_id);
                CREATE INDEX IF NOT EXISTS idx_chunks_document ON chunks(document_id);

                CREATE TABLE IF NOT EXISTS conversations (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    user_id TEXT NOT NULL,
                    question TEXT NOT NULL,
                    answer TEXT NOT NULL,
                    status TEXT NOT NULL,
                    citations_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS feedback (
                    id TEXT PRIMARY KEY,
                    conversation_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    rating INTEGER NOT NULL,
                    comment TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY(conversation_id) REFERENCES conversations(id) ON DELETE CASCADE
                );
                CREATE INDEX IF NOT EXISTS idx_feedback_tenant ON feedback(tenant_id);
                CREATE UNIQUE INDEX IF NOT EXISTS idx_feedback_conversation
                    ON feedback(conversation_id);
                CREATE INDEX IF NOT EXISTS idx_conversations_tenant_user_created
                    ON conversations(tenant_id, user_id, created_at);

                CREATE TABLE IF NOT EXISTS audit_events (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    sequence INTEGER NOT NULL,
                    actor_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_type TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    request_id TEXT NOT NULL,
                    source_ip_hash TEXT NOT NULL,
                    details_json TEXT NOT NULL,
                    previous_hash TEXT NOT NULL,
                    event_hash TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(tenant_id, sequence)
                );
                CREATE INDEX IF NOT EXISTS idx_audit_tenant_created
                    ON audit_events(tenant_id, created_at);

                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                );
                """
            if self.is_postgres:
                for statement in schema.split(";"):
                    if statement.strip():
                        connection.execute(statement)
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS session_id TEXT NOT NULL DEFAULT ''"
                )
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS latency_ms REAL NOT NULL DEFAULT 0"
                )
                connection.execute(
                    "ALTER TABLE conversations ADD COLUMN IF NOT EXISTS debug_json TEXT NOT NULL DEFAULT '{}'"
                )
                connection.execute(
                    """INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)
                    ON CONFLICT (version) DO NOTHING""",
                    (utc_now(),),
                )
                connection.execute(
                    """INSERT INTO schema_migrations(version, applied_at) VALUES (2, ?)
                    ON CONFLICT (version) DO NOTHING""",
                    (utc_now(),),
                )
            else:
                connection.executescript(schema)
                self._ensure_column(connection, "conversations", "session_id", "TEXT NOT NULL DEFAULT ''")
                self._ensure_column(connection, "conversations", "latency_ms", "REAL NOT NULL DEFAULT 0")
                self._ensure_column(connection, "conversations", "debug_json", "TEXT NOT NULL DEFAULT '{}'")
                connection.execute(
                    """INSERT INTO schema_migrations(version, applied_at) VALUES (1, ?)
                    ON CONFLICT (version) DO NOTHING""",
                    (utc_now(),),
                )
                connection.execute(
                    """INSERT INTO schema_migrations(version, applied_at) VALUES (2, ?)
                    ON CONFLICT (version) DO NOTHING""",
                    (utc_now(),),
                )

    def health(self) -> bool:
        try:
            with self._connect() as connection:
                connection.execute("SELECT 1").fetchone()
            return True
        except Exception:
            return False

    def find_document_by_hash(self, tenant_id: str, sha256: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM documents WHERE tenant_id = ? AND sha256 = ?",
                (tenant_id, sha256),
            ).fetchone()
        return self._document_from_row(row) if row else None

    def create_document(
        self,
        *,
        tenant_id: str,
        filename: str,
        sha256: str,
        visibility: str,
        departments: list[str],
    ) -> dict[str, Any]:
        document, _ = self.create_document_once(
            tenant_id=tenant_id,
            filename=filename,
            sha256=sha256,
            visibility=visibility,
            departments=departments,
        )
        return document

    def create_document_once(
        self,
        *,
        tenant_id: str,
        filename: str,
        sha256: str,
        visibility: str,
        departments: list[str],
    ) -> tuple[dict[str, Any], bool]:
        """Atomically claim a content hash so concurrent uploads stay idempotent."""

        document_id = str(uuid.uuid4())
        created_at = utc_now()
        with self._connect() as connection:
            previous = connection.execute(
                """SELECT COALESCE(MAX(version), 0) AS max_version
                FROM documents WHERE tenant_id = ? AND filename = ?""",
                (tenant_id, filename),
            ).fetchone()["max_version"]
            version = int(previous) + 1
            cursor = connection.execute(
                """INSERT INTO documents
                (id, tenant_id, filename, sha256, version, status, visibility, departments_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT (tenant_id, sha256) DO NOTHING""",
                (
                    document_id,
                    tenant_id,
                    filename,
                    sha256,
                    version,
                    visibility,
                    json.dumps(departments, ensure_ascii=False),
                    created_at,
                ),
            )
            created = cursor.rowcount > 0
            if not created:
                row = connection.execute(
                    "SELECT * FROM documents WHERE tenant_id = ? AND sha256 = ?",
                    (tenant_id, sha256),
                ).fetchone()
                if not row:
                    raise RuntimeError("Document deduplication conflict could not be resolved")
                document_id = str(row["id"])
        return self.get_document(document_id), created

    def claim_ingestion(
        self,
        *,
        tenant_id: str,
        filename: str,
        sha256: str,
        visibility: str,
        departments: list[str],
        audit: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], dict[str, Any], bool]:
        """Atomically claim the document and create or reuse its ingestion job."""

        document_id = str(uuid.uuid4())
        job_id = str(uuid.uuid4())
        now = utc_now()
        duplicate = False
        with self._connect() as connection:
            previous = connection.execute(
                """SELECT COALESCE(MAX(version), 0) AS max_version
                FROM documents WHERE tenant_id = ? AND filename = ?""",
                (tenant_id, filename),
            ).fetchone()["max_version"]
            cursor = connection.execute(
                """INSERT INTO documents
                (id, tenant_id, filename, sha256, version, status, visibility, departments_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)
                ON CONFLICT (tenant_id, sha256) DO NOTHING""",
                (
                    document_id,
                    tenant_id,
                    filename,
                    sha256,
                    int(previous) + 1,
                    visibility,
                    json.dumps(departments, ensure_ascii=False),
                    now,
                ),
            )
            if cursor.rowcount > 0:
                connection.execute(
                    "INSERT INTO ingestion_jobs VALUES (?, ?, 'pending', NULL, ?, ?)",
                    (job_id, document_id, now, now),
                )
            else:
                duplicate = True
                document_row = connection.execute(
                    "SELECT * FROM documents WHERE tenant_id = ? AND sha256 = ?",
                    (tenant_id, sha256),
                ).fetchone()
                if not document_row:
                    raise RuntimeError("Document deduplication conflict could not be resolved")
                document_id = str(document_row["id"])
                if document_row["status"] in {"pending", "processing"}:
                    job_row = connection.execute(
                        """SELECT * FROM ingestion_jobs WHERE document_id = ?
                        ORDER BY created_at DESC LIMIT 1""",
                        (document_id,),
                    ).fetchone()
                    if job_row:
                        job_id = str(job_row["id"])
                    else:
                        duplicate = False
                        connection.execute(
                            "INSERT INTO ingestion_jobs VALUES (?, ?, 'pending', NULL, ?, ?)",
                            (job_id, document_id, now, now),
                        )
                elif document_row["status"] == "ready":
                    connection.execute(
                        "INSERT INTO ingestion_jobs VALUES (?, ?, 'completed', NULL, ?, ?)",
                        (job_id, document_id, now, now),
                    )
                else:
                    duplicate = False
                    connection.execute(
                        "UPDATE documents SET status = 'pending' WHERE id = ?",
                        (document_id,),
                    )
                    connection.execute(
                        "INSERT INTO ingestion_jobs VALUES (?, ?, 'pending', NULL, ?, ?)",
                        (job_id, document_id, now, now),
                    )
            if audit and not duplicate:
                self._append_audit_with_connection(
                    connection,
                    tenant_id=tenant_id,
                    action=(
                        "document.upload.accepted"
                        if cursor.rowcount > 0
                        else "document.reingestion.accepted"
                    ),
                    resource_type="document",
                    resource_id=document_id,
                    details={
                        "filename": filename,
                        "visibility": visibility,
                        "departments": departments,
                        "sha256": sha256,
                        "job_id": job_id,
                    },
                    **audit,
                )
        return self.get_document(document_id), self.get_job(job_id), duplicate

    def create_job(self, document_id: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO ingestion_jobs VALUES (?, ?, 'pending', NULL, ?, ?)",
                (job_id, document_id, now, now),
            )
        return self.get_job(job_id)

    def get_latest_job_for_document(self, document_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT * FROM ingestion_jobs WHERE document_id = ?
                ORDER BY created_at DESC LIMIT 1""",
                (document_id,),
            ).fetchone()
        return dict(row) if row else None

    def list_recoverable_jobs(self, updated_before: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT j.*, d.filename FROM ingestion_jobs j
                JOIN documents d ON d.id = j.document_id
                WHERE j.status IN ('pending', 'queued', 'retrying', 'processing')
                  AND j.updated_at < ?
                ORDER BY j.updated_at ASC LIMIT ?""",
                (updated_before, max(1, min(limit, 1000))),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_job(self, job_id: str, status: str, error: str | None = None) -> None:
        with self._connect() as connection:
            connection.execute(
                "UPDATE ingestion_jobs SET status = ?, error = ?, updated_at = ? WHERE id = ?",
                (status, error, utc_now(), job_id),
            )

    def update_document_status(self, document_id: str, status: str) -> None:
        with self._connect() as connection:
            connection.execute("UPDATE documents SET status = ? WHERE id = ?", (status, document_id))

    def get_job(self, job_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM ingestion_jobs WHERE id = ?", (job_id,)).fetchone()
        if not row:
            raise KeyError(f"Job not found: {job_id}")
        return dict(row)

    def get_job_for_tenant(
        self,
        job_id: str,
        tenant_id: str,
        departments: list[str] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT j.*, d.visibility AS document_visibility,
                    d.departments_json AS document_departments_json
                FROM ingestion_jobs j
                JOIN documents d ON d.id = j.document_id
                WHERE j.id = ? AND d.tenant_id = ?""",
                (job_id, tenant_id),
            ).fetchone()
        if not row:
            raise KeyError(f"Job not found: {job_id}")
        result = dict(row)
        document_departments = json.loads(result.pop("document_departments_json"))
        visibility = result.pop("document_visibility")
        if departments is not None and visibility != "public":
            if not set(departments).intersection(document_departments):
                raise KeyError(f"Job not found: {job_id}")
        return result

    def get_document(self, document_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise KeyError(f"Document not found: {document_id}")
        return self._document_from_row(row)

    def list_documents(
        self,
        tenant_id: str,
        departments: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        documents = [self._document_from_row(row) for row in rows]
        if departments is None:
            return documents
        allowed = set(departments)
        return [
            document
            for document in documents
            if document["visibility"] == "public"
            or allowed.intersection(document["departments"])
        ]

    def delete_document(
        self,
        document_id: str,
        tenant_id: str,
        audit: dict[str, Any] | None = None,
    ) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM documents WHERE id = ? AND tenant_id = ?",
                (document_id, tenant_id),
            )
            if cursor.rowcount > 0 and audit:
                self._append_audit_with_connection(
                    connection,
                    tenant_id=tenant_id,
                    action="document.deleted",
                    resource_type="document",
                    resource_id=document_id,
                    details={},
                    **audit,
                )
        return cursor.rowcount > 0

    def insert_chunks(self, document: dict[str, Any], chunks: Iterable[ChunkDraft]) -> int:
        rows = []
        for index, chunk in enumerate(chunks):
            rows.append(
                (
                    str(uuid.uuid4()),
                    document["id"],
                    document["tenant_id"],
                    index,
                    chunk.content,
                    chunk.heading,
                    chunk.page_number,
                    document["visibility"],
                    json.dumps(document["departments"], ensure_ascii=False),
                    chunk.token_count,
                    json.dumps(chunk.metadata, ensure_ascii=False),
                )
            )
        with self._connect() as connection:
            connection.execute("DELETE FROM chunks WHERE document_id = ?", (document["id"],))
            connection.executemany(
                """INSERT INTO chunks
                (id, document_id, tenant_id, chunk_index, content, heading, page_number,
                 visibility, departments_json, token_count, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                rows,
            )
        return len(rows)

    def list_accessible_chunks(self, tenant_id: str, departments: list[str]) -> list[StoredChunk]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.*, d.filename
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.tenant_id = ? AND d.status = 'ready'""",
                (tenant_id,),
            ).fetchall()
        allowed = set(departments)
        chunks: list[StoredChunk] = []
        for row in rows:
            row_departments = json.loads(row["departments_json"])
            if row["visibility"] != "public" and not allowed.intersection(row_departments):
                continue
            chunks.append(
                StoredChunk(
                    id=row["id"],
                    document_id=row["document_id"],
                    tenant_id=row["tenant_id"],
                    chunk_index=row["chunk_index"],
                    content=row["content"],
                    heading=row["heading"],
                    page_number=row["page_number"],
                    visibility=row["visibility"],
                    departments=row_departments,
                    token_count=row["token_count"],
                    metadata=json.loads(row["metadata_json"]),
                    filename=row["filename"],
                )
            )
        return chunks

    def list_document_chunks(self, document_id: str) -> list[StoredChunk]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.*, d.filename
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE c.document_id = ? ORDER BY c.chunk_index""",
                (document_id,),
            ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def list_ready_chunks(self) -> list[StoredChunk]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.*, d.filename
                FROM chunks c JOIN documents d ON d.id = c.document_id
                WHERE d.status = 'ready' ORDER BY c.document_id, c.chunk_index"""
            ).fetchall()
        return [self._chunk_from_row(row) for row in rows]

    def save_conversation(
        self,
        *,
        tenant_id: str,
        user_id: str,
        question: str,
        answer: str,
        status: str,
        citations: list[dict[str, Any]],
        session_id: str = "",
        latency_ms: float = 0.0,
        debug: dict[str, Any] | None = None,
    ) -> str:
        conversation_id = str(uuid.uuid4())
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO conversations
                (id, tenant_id, user_id, question, answer, status, citations_json, created_at,
                 session_id, latency_ms, debug_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    conversation_id,
                    tenant_id,
                    user_id,
                    question,
                    answer,
                    status,
                    json.dumps(citations, ensure_ascii=False),
                    utc_now(),
                    session_id,
                    latency_ms,
                    json.dumps(debug or {}, ensure_ascii=False),
                ),
            )
        return conversation_id

    def list_conversations(
        self,
        *,
        tenant_id: str,
        user_id: str,
        session_id: str = "",
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        clauses = ["tenant_id = ?", "user_id = ?"]
        parameters: list[Any] = [tenant_id, user_id]
        if session_id:
            clauses.append("session_id = ?")
            parameters.append(session_id)
        parameters.append(max(1, min(limit, 100)))
        with self._connect() as connection:
            rows = connection.execute(
                f"""SELECT * FROM conversations WHERE {' AND '.join(clauses)}
                ORDER BY created_at DESC LIMIT ?""",
                parameters,
            ).fetchall()
        results: list[dict[str, Any]] = []
        for row in reversed(rows):
            item = dict(row)
            item["citations"] = json.loads(item.pop("citations_json"))
            item["debug"] = json.loads(item.pop("debug_json", "{}"))
            results.append(item)
        return results

    def save_feedback(
        self,
        *,
        conversation_id: str,
        tenant_id: str,
        user_id: str | None = None,
        rating: int,
        comment: str = "",
        audit: dict[str, Any] | None = None,
    ) -> str:
        if rating not in {-1, 1}:
            raise ValueError("rating must be -1 or 1")
        feedback_id = str(uuid.uuid4())
        with self._connect() as connection:
            clauses = ["id = ?", "tenant_id = ?"]
            parameters: list[Any] = [conversation_id, tenant_id]
            if user_id is not None:
                clauses.append("user_id = ?")
                parameters.append(user_id)
            conversation = connection.execute(
                f"SELECT id FROM conversations WHERE {' AND '.join(clauses)}",
                parameters,
            ).fetchone()
            if not conversation:
                raise KeyError("Conversation not found")
            row = connection.execute(
                """INSERT INTO feedback
                (id, conversation_id, tenant_id, rating, comment, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                ON CONFLICT (conversation_id) DO UPDATE SET
                    rating = excluded.rating,
                    comment = excluded.comment,
                    created_at = excluded.created_at
                RETURNING id""",
                (feedback_id, conversation_id, tenant_id, rating, comment.strip(), utc_now()),
            ).fetchone()
            if audit:
                self._append_audit_with_connection(
                    connection,
                    tenant_id=tenant_id,
                    action="feedback.recorded",
                    resource_type="conversation",
                    resource_id=conversation_id,
                    details={"rating": rating, "has_comment": bool(comment.strip())},
                    **audit,
                )
        return str(row["id"])

    def append_audit_event(
        self,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        request_id: str = "",
        source_ip_hash: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        with self._connect() as connection:
            if not self.is_postgres:
                connection.execute("BEGIN IMMEDIATE")
            event = self._append_audit_with_connection(
                connection,
                tenant_id=tenant_id,
                actor_id=actor_id,
                action=action,
                resource_type=resource_type,
                resource_id=resource_id,
                request_id=request_id,
                source_ip_hash=source_ip_hash,
                details=details or {},
            )
        return event

    def _append_audit_with_connection(
        self,
        connection: Any,
        *,
        tenant_id: str,
        actor_id: str,
        action: str,
        resource_type: str,
        resource_id: str,
        request_id: str = "",
        source_ip_hash: str = "",
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        if self.is_postgres:
            connection.execute("SELECT pg_advisory_xact_lock(hashtext(?))", (tenant_id,))
        previous = connection.execute(
            """SELECT sequence, event_hash FROM audit_events
            WHERE tenant_id = ? ORDER BY sequence DESC LIMIT 1""",
            (tenant_id,),
        ).fetchone()
        sequence = int(previous["sequence"]) + 1 if previous else 1
        previous_hash = str(previous["event_hash"]) if previous else ""
        created_at = utc_now()
        event_id = str(uuid.uuid4())
        normalized_details = details or {}
        event_hash = self._audit_hash(
            tenant_id=tenant_id,
            sequence=sequence,
            actor_id=actor_id,
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request_id,
            source_ip_hash=source_ip_hash,
            details=normalized_details,
            previous_hash=previous_hash,
            created_at=created_at,
        )
        connection.execute(
            """INSERT INTO audit_events
            (id, tenant_id, sequence, actor_id, action, resource_type, resource_id,
             request_id, source_ip_hash, details_json, previous_hash, event_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                event_id,
                tenant_id,
                sequence,
                actor_id,
                action,
                resource_type,
                resource_id,
                request_id,
                source_ip_hash,
                json.dumps(normalized_details, ensure_ascii=False, sort_keys=True),
                previous_hash,
                event_hash,
                created_at,
            ),
        )
        return {
            "id": event_id,
            "tenant_id": tenant_id,
            "sequence": sequence,
            "actor_id": actor_id,
            "action": action,
            "resource_type": resource_type,
            "resource_id": resource_id,
            "request_id": request_id,
            "source_ip_hash": source_ip_hash,
            "details": normalized_details,
            "previous_hash": previous_hash,
            "event_hash": event_hash,
            "created_at": created_at,
        }

    def list_audit_events(self, tenant_id: str, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT * FROM audit_events WHERE tenant_id = ?
                ORDER BY sequence DESC LIMIT ?""",
                (tenant_id, max(1, min(limit, 500))),
            ).fetchall()
        events = []
        for row in rows:
            event = dict(row)
            event["details"] = json.loads(event.pop("details_json"))
            events.append(event)
        return events

    def verify_audit_chain(self, tenant_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM audit_events WHERE tenant_id = ? ORDER BY sequence",
                (tenant_id,),
            ).fetchall()
        previous_hash = ""
        for expected_sequence, row in enumerate(rows, start=1):
            details = json.loads(row["details_json"])
            expected_hash = self._audit_hash(
                tenant_id=row["tenant_id"],
                sequence=expected_sequence,
                actor_id=row["actor_id"],
                action=row["action"],
                resource_type=row["resource_type"],
                resource_id=row["resource_id"],
                request_id=row["request_id"],
                source_ip_hash=row["source_ip_hash"],
                details=details,
                previous_hash=previous_hash,
                created_at=row["created_at"],
            )
            if (
                int(row["sequence"]) != expected_sequence
                or row["previous_hash"] != previous_hash
                or not hmac.compare_digest(row["event_hash"], expected_hash)
            ):
                return {
                    "valid": False,
                    "event_count": len(rows),
                    "first_invalid_sequence": expected_sequence,
                }
            previous_hash = row["event_hash"]
        return {"valid": True, "event_count": len(rows), "first_invalid_sequence": None}

    def _audit_hash(self, **event: Any) -> str:
        canonical = json.dumps(
            event,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        if self.audit_hmac_key:
            return hmac.new(self.audit_hmac_key, canonical, hashlib.sha256).hexdigest()
        return hashlib.sha256(canonical).hexdigest()

    def get_metrics(self, tenant_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            document_row = connection.execute(
                """SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready
                FROM documents WHERE tenant_id = ?""",
                (tenant_id,),
            ).fetchone()
            chunk_count = connection.execute(
                "SELECT COUNT(*) AS chunk_count FROM chunks WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()["chunk_count"]
            conversation_rows = connection.execute(
                "SELECT status, latency_ms FROM conversations WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchall()
            feedback_rows = connection.execute(
                "SELECT rating, COUNT(*) AS count FROM feedback WHERE tenant_id = ? GROUP BY rating",
                (tenant_id,),
            ).fetchall()
        latencies = sorted(float(row["latency_ms"]) for row in conversation_rows if row["latency_ms"])
        answered = sum(row["status"] == "answered" for row in conversation_rows)
        feedback = {int(row["rating"]): int(row["count"]) for row in feedback_rows}
        return {
            "documents": int(document_row["total"] or 0),
            "ready_documents": int(document_row["ready"] or 0),
            "chunks": int(chunk_count),
            "questions": len(conversation_rows),
            "answered": answered,
            "refused": len(conversation_rows) - answered,
            "average_latency_ms": round(sum(latencies) / len(latencies), 2) if latencies else 0.0,
            "p95_latency_ms": round(_percentile(latencies, 0.95), 2) if latencies else 0.0,
            "positive_feedback": feedback.get(1, 0),
            "negative_feedback": feedback.get(-1, 0),
        }

    @staticmethod
    def _ensure_column(
        connection: sqlite3.Connection,
        table: str,
        column: str,
        definition: str,
    ) -> None:
        columns = {row["name"] for row in connection.execute(f"PRAGMA table_info({table})")}
        if column not in columns:
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")

    @staticmethod
    def _document_from_row(row: Any) -> dict[str, Any]:
        result = dict(row)
        result["departments"] = json.loads(result.pop("departments_json"))
        return result

    @staticmethod
    def _chunk_from_row(row: Any) -> StoredChunk:
        return StoredChunk(
            id=row["id"],
            document_id=row["document_id"],
            tenant_id=row["tenant_id"],
            chunk_index=row["chunk_index"],
            content=row["content"],
            heading=row["heading"],
            page_number=row["page_number"],
            visibility=row["visibility"],
            departments=json.loads(row["departments_json"]),
            token_count=row["token_count"],
            metadata=json.loads(row["metadata_json"]),
            filename=row["filename"],
        )


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    index = max(0, min(len(values) - 1, int(round((len(values) - 1) * percentile))))
    return values[index]


class _PostgresConnection:
    """Small DB-API adapter keeping repository SQL backend-neutral."""

    def __init__(self, connection: Any):
        self.connection = connection

    def execute(self, query: str, parameters: Any = None):
        return self.connection.execute(query.replace("?", "%s"), parameters or ())

    def executemany(self, query: str, parameters: Any):
        with self.connection.cursor() as cursor:
            return cursor.executemany(query.replace("?", "%s"), parameters)
