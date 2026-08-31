from __future__ import annotations

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
    """Small SQLite repository used by the local MVP.

    Every operation opens a short-lived connection, making the class safe to use
    from FastAPI background tasks. Tenant and department filters are enforced
    before chunks reach the retriever.
    """

    def __init__(self, database_path: str | Path):
        self.database_path = str(database_path)
        self._schema_lock = threading.Lock()

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.database_path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA journal_mode = WAL")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        Path(self.database_path).parent.mkdir(parents=True, exist_ok=True)
        with self._schema_lock, self._connect() as connection:
            connection.executescript(
                """
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

                CREATE TABLE IF NOT EXISTS ingestion_jobs (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id) ON DELETE CASCADE
                );

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
                """
            )
            self._ensure_column(connection, "conversations", "session_id", "TEXT NOT NULL DEFAULT ''")
            self._ensure_column(connection, "conversations", "latency_ms", "REAL NOT NULL DEFAULT 0")
            self._ensure_column(connection, "conversations", "debug_json", "TEXT NOT NULL DEFAULT '{}'")

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
        document_id = str(uuid.uuid4())
        created_at = utc_now()
        with self._connect() as connection:
            previous = connection.execute(
                "SELECT COALESCE(MAX(version), 0) FROM documents WHERE tenant_id = ? AND filename = ?",
                (tenant_id, filename),
            ).fetchone()[0]
            version = int(previous) + 1
            connection.execute(
                """INSERT INTO documents
                (id, tenant_id, filename, sha256, version, status, visibility, departments_json, created_at)
                VALUES (?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
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
        return self.get_document(document_id)

    def create_job(self, document_id: str) -> dict[str, Any]:
        job_id = str(uuid.uuid4())
        now = utc_now()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO ingestion_jobs VALUES (?, ?, 'pending', NULL, ?, ?)",
                (job_id, document_id, now, now),
            )
        return self.get_job(job_id)

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

    def get_document(self, document_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
        if not row:
            raise KeyError(f"Document not found: {document_id}")
        return self._document_from_row(row)

    def list_documents(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM documents WHERE tenant_id = ? ORDER BY created_at DESC",
                (tenant_id,),
            ).fetchall()
        return [self._document_from_row(row) for row in rows]

    def delete_document(self, document_id: str, tenant_id: str) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "DELETE FROM documents WHERE id = ? AND tenant_id = ?",
                (document_id, tenant_id),
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
        rating: int,
        comment: str = "",
    ) -> str:
        if rating not in {-1, 1}:
            raise ValueError("rating must be -1 or 1")
        feedback_id = str(uuid.uuid4())
        with self._connect() as connection:
            conversation = connection.execute(
                "SELECT id FROM conversations WHERE id = ? AND tenant_id = ?",
                (conversation_id, tenant_id),
            ).fetchone()
            if not conversation:
                raise KeyError("Conversation not found")
            existing = connection.execute(
                "SELECT id FROM feedback WHERE conversation_id = ?",
                (conversation_id,),
            ).fetchone()
            if existing:
                connection.execute(
                    "UPDATE feedback SET rating = ?, comment = ?, created_at = ? WHERE id = ?",
                    (rating, comment.strip(), utc_now(), existing["id"]),
                )
                return str(existing["id"])
            connection.execute(
                "INSERT INTO feedback VALUES (?, ?, ?, ?, ?, ?)",
                (feedback_id, conversation_id, tenant_id, rating, comment.strip(), utc_now()),
            )
        return feedback_id

    def get_metrics(self, tenant_id: str) -> dict[str, Any]:
        with self._connect() as connection:
            document_row = connection.execute(
                """SELECT COUNT(*) AS total,
                SUM(CASE WHEN status = 'ready' THEN 1 ELSE 0 END) AS ready
                FROM documents WHERE tenant_id = ?""",
                (tenant_id,),
            ).fetchone()
            chunk_count = connection.execute(
                "SELECT COUNT(*) FROM chunks WHERE tenant_id = ?",
                (tenant_id,),
            ).fetchone()[0]
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
    def _document_from_row(row: sqlite3.Row) -> dict[str, Any]:
        result = dict(row)
        result["departments"] = json.loads(result.pop("departments_json"))
        return result

    @staticmethod
    def _chunk_from_row(row: sqlite3.Row) -> StoredChunk:
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
