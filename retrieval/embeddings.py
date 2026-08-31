from __future__ import annotations

import hashlib
import math
from typing import Protocol

from retrieval.tokenizer import tokenize


class Embedder(Protocol):
    dimension: int

    def embed(self, text: str) -> list[float]: ...


class HashingEmbedder:
    """Deterministic, dependency-free embedding used by the runnable MVP.

    It is not intended to replace BGE-M3 in production. Its interface exists so
    the production embedder can be swapped in without changing retrieval flow.
    """

    def __init__(self, dimension: int = 384):
        self.dimension = dimension

    def embed(self, text: str) -> list[float]:
        vector = [0.0] * self.dimension
        tokens = tokenize(text)
        for token in tokens:
            digest = hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest()
            value = int.from_bytes(digest, "little")
            index = value % self.dimension
            sign = -1.0 if value & (1 << 63) else 1.0
            vector[index] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector


def cosine_similarity(left: list[float], right: list[float]) -> float:
    return sum(a * b for a, b in zip(left, right))


class SentenceTransformerEmbedder:
    """Production dense embedder loaded lazily on the server.

    BAAI/bge-m3 is the default model. The model cache is controlled through
    Hugging Face's HF_HOME environment variable in the server compose file.
    """

    def __init__(self, model_name: str = "BAAI/bge-m3", device: str = "cpu"):
        try:
            from sentence_transformers import SentenceTransformer
        except ImportError as exc:  # pragma: no cover - optional server dependency
            raise RuntimeError(
                "Server embeddings require the 'server' dependency group: pip install -e '.[server]'"
            ) from exc
        self.model_name = model_name
        self.device = device
        self._model = SentenceTransformer(model_name, device=device)
        dimension_getter = getattr(self._model, "get_embedding_dimension", None)
        if dimension_getter is None:  # sentence-transformers < 5.0
            dimension_getter = self._model.get_sentence_embedding_dimension
        self.dimension = int(dimension_getter())

    def embed(self, text: str) -> list[float]:
        vector = self._model.encode(
            [text],
            normalize_embeddings=True,
            show_progress_bar=False,
        )[0]
        return vector.tolist()
