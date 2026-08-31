from __future__ import annotations

import math
from typing import Protocol

from retrieval.tokenizer import tokenize


class Reranker(Protocol):
    name: str

    def score(self, query: str, documents: list[str]) -> list[float]: ...


class LexicalReranker:
    """Dependency-free fallback used in tests and offline demos."""

    name = "lexical"

    def score(self, query: str, documents: list[str]) -> list[float]:
        query_tokens = set(tokenize(query, remove_stopwords=True))
        if not query_tokens:
            return [0.0] * len(documents)
        scores: list[float] = []
        normalized_query = query.strip().lower()
        for document in documents:
            content_tokens = set(tokenize(document, remove_stopwords=True))
            coverage = len(query_tokens & content_tokens) / len(query_tokens)
            phrase_bonus = 0.15 if normalized_query and normalized_query in document.lower() else 0.0
            scores.append(min(1.0, coverage + phrase_bonus))
        return scores


class CrossEncoderReranker:
    """Optional second-stage semantic reranker for the GPU deployment.

    The model is loaded only when RERANKER_ENABLED=true. Raw logits are mapped
    with a sigmoid so the hybrid retriever can combine them with normalized
    dense/sparse scores without depending on a model-specific score range.
    """

    def __init__(self, model_name: str, device: str = "cpu"):
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:  # pragma: no cover - optional server dependency
            raise RuntimeError(
                "Semantic reranking requires the 'server' dependency group: pip install -e '.[server]'"
            ) from exc
        self.name = model_name
        self._model = CrossEncoder(model_name, device=device, trust_remote_code=True)

    def score(self, query: str, documents: list[str]) -> list[float]:
        if not documents:
            return []
        raw_scores = self._model.predict(
            [(query, document) for document in documents],
            show_progress_bar=False,
        )
        return [_sigmoid(float(value)) for value in raw_scores]


def _sigmoid(value: float) -> float:
    if value >= 0:
        factor = math.exp(-value)
        return 1.0 / (1.0 + factor)
    factor = math.exp(value)
    return factor / (1.0 + factor)
