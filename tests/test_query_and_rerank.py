import unittest

from agent.query import ContextualQueryRewriter
from retrieval.rerankers import LexicalReranker
from retrieval.tokenizer import tokenize


class QueryAndRerankTests(unittest.TestCase):
    def test_chinese_tokenizer_adds_bigrams(self):
        tokens = tokenize("员工年假")
        self.assertIn("员工", tokens)
        self.assertIn("年假", tokens)

    def test_standalone_question_is_not_rewritten(self):
        rewriter = ContextualQueryRewriter()
        question = "成都住宿标准是多少？"
        self.assertEqual(rewriter.rewrite(question, ["年假有几天？"]), question)

    def test_follow_up_question_includes_last_turn(self):
        rewritten = ContextualQueryRewriter().rewrite(
            "这种情况需要谁审批？",
            ["连续休假七天要提前多久？"],
        )
        self.assertIn("连续休假七天", rewritten)

    def test_short_implicit_follow_up_includes_last_turn(self):
        rewritten = ContextualQueryRewriter().rewrite(
            "需要提前多久提交？",
            ["连续休假超过七天由谁审批？"],
        )

        self.assertIn("上下文问题", rewritten)
        self.assertIn("连续休假超过七天", rewritten)
        self.assertIn("当前追问", rewritten)

    def test_lexical_reranker_prefers_matching_document(self):
        scores = LexicalReranker().score(
            "成都住宿标准",
            ["成都出差住宿标准为每晚550元", "员工应按时完成安全培训"],
        )
        self.assertGreater(scores[0], scores[1])


if __name__ == "__main__":
    unittest.main()
