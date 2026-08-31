import unittest

from evaluation.run_server_acceptance import _missing_expectations


class EvaluationExpectationTests(unittest.TestCase):
    def test_semantic_alternative_pattern_accepts_equivalent_prohibition(self):
        example = {
            "expected_terms": ["脱敏"],
            "expected_patterns": [r"(?:不得|不能|不允许)直接"],
        }

        self.assertEqual(
            _missing_expectations("客户日志不能直接上传，必须先脱敏。", example),
            [],
        )

    def test_missing_literal_term_is_reported(self):
        example = {"expected_terms": ["两个工作日", "事故编号"]}

        self.assertEqual(
            _missing_expectations("需要在两个工作日内补录。", example),
            ["事故编号"],
        )


if __name__ == "__main__":
    unittest.main()
