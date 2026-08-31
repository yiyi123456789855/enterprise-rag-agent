from evaluation.compare_acceptance_reports import build_markdown


def test_build_markdown_reports_pass_rate_and_latency_factor() -> None:
    baseline = {
        "passed": 31,
        "failed": 0,
        "total": 31,
        "query_latency_ms": {"average": 200.22, "p50": 181.03, "p95": 281.94},
    }
    candidate = {
        "passed": 31,
        "failed": 0,
        "total": 31,
        "query_latency_ms": {"average": 613.67, "p50": 599.84, "p95": 1202.50},
    }

    markdown = build_markdown(
        baseline,
        candidate,
        baseline_label="Extractive",
        candidate_label="Qwen",
    )

    assert "31/31" in markdown
    assert "100.0%" in markdown
    assert "613.67 ms" in markdown
    assert "3.06x" in markdown
    assert "4.27x" in markdown
