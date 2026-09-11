import json
import unittest
from unittest.mock import patch
from urllib import error

from agent.generators import OpenAICompatibleGenerator, _extract_segments
from app.types import SearchHit, StoredChunk


class _FakeResponse:
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, traceback):
        return False

    def read(self):
        return json.dumps(
            {"choices": [{"message": {"content": "最多结转五天，并于次年3月31日前使用。[1]"}}]},
            ensure_ascii=False,
        ).encode("utf-8")


class _FakeResponseWithoutCitation(_FakeResponse):
    def read(self):
        return json.dumps(
            {"choices": [{"message": {"content": "可以先采购，之后再补手续。"}}]},
            ensure_ascii=False,
        ).encode("utf-8")


class _FakeModelsResponse(_FakeResponse):
    def read(self):
        return json.dumps({"object": "list", "data": [{"id": "test-model"}]}).encode()


class OpenAICompatibleGeneratorTests(unittest.TestCase):
    def test_markdown_table_rows_keep_column_meaning(self):
        segments = _extract_segments(
            "| 城市类别 | 普通员工 | 部门负责人及以上 |\n"
            "|---|---:|---:|\n"
            "| 广州、杭州、成都、南京 | 550元/晚 | 700元/晚 |"
        )

        self.assertEqual(len(segments), 1)
        self.assertIn("城市类别：广州、杭州、成都、南京", segments[0])
        self.assertIn("普通员工：550元/晚", segments[0])

    @patch("agent.generators.request.urlopen", return_value=_FakeResponse())
    def test_prompt_preserves_policy_anchors_and_uses_deterministic_generation(self, urlopen):
        chunk = StoredChunk(
            id="chunk-1",
            document_id="document-1",
            tenant_id="demo-company",
            chunk_index=0,
            content="年假最多结转五天，并于次年3月31日前使用。",
            heading="年假结转",
            page_number=2,
            visibility="public",
            departments=[],
            token_count=20,
            metadata={},
            filename="handbook.md",
        )
        hit = SearchHit(chunk=chunk, score=0.9, dense_score=0.9, sparse_score=0.8, rerank_score=0.9)
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8001/v1",
            api_key="test-key",
            model="Qwen/Qwen2.5-3B-Instruct",
        )

        answer = generator.generate("剩余年假如何结转？", [hit])

        self.assertIn("五天", answer)
        self.assertIn("3月31日", answer)
        http_request = urlopen.call_args.args[0]
        payload = json.loads(http_request.data.decode("utf-8"))
        self.assertEqual(payload["temperature"], 0)
        self.assertEqual(payload["max_tokens"], 512)
        prompt = payload["messages"][0]["content"]
        self.assertIn("原样保留", prompt)
        self.assertIn("禁止性短语", prompt)
        self.assertIn("规范动作词", prompt)
        self.assertIn("不要输出文件名", prompt)
        self.assertIn("年假最多结转五天", payload["messages"][1]["content"])

    @patch("agent.generators.request.urlopen", return_value=_FakeResponseWithoutCitation())
    def test_missing_llm_citation_falls_back_to_grounded_extractive_answer(self, _urlopen):
        chunk = StoredChunk(
            id="chunk-p0",
            document_id="document-p0",
            tenant_id="demo-company",
            chunk_index=0,
            content="P0事故可以先执行紧急采购。事后两个工作日内补录，并关联事故编号。",
            heading="P0紧急采购",
            page_number=None,
            visibility="public",
            departments=[],
            token_count=24,
            metadata={},
            filename="emergency.md",
        )
        hit = SearchHit(chunk=chunk, score=0.9, dense_score=0.9, sparse_score=0.9, rerank_score=0.9)
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8001/v1",
            api_key="test-key",
            model="Qwen/Qwen2.5-3B-Instruct",
        )

        answer = generator.generate("P0事故紧急采购需要什么手续？", [hit])

        self.assertIn("两个工作日", answer)
        self.assertIn("事故编号", answer)
        self.assertIn("[1]", answer)

    @patch(
        "agent.generators.request.urlopen",
        side_effect=error.URLError("connection refused"),
    )
    def test_llm_transport_failure_falls_back_without_raising_500(self, urlopen):
        hit = self._policy_hit()
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8001/v1",
            api_key="test-key",
            model="Qwen/Qwen2.5-3B-Instruct",
        )

        answer = generator.generate("连续休假七天要提前多久申请？", [hit])

        self.assertIn("十个工作日", answer)
        self.assertIn("[1]", answer)
        self.assertEqual(urlopen.call_count, 2)

    @patch(
        "agent.generators.request.urlopen",
        side_effect=error.URLError("connection refused"),
    )
    def test_circuit_breaker_skips_repeated_remote_calls(self, urlopen):
        hit = self._policy_hit()
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8001/v1",
            api_key="test-key",
            model="Qwen/Qwen2.5-3B-Instruct",
            failure_threshold=1,
            circuit_reset_seconds=60,
            retry_backoff_seconds=0,
        )

        first = generator.generate("连续休假七天要提前多久申请？", [hit])
        second = generator.generate("连续休假七天要提前多久申请？", [hit])

        self.assertIn("[1]", first)
        self.assertIn("[1]", second)
        self.assertEqual(urlopen.call_count, 2)

    @patch("agent.generators.request.urlopen", return_value=_FakeModelsResponse())
    def test_llm_health_probe_validates_models_endpoint(self, urlopen):
        generator = OpenAICompatibleGenerator(
            base_url="http://127.0.0.1:8001/v1",
            api_key="test-key",
            model="Qwen/Qwen2.5-3B-Instruct",
        )

        self.assertTrue(generator.health())
        http_request = urlopen.call_args.args[0]
        self.assertEqual(http_request.full_url, "http://127.0.0.1:8001/v1/models")
        self.assertEqual(http_request.headers["Authorization"], "Bearer test-key")

    @staticmethod
    def _policy_hit() -> SearchHit:
        chunk = StoredChunk(
            id="chunk-leave",
            document_id="document-leave",
            tenant_id="demo-company",
            chunk_index=0,
            content="连续休假七天需要提前十个工作日申请。",
            heading="休假审批",
            page_number=1,
            visibility="public",
            departments=[],
            token_count=18,
            metadata={},
            filename="leave.md",
        )
        return SearchHit(
            chunk=chunk,
            score=0.9,
            dense_score=0.9,
            sparse_score=0.9,
            rerank_score=0.9,
        )


if __name__ == "__main__":
    unittest.main()
