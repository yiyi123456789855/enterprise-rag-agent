from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from pathlib import Path

from app.database import Repository
from ingestion.chunker import chunk_paragraphs
from ingestion.parsers import SUPPORTED_EXTENSIONS, parse_document
from retrieval.vector_store import VectorIndex


logger = logging.getLogger(__name__)


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
        audit: dict | None = None,
    ) -> EnqueuedIngestion:
        digest = hashlib.sha256(content).hexdigest()
        return self._enqueue_with_digest(
            filename=filename,
            digest=digest,
            tenant_id=tenant_id,
            visibility=visibility,
            departments=departments,
            audit=audit,
        )

    def enqueue_file(
        self,
        *,
        filename: str,
        content_path: str | Path,
        tenant_id: str,
        visibility: str = "public",
        departments: list[str] | None = None,
        audit: dict | None = None,
    ) -> EnqueuedIngestion:
        digest = _sha256_file(Path(content_path))
        return self._enqueue_with_digest(
            filename=filename,
            digest=digest,
            tenant_id=tenant_id,
            visibility=visibility,
            departments=departments,
            audit=audit,
        )

    def _enqueue_with_digest(
        self,
        *,
        filename: str,
        digest: str,
        tenant_id: str,
        visibility: str,
        departments: list[str] | None,
        audit: dict | None,
    ) -> EnqueuedIngestion:
        suffix = Path(filename).suffix.lower()
        if suffix not in SUPPORTED_EXTENSIONS:
            raise ValueError(f"Unsupported file type: {suffix or 'unknown'}")
        if visibility not in {"public", "department"}:
            raise ValueError("visibility must be 'public' or 'department'")
        normalized_departments = sorted({item.strip() for item in (departments or []) if item.strip()})
        if visibility == "department" and not normalized_departments:
            raise ValueError("department visibility requires at least one department")

        document, job, duplicate = self.repository.claim_ingestion(
            tenant_id=tenant_id,
            filename=Path(filename).name,
            sha256=digest,
            visibility=visibility,
            departments=normalized_departments,
            audit=audit,
        )
        if duplicate and self.vector_index is not None and document["status"] == "ready":
            self.vector_index.upsert(self.repository.list_document_chunks(document["id"]))
        return EnqueuedIngestion(document, job, duplicate)

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
            from app.errors import public_error

            logger.error(
                "Ingestion failed job_id=%s document_id=%s error_type=%s",
                job_id,
                document_id,
                type(exc).__name__,
            )
            self.repository.update_document_status(document_id, "failed")
            self.repository.update_job(job_id, "failed", public_error(exc))
            raise

    def process_file(
        self,
        job_id: str,
        document_id: str,
        filename: str,
        content_path: str | Path,
    ) -> int:
        return self.process(job_id, document_id, filename, Path(content_path).read_bytes())


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
