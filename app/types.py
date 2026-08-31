from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(slots=True)
class Paragraph:
    text: str
    heading: str | None = None
    page_number: int | None = None


@dataclass(slots=True)
class ChunkDraft:
    content: str
    heading: str | None
    page_number: int | None
    token_count: int
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class StoredChunk:
    id: str
    document_id: str
    tenant_id: str
    chunk_index: int
    content: str
    heading: str | None
    page_number: int | None
    visibility: str
    departments: list[str]
    token_count: int
    metadata: dict[str, Any]
    filename: str = ""


@dataclass(slots=True)
class SearchHit:
    chunk: StoredChunk
    score: float
    dense_score: float
    sparse_score: float
    rerank_score: float

