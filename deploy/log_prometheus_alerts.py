#!/usr/bin/env python3
"""Record Prometheus alert transitions as structured journal logs."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.request import Request, urlopen


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def emit(event: str, level: str = "INFO", **fields: Any) -> None:
    payload = {
        "timestamp": utc_now(),
        "level": level,
        "component": "enterprise-rag-alert-logger",
        "event": event,
        **fields,
    }
    print(json.dumps(payload, ensure_ascii=False, separators=(",", ":")), flush=True)


def alert_key(labels: dict[str, str]) -> str:
    encoded = json.dumps(labels, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def load_state(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    try:
        with path.open(encoding="utf-8") as file:
            payload = json.load(file)
    except (OSError, json.JSONDecodeError) as exc:
        emit("state_load_failed", level="ERROR", error_type=type(exc).__name__)
        return {}
    alerts = payload.get("alerts", {})
    return alerts if isinstance(alerts, dict) else {}


def save_state(path: Path, alerts: dict[str, dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", dir=str(path.parent)
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as file:
            json.dump(
                {"updated_at": utc_now(), "alerts": alerts},
                file,
                ensure_ascii=False,
                sort_keys=True,
            )
            file.write("\n")
            file.flush()
            os.fsync(file.fileno())
        os.chmod(temporary_name, 0o600)
        os.replace(temporary_name, path)
    finally:
        if os.path.exists(temporary_name):
            os.unlink(temporary_name)


def fetch_alerts(url: str, timeout: float) -> list[dict[str, Any]]:
    request = Request(url, headers={"Accept": "application/json"})
    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)
    if payload.get("status") != "success":
        raise RuntimeError("Prometheus returned a non-success response")
    alerts = payload.get("data", {}).get("alerts", [])
    if not isinstance(alerts, list):
        raise RuntimeError("Prometheus response does not contain an alerts list")
    return alerts


def normalize(alert: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    labels = {
        str(key): str(value)
        for key, value in alert.get("labels", {}).items()
    }
    annotations = {
        str(key): str(value)
        for key, value in alert.get("annotations", {}).items()
    }
    state = str(alert.get("state", "unknown"))
    record = {
        "state": state,
        "labels": labels,
        "annotations": annotations,
        "active_at": alert.get("activeAt", ""),
    }
    return alert_key(labels), record


def record_transition(event: str, record: dict[str, Any]) -> None:
    labels = record.get("labels", {})
    annotations = record.get("annotations", {})
    state = record.get("state", "unknown")
    level = "WARNING" if state == "firing" else "INFO"
    emit(
        event,
        level=level,
        alertname=labels.get("alertname", "unknown"),
        severity=labels.get("severity", "unknown"),
        state=state,
        summary=annotations.get("summary", ""),
        labels=labels,
        active_at=record.get("active_at", ""),
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--prometheus-url",
        default="http://127.0.0.1:9090/api/v1/alerts",
    )
    parser.add_argument(
        "--state-file",
        type=Path,
        default=Path("data/monitoring/prometheus-alert-state.json"),
    )
    parser.add_argument("--timeout", type=float, default=10.0)
    args = parser.parse_args()

    previous = load_state(args.state_file)
    try:
        raw_alerts = fetch_alerts(args.prometheus_url, args.timeout)
    except Exception as exc:
        emit(
            "prometheus_query_failed",
            level="ERROR",
            error_type=type(exc).__name__,
            message=str(exc)[:500],
        )
        return 2

    current = dict(normalize(alert) for alert in raw_alerts)

    for key, record in current.items():
        old_record = previous.get(key)
        if old_record is None:
            record_transition(f"alert_{record['state']}", record)
        elif old_record.get("state") != record.get("state"):
            record_transition(f"alert_{record['state']}", record)

    for key, old_record in previous.items():
        if key not in current:
            resolved = {**old_record, "state": "resolved"}
            record_transition("alert_resolved", resolved)

    first_run = not args.state_file.exists()
    save_state(args.state_file, current)
    if first_run and not current:
        emit("monitor_ready", active_alerts=0)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
