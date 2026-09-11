from __future__ import annotations


def public_error(exc: Exception) -> str:
    """Return a bounded job error that cannot expose connection secrets."""

    if isinstance(exc, ValueError):
        message = " ".join(str(exc).split())[:400]
        return message or "Document validation failed"
    return f"{type(exc).__name__}: ingestion failed"
