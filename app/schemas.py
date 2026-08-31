from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class DocumentResponse(BaseModel):
    id: str
    tenant_id: str
    filename: str
    version: int
    status: str
    visibility: str
    departments: list[str]
    created_at: datetime


class UploadResponse(BaseModel):
    document_id: str
    job_id: str
    status: str
    duplicate: bool = False


class JobResponse(BaseModel):
    id: str
    document_id: str
    status: str
    error: str | None = None
    created_at: datetime
    updated_at: datetime


class ChatRequest(BaseModel):
    question: str = Field(min_length=2, max_length=2000)
    tenant_id: str = Field(default="default", min_length=1, max_length=100)
    user_id: str = Field(default="anonymous", max_length=100)
    departments: list[str] = Field(default_factory=list)
    top_k: int = Field(default=5, ge=1, le=20)
    session_id: str = Field(default="", max_length=100)


class Citation(BaseModel):
    index: int
    document_id: str
    filename: str
    chunk_id: str
    heading: str | None = None
    page_number: int | None = None
    quote: str
    score: float


class RetrievalDebug(BaseModel):
    top_score: float = 0.0
    query_coverage: float = 0.0
    anchor_coverage: float = 0.0
    reason: str = ""
    candidate_count: int = 0
    retrieval_query: str = ""
    retrieval_ms: float = 0.0
    generation_ms: float = 0.0
    total_ms: float = 0.0


class ChatResponse(BaseModel):
    status: Literal["answered", "insufficient_evidence"]
    answer: str
    citations: list[Citation]
    debug: RetrievalDebug | None = None
    conversation_id: str
    session_id: str


class ConversationResponse(BaseModel):
    id: str
    session_id: str
    question: str
    answer: str
    status: str
    citations: list[dict[str, Any]]
    latency_ms: float
    created_at: datetime


class FeedbackRequest(BaseModel):
    conversation_id: str = Field(min_length=1, max_length=100)
    tenant_id: str = Field(default="default", min_length=1, max_length=100)
    rating: Literal[-1, 1]
    comment: str = Field(default="", max_length=1000)


class FeedbackResponse(BaseModel):
    id: str
    status: str = "recorded"


class MetricsResponse(BaseModel):
    tenant_id: str
    metrics: dict[str, Any]


class HealthResponse(BaseModel):
    status: str
    details: dict[str, Any]
