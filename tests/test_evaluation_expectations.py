import ast
import inspect
import textwrap
import unittest

import evaluation.run_server_acceptance as server_acceptance
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

    def test_golden_dataset_uses_primary_authorized_client(self):
        tree = ast.parse(textwrap.dedent(inspect.getsource(server_acceptance.main)))
        examples_loop = next(
            node
            for node in ast.walk(tree)
            if isinstance(node, ast.For)
            and isinstance(node.iter, ast.Call)
            and isinstance(node.iter.func, ast.Name)
            and node.iter.func.id == "enumerate"
            and isinstance(node.iter.args[0], ast.Name)
            and node.iter.args[0].id == "examples"
        )
        ask_call = next(
            node
            for node in ast.walk(examples_loop)
            if isinstance(node, ast.Call)
            and isinstance(node.func, ast.Name)
            and node.func.id == "ask"
        )

        self.assertIsInstance(ask_call.args[0], ast.Name)
        self.assertEqual(ask_call.args[0].id, "client")


if __name__ == "__main__":
    unittest.main()
