from __future__ import annotations

import math
from collections import Counter

from app.database import Repository
from app.types import SearchHit, StoredChunk
from retrieval.embeddings import Embedder, HashingEmbedder, cosine_similarity
from retrieval.rerankers import LexicalReranker, Reranker
from retrieval.tokenizer import tokenize
from retrieval.vector_store import VectorIndex


class HybridRetriever:
    def __init__(
        self,
        repository: Repository,
        embedder: Embedder | None = None,
        vector_index: VectorIndex | None = None,
        reranker: Reranker | None = None,
        candidate_k: int = 20,
    ):
        self.repository = repository
        self.embedder = embedder or HashingEmbedder()
        self.vector_index = vector_index
        self.reranker = reranker or LexicalReranker()
        self.candidate_k = max(1, candidate_k)

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        departments: list[str],
        top_k: int = 5,
    ) -> list[SearchHit]:
        chunks = self.repository.list_accessible_chunks(tenant_id, departments)
        if not chunks:
            return []
        dense = self._dense_scores(
            query,
            chunks,
            tenant_id=tenant_id,
            departments=departments,
            limit=max(40, top_k * 10),
        )
        sparse = self._bm25_scores(query, chunks)
        dense_rank = _rank_map(dense)
        sparse_rank = _rank_map(sparse)
        fused: dict[str, float] = {}
        for chunk in chunks:
            fused[chunk.id] = 1.0 / (60 + dense_rank[chunk.id]) + 1.0 / (60 + sparse_rank[chunk.id])
        fused_max = max(fused.values()) or 1.0

        preliminary: list[tuple[StoredChunk, float]] = []
        for chunk in chunks:
            rerank = self._lexical_rerank(query, chunk)
            preliminary_score = 0.40 * (fused[chunk.id] / fused_max) + 0.60 * rerank
            preliminary.append((chunk, preliminary_score))

        preliminary.sort(key=lambda item: (item[1], sparse[item[0].id]), reverse=True)
        candidates = preliminary[: max(top_k, self.candidate_k)]
        semantic_scores = self.reranker.score(query, [chunk.content for chunk, _ in candidates])

        results: list[SearchHit] = []
        for (chunk, preliminary_score), rerank_score in zip(candidates, semantic_scores):
            if isinstance(self.reranker, LexicalReranker):
                final_score = preliminary_score
            else:
                final_score = 0.25 * preliminary_score + 0.75 * rerank_score
            results.append(
                SearchHit(
                    chunk=chunk,
                    score=final_score,
                    dense_score=dense[chunk.id],
                    sparse_score=sparse[chunk.id],
                    rerank_score=rerank_score,
                )
            )
        results.sort(key=lambda item: (item.score, item.sparse_score), reverse=True)
        return results[:top_k]

    def _dense_scores(
        self,
        query: str,
        chunks: list[StoredChunk],
        *,
        tenant_id: str,
        departments: list[str],
        limit: int,
    ) -> dict[str, float]:
        if self.vector_index is not None:
            remote_scores = self.vector_index.search(
                query,
                tenant_id=tenant_id,
                departments=departments,
                limit=limit,
            )
            accessible_ids = {chunk.id for chunk in chunks}
            return {chunk.id: remote_scores.get(chunk.id, 0.0) for chunk in chunks if chunk.id in accessible_ids}
        query_vector = self.embedder.embed(query)
        return {
            chunk.id: max(0.0, cosine_similarity(query_vector, self.embedder.embed(chunk.content)))
            for chunk in chunks
        }

    @staticmethod
    def _bm25_scores(query: str, chunks: list[StoredChunk]) -> dict[str, float]:
        query_terms = tokenize(query, remove_stopwords=True)
        documents = [tokenize(chunk.content, remove_stopwords=True) for chunk in chunks]
        if not query_terms:
            return {chunk.id: 0.0 for chunk in chunks}
        average_length = sum(len(doc) for doc in documents) / max(1, len(documents))
        document_frequency = Counter()
        for document in documents:
            document_frequency.update(set(document))
        raw_scores: dict[str, float] = {}
        n_docs = len(documents)
        for chunk, document in zip(chunks, documents):
            frequencies = Counter(document)
            score = 0.0
            for term in query_terms:
                frequency = frequencies[term]
                if not frequency:
                    continue
                idf = math.log(1 + (n_docs - document_frequency[term] + 0.5) / (document_frequency[term] + 0.5))
                denominator = frequency + 1.5 * (1 - 0.75 + 0.75 * len(document) / max(1.0, average_length))
                score += idf * (frequency * 2.5) / denominator
            raw_scores[chunk.id] = score
        maximum = max(raw_scores.values()) or 1.0
        return {chunk_id: score / maximum for chunk_id, score in raw_scores.items()}

    @staticmethod
    def _lexical_rerank(query: str, chunk: StoredChunk) -> float:
        query_tokens = set(tokenize(query, remove_stopwords=True))
        content_tokens = set(tokenize(chunk.content, remove_stopwords=True))
        if not query_tokens:
            return 0.0
        coverage = len(query_tokens & content_tokens) / len(query_tokens)
        phrase_bonus = 0.15 if query.strip().lower() in chunk.content.lower() else 0.0
        heading_bonus = 0.08 if chunk.heading and query_tokens.intersection(tokenize(chunk.heading)) else 0.0
        return min(1.0, coverage + phrase_bonus + heading_bonus)


def _rank_map(scores: dict[str, float]) -> dict[str, int]:
    ordered = sorted(scores, key=scores.get, reverse=True)
    return {chunk_id: rank for rank, chunk_id in enumerate(ordered, start=1)}
