from __future__ import annotations

import argparse
from datetime import datetime, timedelta, timezone

from api.dependencies import get_ingestion_dispatcher, get_repository, get_settings, get_upload_store


def main() -> int:
    parser = argparse.ArgumentParser(description="Requeue ingestion jobs stranded by a process failure")
    parser.add_argument("--older-than-seconds", type=int, default=3600)
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    if args.older_than_seconds < get_settings().celery_time_limit:
        raise SystemExit("Recovery age must be at least CELERY_TIME_LIMIT")

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=args.older_than_seconds)
    repository = get_repository()
    upload_store = get_upload_store()
    dispatcher = get_ingestion_dispatcher()
    jobs = repository.list_recoverable_jobs(cutoff.isoformat(), args.limit)
    requeued = 0
    missing = 0
    for job in jobs:
        path = upload_store.path_for_job(job["id"])
        if not path.is_file():
            repository.update_job(job["id"], "failed", "Upload spool file is missing")
            missing += 1
            continue
        dispatcher.dispatch(
            job_id=job["id"],
            document_id=job["document_id"],
            filename=job["filename"],
            content_path=str(path),
        )
        requeued += 1
    print(f"Recovery complete: requeued={requeued}, missing_spool={missing}, scanned={len(jobs)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
