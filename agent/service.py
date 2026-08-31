from __future__ import annotations

import uuid
from time import perf_counter
from typing import Any

from agent.workflow import AgentState, RAGWorkflow
from app.database import Repository


class RAGService:
    def __init__(self, repository: Repository, workflow: RAGWorkflow):
        self.repository = repository
        self.workflow = workflow

    def ask(
        self,
        *,
        question: str,
        tenant_id: str,
        user_id: str,
        departments: list[str],
        top_k: int,
        session_id: str = "",
    ) -> dict[str, Any]:
        started = perf_counter()
        resolved_session_id = session_id.strip() or str(uuid.uuid4())
        history = self.repository.list_conversations(
            tenant_id=tenant_id,
            user_id=user_id,
            session_id=resolved_session_id,
            limit=6,
        )
        state = self.workflow.run(
            AgentState(
                question=question,
                tenant_id=tenant_id,
                departments=departments,
                top_k=top_k,
                history_questions=[item["question"] for item in history],
            )
        )
        citations = []
        if state.status == "answered":
            for index, hit in enumerate(state.hits, start=1):
                quote = hit.chunk.content.replace("\n", " ").strip()
                citations.append(
                    {
                        "index": index,
                        "document_id": hit.chunk.document_id,
                        "filename": hit.chunk.filename,
                        "chunk_id": hit.chunk.id,
                        "heading": hit.chunk.heading,
                        "page_number": hit.chunk.page_number,
                        "quote": quote[:240] + ("…" if len(quote) > 240 else ""),
                        "score": round(hit.score, 4),
                    }
                )
        evidence = state.evidence
        total_ms = (perf_counter() - started) * 1000
        debug = {
            "top_score": round(evidence.top_score, 4) if evidence else 0.0,
            "query_coverage": round(evidence.query_coverage, 4) if evidence else 0.0,
            "anchor_coverage": round(evidence.anchor_coverage, 4) if evidence else 0.0,
            "reason": evidence.reason if evidence else "",
            "candidate_count": len(state.hits),
            "retrieval_query": state.retrieval_query or state.question,
            "retrieval_ms": round(state.retrieval_ms, 2),
            "generation_ms": round(state.generation_ms, 2),
            "total_ms": round(total_ms, 2),
        }
        conversation_id = self.repository.save_conversation(
            tenant_id=tenant_id,
            user_id=user_id,
            question=question,
            answer=state.answer,
            status=state.status,
            citations=citations,
            session_id=resolved_session_id,
            latency_ms=total_ms,
            debug=debug,
        )
        return {
            "status": state.status,
            "answer": state.answer,
            "citations": citations,
            "debug": debug,
            "conversation_id": conversation_id,
            "session_id": resolved_session_id,
        }
