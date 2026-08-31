from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Settings:
    app_name: str = "Enterprise Knowledge RAG Agent"
    data_dir: Path = Path("data")
    database_path: Path = Path("data/rag.db")
    max_upload_mb: int = 30
    chunk_size: int = 320
    chunk_overlap: int = 60
    retrieval_top_k: int = 5
    evidence_min_coverage: float = 0.20
    evidence_min_anchor_coverage: float = 0.20
    retrieval_backend: str = "local"
    embedding_model: str = "BAAI/bge-m3"
    embedding_device: str = "cpu"
    qdrant_url: str = "http://qdrant:6333"
    qdrant_api_key: str = ""
    qdrant_collection: str = "enterprise_knowledge"
    reranker_enabled: bool = False
    reranker_model: str = "BAAI/bge-reranker-v2-m3"
    reranker_device: str = "cpu"
    rerank_candidates: int = 20
    app_api_key: str = ""
    llm_base_url: str = ""
    llm_api_key: str = ""
    llm_model: str = ""

    @classmethod
    def from_env(cls) -> "Settings":
        data_dir = Path(os.getenv("DATA_DIR", "data"))
        return cls(
            app_name=os.getenv("APP_NAME", cls.app_name),
            data_dir=data_dir,
            database_path=Path(os.getenv("DATABASE_PATH", str(data_dir / "rag.db"))),
            max_upload_mb=int(os.getenv("MAX_UPLOAD_MB", "30")),
            chunk_size=int(os.getenv("CHUNK_SIZE", "320")),
            chunk_overlap=int(os.getenv("CHUNK_OVERLAP", "60")),
            retrieval_top_k=int(os.getenv("RETRIEVAL_TOP_K", "5")),
            evidence_min_coverage=float(os.getenv("EVIDENCE_MIN_COVERAGE", "0.20")),
            evidence_min_anchor_coverage=float(os.getenv("EVIDENCE_MIN_ANCHOR_COVERAGE", "0.20")),
            retrieval_backend=os.getenv("RETRIEVAL_BACKEND", "local").lower(),
            embedding_model=os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3"),
            embedding_device=os.getenv("EMBEDDING_DEVICE", "cpu"),
            qdrant_url=os.getenv("QDRANT_URL", "http://qdrant:6333").rstrip("/"),
            qdrant_api_key=os.getenv("QDRANT_API_KEY", ""),
            qdrant_collection=os.getenv("QDRANT_COLLECTION", "enterprise_knowledge"),
            reranker_enabled=_env_bool("RERANKER_ENABLED", False),
            reranker_model=os.getenv("RERANKER_MODEL", "BAAI/bge-reranker-v2-m3"),
            reranker_device=os.getenv("RERANKER_DEVICE", os.getenv("EMBEDDING_DEVICE", "cpu")),
            rerank_candidates=int(os.getenv("RERANK_CANDIDATES", "20")),
            app_api_key=os.getenv("APP_API_KEY", ""),
            llm_base_url=os.getenv("LLM_BASE_URL", "").rstrip("/"),
            llm_api_key=os.getenv("LLM_API_KEY", ""),
            llm_model=os.getenv("LLM_MODEL", ""),
        )

    def ensure_directories(self) -> None:
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path.parent.mkdir(parents=True, exist_ok=True)


def _env_bool(name: str, default: bool) -> bool:
    value = os.getenv(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}
