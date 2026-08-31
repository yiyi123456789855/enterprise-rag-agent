from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from app.database import Repository
from ingestion.chunker import chunk_paragraphs
from ingestion.parsers import SUPPORTED_EXTENSIONS, parse_document
from retrieval.vector_store import VectorIndex


@dataclass(slots=True)
class EnqueuedIngestion:
    document: dict
    job: dict
    duplicate: bool


class IngestionService:
    def __init__(
        self,
        repository: Repository,
        *,
        chunk_size: int = 320,
        chunk_overlap: int = 60,
        vector_index: VectorIndex | None = None,
    ):
        self.repository = repository
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.vector_index = vector_index

    def enqueue(
        self,
        *,
        filename: str,
        content: bytes,
        tenant_id: str,
        visibility: str = "public",
        departments: list[str] | None = None,
    ) -> EnqueuedIngestion:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")
        if visibility not in {"public", "department"}:
            raise ValueError("visibility must be 'public' or 'department'")
        normalized_departments = sorted({item.strip() for item in (departments or []) if item.strip()})
        if visibility == "department" and not normalized_departments:
            raise ValueError("department visibility requires at least one department")

        digest = hashlib.sha256(content).hexdigest()
        existing = self.repository.find_document_by_hash(tenant_id, digest)
        if existing:
            if self.vector_index is not None and existing["status"] == "ready":
                self.vector_index.upsert(self.repository.list_document_chunks(existing["id"]))
            job = self.repository.create_job(existing["id"])
            self.repository.update_job(job["id"], "completed")
            return EnqueuedIngestion(existing, self.repository.get_job(job["id"]), True)

        document = self.repository.create_document(
            tenant_id=tenant_id,
            filename=Path(filename).name,
            sha256=digest,
            visibility=visibility,
            departments=normalized_departments,
        )
        job = self.repository.create_job(document["id"])
        return EnqueuedIngestion(document, job, False)

    def process(self, job_id: str, document_id: str, filename: str, content: bytes) -> int:
        self.repository.update_job(job_id, "processing")
        self.repository.update_document_status(document_id, "processing")
        try:
            parsed = parse_document(filename, content)
            chunks = chunk_paragraphs(
                parsed.paragraphs,
                chunk_size=self.chunk_size,
                overlap=self.chunk_overlap,
            )
            if not chunks:
                raise ValueError("No readable text was extracted from the document")
            document = self.repository.get_document(document_id)
            count = self.repository.insert_chunks(document, chunks)
            if self.vector_index is not None:
                self.vector_index.upsert(self.repository.list_document_chunks(document_id))
            self.repository.update_document_status(document_id, "ready")
            self.repository.update_job(job_id, "completed")
            return count
        except Exception as exc:
            self.repository.update_document_status(document_id, "failed")
            self.repository.update_job(job_id, "failed", str(exc))
            raise
