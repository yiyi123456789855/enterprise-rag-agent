from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_report(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        report = json.load(handle)
    required = {"passed", "failed", "total", "query_latency_ms"}
    missing = sorted(required.difference(report))
    if missing:
        raise ValueError(f"{path} is missing fields: {', '.join(missing)}")
    return report


def _latency(report: dict[str, Any], key: str) -> float:
    return float(report["query_latency_ms"][key])


def _pass_rate(report: dict[str, Any]) -> float:
    total = int(report["total"])
    return int(report["passed"]) / total if total else 0.0


def build_markdown(
    baseline: dict[str, Any],
    candidate: dict[str, Any],
    *,
    baseline_label: str,
    candidate_label: str,
) -> str:
    rows = [
        ("验收通过", f'{baseline["passed"]}/{baseline["total"]}', f'{candidate["passed"]}/{candidate["total"]}'),
        ("验收通过率", f"{_pass_rate(baseline):.1%}", f"{_pass_rate(candidate):.1%}"),
        ("平均延迟", f'{_latency(baseline, "average"):.2f} ms', f'{_latency(candidate, "average"):.2f} ms'),
        ("P50 延迟", f'{_latency(baseline, "p50"):.2f} ms', f'{_latency(candidate, "p50"):.2f} ms'),
        ("P95 延迟", f'{_latency(baseline, "p95"):.2f} ms', f'{_latency(candidate, "p95"):.2f} ms'),
    ]
    factors = {
        key: _latency(candidate, key) / _latency(baseline, key)
        for key in ("average", "p50", "p95")
        if _latency(baseline, key) > 0
    }
    factor_text = "，".join(
        f"{label} {factors[key]:.2f}x"
        for key, label in (("average", "平均"), ("p50", "P50"), ("p95", "P95"))
        if key in factors
    )
    table = "\n".join(
        [
            f"| 指标 | {baseline_label} | {candidate_label} |",
            "|---|---:|---:|",
            *(f"| {name} | {left} | {right} |" for name, left, right in rows),
        ]
    )
    return f"""# 服务器验收 A/B 对比

{table}

候选生成器相对基线的延迟倍数：{factor_text}。

## 结论

- 两个版本均通过同一套服务器验收，可将差异主要归因于答案生成方式。
- `{candidate_label}` 提升了答案组织能力，但需要支付模型推理延迟；证据门控、ACL 和引用校验仍在生成前后执行。
- 生产选择应根据业务对可读性、吞吐和延迟的要求决定；高并发场景可保留抽取式降级通道。

## 指标边界

该结果来自单份虚构企业手册与固定验收流程，用于回归和方案对比，不代表真实企业生产数据上的泛化能力。对外表述时应同时说明样本范围、硬件环境和并发条件。
"""


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compare two server acceptance JSON reports.")
    parser.add_argument("--baseline", required=True, type=Path)
    parser.add_argument("--candidate", required=True, type=Path)
    parser.add_argument("--baseline-label", default="Extractive")
    parser.add_argument("--candidate-label", default="Qwen2.5-3B + vLLM")
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    markdown = build_markdown(
        load_report(args.baseline),
        load_report(args.candidate),
        baseline_label=args.baseline_label,
        candidate_label=args.candidate_label,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(markdown, encoding="utf-8")
    print(f"A/B report written to: {args.output}")


if __name__ == "__main__":
    main()
