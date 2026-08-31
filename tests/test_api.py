import os
import tempfile
import unittest
from pathlib import Path


class APITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp_directory = tempfile.TemporaryDirectory()
        data_dir = Path(cls.temp_directory.name)
        os.environ["DATA_DIR"] = str(data_dir)
        os.environ["DATABASE_PATH"] = str(data_dir / "api.db")

        from fastapi.testclient import TestClient
        from app.main import app

        cls.client_context = TestClient(app)
        cls.client = cls.client_context.__enter__()

    @classmethod
    def tearDownClass(cls):
        cls.client_context.__exit__(None, None, None)
        from api.dependencies import (
            get_embedder,
            get_ingestion_service,
            get_rag_service,
            get_repository,
            get_reranker,
            get_settings,
            get_vector_index,
        )

        get_rag_service.cache_clear()
        get_ingestion_service.cache_clear()
        get_repository.cache_clear()
        get_vector_index.cache_clear()
        get_embedder.cache_clear()
        get_reranker.cache_clear()
        get_settings.cache_clear()
        os.environ.pop("DATA_DIR", None)
        os.environ.pop("DATABASE_PATH", None)
        cls.temp_directory.cleanup()

    def test_upload_poll_and_chat(self):
        root = self.client.get("/")
        self.assertEqual(root.status_code, 200)
        self.assertIn("企业知识库 RAG Agent", root.text)

        health = self.client.get("/health")
        self.assertEqual(health.status_code, 200)
        self.assertEqual(health.json()["status"], "ok")

        upload = self.client.post(
            "/api/v1/documents",
            data={"tenant_id": "api-company", "visibility": "public", "departments": "[]"},
            files={
                "file": (
                    "travel-policy.md",
                    "# 差旅制度\n\n成都地区出差的住宿标准为每晚五百元。".encode("utf-8"),
                    "text/markdown",
                )
            },
        )
        self.assertEqual(upload.status_code, 202, upload.text)
        job = self.client.get(f"/api/v1/jobs/{upload.json()['job_id']}")
        self.assertEqual(job.status_code, 200)
        self.assertEqual(job.json()["status"], "completed")

        response = self.client.post(
            "/api/v1/chat",
            json={
                "question": "成都出差住宿标准是多少？",
                "tenant_id": "api-company",
                "user_id": "tester",
                "departments": [],
                "top_k": 3,
            },
        )
        self.assertEqual(response.status_code, 200, response.text)
        body = response.json()
        self.assertEqual(body["status"], "answered")
        self.assertEqual(body["citations"][0]["filename"], "travel-policy.md")
        self.assertTrue(body["conversation_id"])
        self.assertTrue(body["session_id"])
        self.assertGreaterEqual(body["debug"]["total_ms"], 0)

        conversations = self.client.get(
            "/api/v1/conversations",
            params={"tenant_id": "api-company", "user_id": "tester"},
        )
        self.assertEqual(conversations.status_code, 200)
        self.assertEqual(conversations.json()[0]["id"], body["conversation_id"])

        feedback = self.client.post(
            "/api/v1/feedback",
            json={
                "conversation_id": body["conversation_id"],
                "tenant_id": "api-company",
                "rating": 1,
                "comment": "引用准确",
            },
        )
        self.assertEqual(feedback.status_code, 200, feedback.text)

        metrics = self.client.get("/api/v1/metrics", params={"tenant_id": "api-company"})
        self.assertEqual(metrics.status_code, 200)
        self.assertEqual(metrics.json()["metrics"]["questions"], 1)
        self.assertEqual(metrics.json()["metrics"]["positive_feedback"], 1)


if __name__ == "__main__":
    unittest.main()
