import unittest

from app.types import StoredChunk
from retrieval.embeddings import HashingEmbedder
from retrieval.vector_store import QdrantVectorIndex


def make_chunk(chunk_id: str, content: str, visibility: str, departments: list[str]) -> StoredChunk:
    return StoredChunk(
        id=chunk_id,
        document_id="00000000-0000-0000-0000-000000000010",
        tenant_id="acme",
        chunk_index=0,
        content=content,
        heading="测试",
        page_number=1,
        visibility=visibility,
        departments=departments,
        token_count=10,
        metadata={},
        filename="test.md",
    )


class QdrantVectorIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = QdrantVectorIndex(
            url=":memory:",
            api_key="",
            collection_name="test_collection",
            embedder=HashingEmbedder(dimension=64),
        )
        self.public_id = "00000000-0000-0000-0000-000000000001"
        self.secret_id = "00000000-0000-0000-0000-000000000002"
        self.index.upsert(
            [
                make_chunk(self.public_id, "员工每年享有十天带薪年假", "public", []),
                make_chunk(self.secret_id, "研发部门年度调薪规则", "department", ["研发部"]),
            ]
        )

    def test_public_user_cannot_search_department_vector(self):
        result = self.index.search(
            "研发部门调薪规则",
            tenant_id="acme",
            departments=[],
            limit=10,
        )
        self.assertIn(self.public_id, result)
        self.assertNotIn(self.secret_id, result)

    def test_authorized_department_can_search_department_vector(self):
        result = self.index.search(
            "研发部门调薪规则",
            tenant_id="acme",
            departments=["研发部"],
            limit=10,
        )
        self.assertIn(self.secret_id, result)
        self.assertTrue(self.index.health())


if __name__ == "__main__":
    unittest.main()

