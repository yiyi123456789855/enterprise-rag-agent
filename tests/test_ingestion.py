import tempfile
import unittest
from pathlib import Path

from app.database import Repository
from ingestion.service import IngestionService


class IngestionTests(unittest.TestCase):
    def setUp(self):
        self.temp_directory = tempfile.TemporaryDirectory()
        self.database_path = Path(self.temp_directory.name) / "test.db"
        self.repository = Repository(self.database_path)
        self.repository.initialize()
        self.service = IngestionService(self.repository, chunk_size=80, chunk_overlap=10)

    def tearDown(self):
        self.temp_directory.cleanup()

    def test_markdown_ingestion_and_duplicate_detection(self):
        content = "# 报销制度\n\n差旅报销应在返程后五个工作日内提交。".encode("utf-8")
        task = self.service.enqueue(
            filename="policy.md",
            content=content,
            tenant_id="acme",
        )
        count = self.service.process(task.job["id"], task.document["id"], "policy.md", content)

        self.assertEqual(count, 1)
        self.assertEqual(self.repository.get_document(task.document["id"])["status"], "ready")
        duplicate = self.service.enqueue(filename="policy.md", content=content, tenant_id="acme")
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(duplicate.document["id"], task.document["id"])

    def test_department_document_requires_department(self):
        with self.assertRaises(ValueError):
            self.service.enqueue(
                filename="secret.txt",
                content="调薪规则".encode("utf-8"),
                tenant_id="acme",
                visibility="department",
                departments=[],
            )


if __name__ == "__main__":
    unittest.main()

