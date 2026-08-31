"""Offline portfolio evaluator for retrieval, decisions, answers and latency."""

from __future__ import annotations

import argparse
import json
import re
import statistics
from pathlib import Path

from agent.generators import ExtractiveAnswerGenerator
from agent.service import RAGService
from agent.workflow import RAGWorkflow
from app.database import Repository
from ingestion.service import IngestionService
from retrieval.evidence import EvidenceGate
from retrieval.hybrid import HybridRetriever


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", default="data/evaluation.db")
    parser.add_argument("--dataset", default="evaluation/golden_portfolio.jsonl")
    parser.add_argument("--tenant", default="demo-company")
    parser.add_argument("--bootstrap", nargs="*", default=[])
    parser.add_argument("--output", default="evaluation/latest_report.json")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    repository = Repository(args.database)
    repository.initialize()
    ingestion = IngestionService(repository)
    for raw_path in args.bootstrap:
        path = Path(raw_path)
        content = path.read_bytes()
        task = ingestion.enqueue(
            filename=path.name,
            content=content,
            tenant_id=args.tenant,
            visibility="public",
        )
        if not task.duplicate:
            ingestion.process(task.job["id"], task.document["id"], path.name, content)

    retriever = HybridRetriever(repository)
    rag = RAGService(
        repository,
        RAGWorkflow(retriever, EvidenceGate(), ExtractiveAnswerGenerator()),
    )
    examples = _load_jsonl(Path(args.dataset))
    retrieval_ranks: list[int] = []
    retrieval_cases = 0
    correct_decisions = 0
    keyword_scores: list[float] = []
    latencies: list[float] = []
    failures: list[dict] = []

    for index, example in enumerate(examples, start=1):
        departments = example.get("departments", [])
        hits = retriever.search(
            example["question"],
            tenant_id=args.tenant,
            departments=departments,
            top_k=args.top_k,
        )
        expected_document = example.get("expected_document")
        rank = 0
        if expected_document:
            retrieval_cases += 1
            for position, hit in enumerate(hits, start=1):
                if hit.chunk.filename == expected_document:
                    rank = position
                    break
            retrieval_ranks.append(rank)

        result = rag.ask(
            question=example["question"],
            tenant_id=args.tenant,
            user_id="offline-evaluator",
            departments=departments,
            top_k=args.top_k,
            session_id=f"eval-{index}",
        )
        answered = result["status"] == "answered"
        decision_ok = answered == bool(example["should_answer"])
        correct_decisions += int(decision_ok)
        latencies.append(float(result["debug"]["total_ms"]))

        expected_terms = example.get("expected_terms", [])
        expected_patterns = example.get("expected_patterns", [])
        term_score = 1.0
        expectation_count = len(expected_terms) + len(expected_patterns)
        if expectation_count:
            matched = sum(term in result["answer"] for term in expected_terms)
            matched += sum(bool(re.search(pattern, result["answer"])) for pattern in expected_patterns)
            term_score = matched / expectation_count
            keyword_scores.append(term_score)
        if not decision_ok or (expected_document and rank == 0) or term_score < 1.0:
            failures.append(
                {
                    "question": example["question"],
                    "status": result["status"],
                    "expected_should_answer": example["should_answer"],
                    "retrieval_rank": rank,
                    "term_score": round(term_score, 4),
                    "reason": result["debug"]["reason"],
                }
            )

    total = max(1, len(examples))
    report = {
        "dataset": str(args.dataset),
        "examples": len(examples),
        "retrieval_cases": retrieval_cases,
        "recall_at_1": _recall_at(retrieval_ranks, 1),
        "recall_at_3": _recall_at(retrieval_ranks, 3),
        "recall_at_5": _recall_at(retrieval_ranks, 5),
        "mrr": round(sum(1 / rank for rank in retrieval_ranks if rank) / max(1, retrieval_cases), 4),
        "decision_accuracy": round(correct_decisions / total, 4),
        "answer_keyword_recall": round(statistics.mean(keyword_scores), 4) if keyword_scores else 0.0,
        "latency_p50_ms": round(_percentile(latencies, 0.50), 2),
        "latency_p95_ms": round(_percentile(latencies, 0.95), 2),
        "failures": failures,
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report, ensure_ascii=False, indent=2))


def _load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]


def _recall_at(ranks: list[int], k: int) -> float:
    return round(sum(0 < rank <= k for rank in ranks) / max(1, len(ranks)), 4)


def _percentile(values: list[float], percentile: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(round((len(ordered) - 1) * percentile))))
    return ordered[index]


if __name__ == "__main__":
    main()
