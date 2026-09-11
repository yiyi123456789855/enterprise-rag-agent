import unittest
from pathlib import Path
from tempfile import TemporaryDirectory

from evaluation.run_eval import _load_thresholds, _threshold_failures


class EvaluationGateTests(unittest.TestCase):
    def test_threshold_failures_report_minimum_and_maximum_regressions(self):
        report = {"recall_at_5": 0.8, "latency_p95_ms": 700.0}
        failures = _threshold_failures(
            report,
            {
                "minimums": {"recall_at_5": 0.9},
                "maximums": {"latency_p95_ms": 500.0},
            },
        )

        self.assertEqual(
            [(failure["metric"], failure["operator"]) for failure in failures],
            [("recall_at_5", ">="), ("latency_p95_ms", "<=")],
        )

    def test_threshold_configuration_rejects_non_numeric_values(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "thresholds.json"
            path.write_text('{"minimums": {"recall_at_5": "high"}}', encoding="utf-8")

            with self.assertRaisesRegex(ValueError, "numeric"):
                _load_thresholds(path)


if __name__ == "__main__":
    unittest.main()
