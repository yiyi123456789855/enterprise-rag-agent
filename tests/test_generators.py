import json
import unittest
from unittest.mock import patch

from agent.generators import OpenAICompatibleGenerator
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


class OpenAICompatibleGeneratorTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
