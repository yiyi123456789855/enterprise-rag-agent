from __future__ import annotations

from functools import lru_cache

from agent.generators import ExtractiveAnswerGenerator, OpenAICompatibleGenerator
from agent.service import RAGService
from agent.workflow import RAGWorkflow
from app.config import Settings
from app.database import Repository
from ingestion.service import IngestionService
from retrieval.evidence import EvidenceGate
from retrieval.embeddings import HashingEmbedder, SentenceTransformerEmbedder
from retrieval.hybrid import HybridRetriever
from retrieval.rerankers import CrossEncoderReranker, LexicalReranker
from retrieval.vector_store import QdrantVectorIndex, VectorIndex


@lru_cache
def get_settings() -> Settings:
    settings = Settings.from_env()
    settings.ensure_directories()
    return settings


@lru_cache
def get_repository() -> Repository:
    repository = Repository(get_settings().database_path)
    repository.initialize()
    return repository


@lru_cache
def get_ingestion_service() -> IngestionService:
    settings = get_settings()
    return IngestionService(
        get_repository(),
        chunk_size=settings.chunk_size,
        chunk_overlap=settings.chunk_overlap,
        vector_index=get_vector_index(),
    )


@lru_cache
def get_embedder():
    settings = get_settings()
    if settings.retrieval_backend == "qdrant":
        return SentenceTransformerEmbedder(settings.embedding_model, settings.embedding_device)
    return HashingEmbedder()


@lru_cache
def get_vector_index() -> VectorIndex | None:
    settings = get_settings()
    if settings.retrieval_backend == "local":
        return None
    if settings.retrieval_backend != "qdrant":
        raise RuntimeError(f"Unsupported RETRIEVAL_BACKEND: {settings.retrieval_backend}")
    return QdrantVectorIndex(
        url=settings.qdrant_url,
        api_key=settings.qdrant_api_key,
        collection_name=settings.qdrant_collection,
        embedder=get_embedder(),
    )


@lru_cache
def get_reranker():
    settings = get_settings()
    if not settings.reranker_enabled:
        return LexicalReranker()
    return CrossEncoderReranker(settings.reranker_model, settings.reranker_device)


@lru_cache
def get_rag_service() -> RAGService:
    settings = get_settings()
    generator = ExtractiveAnswerGenerator()
    if settings.llm_base_url and settings.llm_model:
        generator = OpenAICompatibleGenerator(
            base_url=settings.llm_base_url,
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    workflow = RAGWorkflow(
        HybridRetriever(
            get_repository(),
            get_embedder(),
            get_vector_index(),
            reranker=get_reranker(),
            candidate_k=settings.rerank_candidates,
        ),
        EvidenceGate(
            min_coverage=settings.evidence_min_coverage,
            min_anchor_coverage=settings.evidence_min_anchor_coverage,
        ),
        generator,
    )
    return RAGService(get_repository(), workflow)
