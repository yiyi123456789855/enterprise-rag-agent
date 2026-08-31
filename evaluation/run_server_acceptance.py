"""End-to-end acceptance test for the deployed RAG HTTP service.

The script intentionally uses only Python's standard library. It exercises the
real configured embedding model, vector store and reranker through the API,
then cleans up the temporary ACL document it creates.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import statistics
import sys
import time
import uuid
from pathlib import Path
from urllib import error, parse, request


class ApiClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key

    def json(
        self,
        method: str,
        path: str,
        payload: dict | None = None,
        *,
        api_key: str | None = None,
        expected_status: int = 200,
    ) -> dict | list | None:
        body = None
        headers = {"X-API-Key": self.api_key if api_key is None else api_key}
        if payload is not None:
            body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = request.Request(
            f"{self.base_url}{path}", data=body, headers=headers, method=method
        )
        return self._open(req, expected_status)

    def health(self) -> dict:
        req = request.Request(f"{self.base_url}/health", method="GET")
        result = self._open(req, 200)
        assert isinstance(result, dict)
        return result

    def upload_markdown(
        self,
        *,
        filename: str,
        content: str,
        tenant_id: str,
        visibility: str,
        departments: list[str],
    ) -> dict:
        boundary = f"----rag-acceptance-{uuid.uuid4().hex}"
        chunks: list[bytes] = []

        def field(name: str, value: str) -> None:
            chunks.extend(
                [
                    f"--{boundary}\r\n".encode(),
                    f'Content-Disposition: form-data; name="{name}"\r\n\r\n'.encode(),
                    value.encode("utf-8"),
                    b"\r\n",
                ]
            )

        field("tenant_id", tenant_id)
        field("visibility", visibility)
        field("departments", json.dumps(departments, ensure_ascii=False))
        chunks.extend(
            [
                f"--{boundary}\r\n".encode(),
                (
                    f'Content-Disposition: form-data; name="file"; '
                    f'filename="{filename}"\r\n'
                ).encode(),
                b"Content-Type: text/markdown; charset=utf-8\r\n\r\n",
                content.encode("utf-8"),
                b"\r\n",
                f"--{boundary}--\r\n".encode(),
            ]
        )
        req = request.Request(
            f"{self.base_url}/api/v1/documents",
            data=b"".join(chunks),
            headers={
                "X-API-Key": self.api_key,
                "Content-Type": f"multipart/form-data; boundary={boundary}",
            },
            method="POST",
        )
        result = self._open(req, 202)
        assert isinstance(result, dict)
        return result

    @staticmethod
    def _open(req: request.Request, expected_status: int):
        try:
            with request.urlopen(req, timeout=90) as response:
                status = response.status
                raw = response.read()
        except error.HTTPError as exc:
            status = exc.code
            raw = exc.read()
        except error.URLError as exc:
            raise RuntimeError(f"无法连接服务：{exc}") from exc
        if status != expected_status:
            detail = raw.decode("utf-8", errors="replace")
            raise RuntimeError(f"HTTP {status}，预期 {expected_status}：{detail}")
        if not raw or expected_status == 204:
            return None
        return json.loads(raw.decode("utf-8"))


class AcceptanceReport:
    def __init__(self):
        self.checks: list[dict] = []

    def check(self, name: str, passed: bool, detail: str = "") -> None:
        self.checks.append({"name": name, "passed": bool(passed), "detail": detail})
        print(f"[{'PASS' if passed else 'FAIL'}] {name}{': ' + detail if detail else ''}")

    def summary(self) -> dict:
        passed = sum(item["passed"] for item in self.checks)
        return {
            "passed": passed,
            "failed": len(self.checks) - passed,
            "total": len(self.checks),
            "checks": self.checks,
        }


def ask(
    client: ApiClient,
    question: str,
    *,
    tenant: str,
    departments: list[str],
    session_id: str,
) -> dict:
    result = client.json(
        "POST",
        "/api/v1/chat",
        {
            "question": question,
            "tenant_id": tenant,
            "user_id": "acceptance-runner",
            "departments": departments,
            "top_k": 5,
            "session_id": session_id,
        },
    )
    assert isinstance(result, dict)
    return result


def wait_for_job(client: ApiClient, job_id: str, timeout_seconds: int = 180) -> dict:
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = client.json("GET", f"/api/v1/jobs/{parse.quote(job_id)}")
        assert isinstance(result, dict)
        if result["status"] == "completed":
            return result
        if result["status"] == "failed":
            raise RuntimeError(f"入库任务失败：{result.get('error')}")
        time.sleep(1)
    raise RuntimeError("等待文档入库超时")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--api-key", default=os.getenv("APP_API_KEY", ""))
    parser.add_argument("--tenant", default="demo-company")
    parser.add_argument("--dataset", default="evaluation/golden_portfolio.jsonl")
    parser.add_argument("--output", default="evaluation/server_acceptance_report.json")
    args = parser.parse_args()
    if not args.api_key:
        print("缺少 API Key：请先 source .env.direct 或传入 --api-key", file=sys.stderr)
        return 2

    client = ApiClient(args.base_url, args.api_key)
    report = AcceptanceReport()
    latencies: list[float] = []
    first_conversation_id = ""

    health = client.health()
    details = health.get("details", {})
    report.check("健康检查", health.get("status") == "ok", json.dumps(details, ensure_ascii=False))
    report.check("Qdrant 后端", details.get("retrieval_backend") == "qdrant")
    report.check("BGE-M3 Embedding", "bge-m3" in details.get("embedding_model", "").lower())
    report.check("语义重排已启用", details.get("reranker") != "lexical", str(details.get("reranker")))

    try:
        client.json(
            "GET",
            f"/api/v1/metrics?tenant_id={parse.quote(args.tenant)}",
            api_key="invalid-acceptance-key",
            expected_status=401,
        )
        report.check("无效 API Key 被拒绝", True)
    except Exception as exc:
        report.check("无效 API Key 被拒绝", False, str(exc))

    examples = [
        json.loads(line)
        for line in Path(args.dataset).read_text("utf-8").splitlines()
        if line.strip()
    ]
    for index, example in enumerate(examples, start=1):
        result = ask(
            client,
            example["question"],
            tenant=args.tenant,
            departments=example.get("departments", ["研发部"]),
            session_id=f"acceptance-golden-{uuid.uuid4().hex}",
        )
        expected_status = "answered" if example["should_answer"] else "insufficient_evidence"
        answer = result.get("answer", "")
        missing = _missing_expectations(answer, example)
        passed = result.get("status") == expected_status and not missing
        if result.get("status") == "answered":
            passed = passed and bool(result.get("citations"))
        debug = result.get("debug") or {}
        latencies.append(float(debug.get("total_ms", 0.0)))
        if not first_conversation_id and result.get("status") == "answered":
            first_conversation_id = result["conversation_id"]
        report.check(
            f"黄金集 {index:02d}：{example['question']}",
            passed,
            f"status={result.get('status')} missing={missing}",
        )

    follow_session = f"acceptance-follow-{uuid.uuid4().hex}"
    first = ask(
        client,
        "连续休假超过七天由谁审批？",
        tenant=args.tenant,
        departments=["研发部"],
        session_id=follow_session,
    )
    second = ask(
        client,
        "需要提前多久提交？",
        tenant=args.tenant,
        departments=["研发部"],
        session_id=follow_session,
    )
    report.check(
        "多轮追问与指代消解",
        first.get("status") == "answered"
        and second.get("status") == "answered"
        and "十个工作日" in second.get("answer", "")
        and "上下文问题" in (second.get("debug") or {}).get("retrieval_query", ""),
        second.get("answer", "").replace("\n", " ")[:180],
    )

    if first_conversation_id:
        before = client.json("GET", f"/api/v1/metrics?tenant_id={parse.quote(args.tenant)}")
        client.json(
            "POST",
            "/api/v1/feedback",
            {
                "conversation_id": first_conversation_id,
                "tenant_id": args.tenant,
                "rating": 1,
                "comment": "automated acceptance",
            },
        )
        after = client.json("GET", f"/api/v1/metrics?tenant_id={parse.quote(args.tenant)}")
        before_value = (before or {}).get("metrics", {}).get("positive_feedback", 0)
        after_value = (after or {}).get("metrics", {}).get("positive_feedback", 0)
        report.check("反馈闭环写入指标", after_value == before_value + 1)

    private_document_id = ""
    private_text = (
        "# 研发部私有模型发布规则\n\n"
        "项目代号星河7429的模型首次灰度发布比例为17%。观察窗口为30分钟；"
        "若错误率超过1.5%，应立即回滚并通知研发负责人。\n"
    )
    private_filename = "acceptance-rd-private-policy.md"
    try:
        upload = client.upload_markdown(
            filename=private_filename,
            content=private_text,
            tenant_id=args.tenant,
            visibility="department",
            departments=["研发部"],
        )
        private_document_id = upload["document_id"]
        if not upload.get("duplicate"):
            wait_for_job(client, upload["job_id"])
        report.check("部门私有文档上传入库", True)

        duplicate = client.upload_markdown(
            filename=private_filename,
            content=private_text,
            tenant_id=args.tenant,
            visibility="department",
            departments=["研发部"],
        )
        report.check("SHA-256 重复文档去重", bool(duplicate.get("duplicate")))

        rd_result = ask(
            client,
            "星河7429项目首次灰度发布比例是多少？",
            tenant=args.tenant,
            departments=["研发部"],
            session_id=f"acceptance-rd-{uuid.uuid4().hex}",
        )
        report.check(
            "研发部可以检索私有文档",
            rd_result.get("status") == "answered" and "17%" in rd_result.get("answer", ""),
        )

        sales_result = ask(
            client,
            "星河7429项目首次灰度发布比例是多少？",
            tenant=args.tenant,
            departments=["市场部"],
            session_id=f"acceptance-sales-{uuid.uuid4().hex}",
        )
        report.check("市场部无法检索研发私有文档", sales_result.get("status") == "insufficient_evidence")

        other_tenant = ask(
            client,
            "星河7429项目首次灰度发布比例是多少？",
            tenant="acceptance-other-company",
            departments=["研发部"],
            session_id=f"acceptance-tenant-{uuid.uuid4().hex}",
        )
        report.check("跨租户数据隔离", other_tenant.get("status") == "insufficient_evidence")
    finally:
        if private_document_id:
            client.json(
                "DELETE",
                f"/api/v1/documents/{parse.quote(private_document_id)}?tenant_id={parse.quote(args.tenant)}",
                expected_status=204,
            )
            deleted_result = ask(
                client,
                "星河7429项目首次灰度发布比例是多少？",
                tenant=args.tenant,
                departments=["研发部"],
                session_id=f"acceptance-deleted-{uuid.uuid4().hex}",
            )
            report.check("删除文档后向量不可检索", deleted_result.get("status") == "insufficient_evidence")

    summary = report.summary()
    if latencies:
        ordered = sorted(latencies)
        summary["query_latency_ms"] = {
            "average": round(statistics.mean(latencies), 2),
            "p50": round(statistics.median(latencies), 2),
            "p95": round(ordered[max(0, int(len(ordered) * 0.95) - 1)], 2),
        }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n报告已写入：{output}")
    print(json.dumps({key: value for key, value in summary.items() if key != "checks"}, ensure_ascii=False, indent=2))
    return 0 if summary["failed"] == 0 else 1


def _missing_expectations(answer: str, example: dict) -> list[str]:
    """Return missing literal terms and semantic-alternative regex groups."""

    missing = [term for term in example.get("expected_terms", []) if term not in answer]
    missing.extend(
        f"pattern:{pattern}"
        for pattern in example.get("expected_patterns", [])
        if not re.search(pattern, answer)
    )
    return missing


if __name__ == "__main__":
    raise SystemExit(main())
