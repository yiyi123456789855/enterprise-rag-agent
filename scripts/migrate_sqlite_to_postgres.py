from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path

from app.database import Repository


TABLE_COLUMNS = {
    "documents": (
        "id", "tenant_id", "filename", "sha256", "version", "status",
        "visibility", "departments_json", "created_at",
    ),
    "ingestion_jobs": (
        "id", "document_id", "status", "error", "created_at", "updated_at",
    ),
    "chunks": (
        "id", "document_id", "tenant_id", "chunk_index", "content", "heading",
        "page_number", "visibility", "departments_json", "token_count", "metadata_json",
    ),
    "conversations": (
        "id", "tenant_id", "user_id", "question", "answer", "status",
        "citations_json", "created_at", "session_id", "latency_ms", "debug_json",
    ),
    "feedback": (
        "id", "conversation_id", "tenant_id", "rating", "comment", "created_at",
    ),
    "audit_events": (
        "id", "tenant_id", "sequence", "actor_id", "action", "resource_type",
        "resource_id", "request_id", "source_ip_hash", "details_json",
        "previous_hash", "event_hash", "created_at",
    ),
}


def main() -> int:
    parser = argparse.ArgumentParser(description="One-time SQLite to PostgreSQL metadata migration")
    parser.add_argument("--sqlite", required=True, help="Path to the existing rag.db")
    parser.add_argument("--database-url", default=os.getenv("DATABASE_URL", ""))
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    sqlite_path = Path(args.sqlite)
    if not sqlite_path.is_file():
        raise SystemExit(f"SQLite database not found: {sqlite_path}")
    if not args.database_url.startswith(("postgresql://", "postgres://")):
        raise SystemExit("--database-url must be a PostgreSQL URL")

    source_repository = Repository(sqlite_path)
    source_repository.initialize()
    target_repository = Repository(args.database_url)
    target_repository.initialize()
    try:
        source = sqlite3.connect(sqlite_path)
        source.row_factory = sqlite3.Row
        try:
            with target_repository._connect() as target:
                target_counts = {
                    table: target.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"]
                    for table in TABLE_COLUMNS
                }
                if any(target_counts.values()):
                    raise SystemExit("Target PostgreSQL database is not empty; migration aborted")
                counts = {
                    table: source.execute(f"SELECT COUNT(*) AS total FROM {table}").fetchone()["total"]
                    for table in TABLE_COLUMNS
                }
                print("Rows to migrate:", counts)
                if args.dry_run:
                    return 0

                for table, columns in TABLE_COLUMNS.items():
                    rows = source.execute(
                        f"SELECT {', '.join(columns)} FROM {table}"
                    ).fetchall()
                    if not rows:
                        continue
                    placeholders = ", ".join("?" for _ in columns)
                    values = [tuple(row[column] for column in columns) for row in rows]
                    target.executemany(
                        f"INSERT INTO {table} ({', '.join(columns)}) VALUES ({placeholders})",
                        values,
                    )
                    print(f"Migrated {table}: {len(rows)}")
        finally:
            source.close()
    finally:
        target_repository.close()

    print("Metadata migration completed. Run scripts/reindex.py to rebuild Qdrant payloads.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
