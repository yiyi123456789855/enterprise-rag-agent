from __future__ import annotations

import logging

from app.config import Settings
from app.database import Repository
from ingestion.service import IngestionService
from ingestion.upload_store import UploadStore


logger = logging.getLogger(__name__)


class IngestionDispatcher:
    def __init__(
        self,
        settings: Settings,
        repository: Repository,
        service: IngestionService,
        upload_store: UploadStore,
    ):
        self.settings = settings
        self.repository = repository
        self.service = service
        self.upload_store = upload_store

    def dispatch(
        self,
        *,
        job_id: str,
        document_id: str,
        filename: str,
        content_path: str,
    ) -> None:
        content_path = str(self.upload_store.validate_job_path(job_id, content_path))
        if self.settings.task_queue_backend == "sync":
            try:
                self.service.process_file(job_id, document_id, filename, content_path)
            finally:
                self.upload_store.delete(content_path)
            return

        self.repository.update_job(job_id, "queued")
        try:
            from ingestion.tasks import TASK_NAME, celery_app

            celery_app.send_task(
                TASK_NAME,
                args=[job_id, document_id, filename, content_path],
                task_id=job_id,
                queue=self.settings.celery_queue,
            )
        except Exception as exc:
            logger.error("Queue dispatch failed job_id=%s error_type=%s", job_id, type(exc).__name__)
            self.repository.update_job(job_id, "failed", "Queue dispatch failed")
            self.upload_store.delete(content_path)
            raise RuntimeError("Unable to enqueue ingestion task") from exc

    def health(self) -> bool:
        if self.settings.task_queue_backend == "sync":
            return True
        try:
            import redis

            broker_ready = bool(
                redis.Redis.from_url(
                    self.settings.redis_url,
                    socket_connect_timeout=2,
                    socket_timeout=2,
                ).ping()
            )
            if not broker_ready:
                return False
            from ingestion.tasks import celery_app

            return bool(celery_app.control.inspect(timeout=1).ping())
        except Exception:
            return False
