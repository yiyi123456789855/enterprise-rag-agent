from __future__ import annotations

from typing import Protocol

from app.types import StoredChunk
from retrieval.embeddings import Embedder


class VectorIndex(Protocol):
    def upsert(self, chunks: list[StoredChunk]) -> None: ...

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        departments: list[str],
        limit: int,
    ) -> dict[str, float]: ...

    def delete_document(self, document_id: str) -> None: ...

    def health(self) -> bool: ...


class QdrantVectorIndex:
    def __init__(
        self,
        *,
        url: str,
        api_key: str,
        collection_name: str,
        embedder: Embedder,
    ):
        try:
            from qdrant_client import QdrantClient
        except ImportError as exc:  # pragma: no cover - optional server dependency
            raise RuntimeError(
                "Qdrant requires the 'server' dependency group: pip install -e '.[server]'"
            ) from exc
        self._models = __import__("qdrant_client.models", fromlist=["models"])
        if url in {":memory:", "memory"}:
            self.client = QdrantClient(location=":memory:")
        elif url.startswith("local:"):
            local_path = url.removeprefix("local:").strip()
            if not local_path:
                raise ValueError("QDRANT_URL local mode requires a path after 'local:'")
            self.client = QdrantClient(path=local_path)
        else:
            self.client = QdrantClient(url=url, api_key=api_key or None, timeout=30)
        self.collection_name = collection_name
        self.embedder = embedder
        self._ensure_collection()

    def _ensure_collection(self) -> None:
        models = self._models
        if not self.client.collection_exists(self.collection_name):
            self.client.create_collection(
                collection_name=self.collection_name,
                vectors_config=models.VectorParams(
                    size=self.embedder.dimension,
                    distance=models.Distance.COSINE,
                ),
            )

    def upsert(self, chunks: list[StoredChunk]) -> None:
        if not chunks:
            return
        models = self._models
        points = [
            models.PointStruct(
                id=chunk.id,
                vector=self.embedder.embed(chunk.content),
                payload={
                    "chunk_id": chunk.id,
                    "document_id": chunk.document_id,
                    "tenant_id": chunk.tenant_id,
                    "visibility": chunk.visibility,
                    "departments": chunk.departments,
                },
            )
            for chunk in chunks
        ]
        self.client.upsert(collection_name=self.collection_name, points=points, wait=True)

    def search(
        self,
        query: str,
        *,
        tenant_id: str,
        departments: list[str],
        limit: int,
    ) -> dict[str, float]:
        models = self._models
        must = [models.FieldCondition(key="tenant_id", match=models.MatchValue(value=tenant_id))]
        if departments:
            access_filter = models.Filter(
                must=must,
                should=[
                    models.FieldCondition(key="visibility", match=models.MatchValue(value="public")),
                    models.FieldCondition(key="departments", match=models.MatchAny(any=departments)),
                ],
            )
        else:
            access_filter = models.Filter(
                must=must
                + [models.FieldCondition(key="visibility", match=models.MatchValue(value="public"))]
            )
        response = self.client.query_points(
            collection_name=self.collection_name,
            query=self.embedder.embed(query),
            query_filter=access_filter,
            limit=limit,
            with_payload=True,
        )
        return {
            str(point.payload.get("chunk_id", point.id)): max(0.0, float(point.score))
            for point in response.points
        }

    def delete_document(self, document_id: str) -> None:
        models = self._models
        self.client.delete(
            collection_name=self.collection_name,
            points_selector=models.FilterSelector(
                filter=models.Filter(
                    must=[
                        models.FieldCondition(
                            key="document_id",
                            match=models.MatchValue(value=document_id),
                        )
                    ]
                )
            ),
            wait=True,
        )

    def health(self) -> bool:
        try:
            self.client.get_collection(self.collection_name)
            return True
        except Exception:
            return False
