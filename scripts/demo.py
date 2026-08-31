from __future__ import annotations

import json
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from agent.generators import ExtractiveAnswerGenerator
from agent.service import RAGService
from agent.workflow import RAGWorkflow
from app.database import Repository
from ingestion.service import IngestionService
from retrieval.evidence import EvidenceGate
from retrieval.hybrid import HybridRetriever


def main() -> None:
    database_path = PROJECT_ROOT / "data" / "demo.db"
    repository = Repository(database_path)
    repository.initialize()
    ingestion = IngestionService(repository)

    source = PROJECT_ROOT / "examples" / "company_handbook.md"
    content = source.read_bytes()
    task = ingestion.enqueue(
        filename=source.name,
        content=content,
        tenant_id="demo-company",
        visibility="public",
    )
    if not task.duplicate:
        ingestion.process(task.job["id"], task.document["id"], source.name, content)

    rag = RAGService(
        repository,
        RAGWorkflow(HybridRetriever(repository), EvidenceGate(), ExtractiveAnswerGenerator()),
    )
    result = rag.ask(
        question="年假需要提前多久申请？",
        tenant_id="demo-company",
        user_id="demo-user",
        departments=[],
        top_k=3,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()

