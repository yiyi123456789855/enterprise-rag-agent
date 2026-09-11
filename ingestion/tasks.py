from __future__ import annotations

from celery import Celery

from app.config import Settings
from app.errors import public_error


TASK_NAME = "enterprise_rag.ingestion.process"
_settings = Settings.from_env()
_settings.validate()

celery_app = Celery(
    "enterprise_rag",
    broker=_settings.redis_url,
    backend=_settings.redis_url,
)
celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    task_track_started=True,
    task_soft_time_limit=_settings.celery_soft_time_limit,
    task_time_limit=_settings.celery_time_limit,
    result_expires=86400,
    broker_connection_retry_on_startup=True,
    broker_transport_options={"visibility_timeout": 3600},
    task_routes={TASK_NAME: {"queue": _settings.celery_queue}},
)


@celery_app.task(bind=True, name=TASK_NAME, acks_late=True, reject_on_worker_lost=True)
def process_ingestion_task(
    self,
    job_id: str,
    document_id: str,
    filename: str,
    content_path: str,
) -> int:
    from api.dependencies import get_ingestion_service, get_repository, get_upload_store

    import redis
    from redis.exceptions import LockError

    repository = get_repository()
    upload_store = get_upload_store()
    content_path = str(upload_store.validate_job_path(job_id, content_path))
    lock = redis.Redis.from_url(_settings.redis_url).lock(
        f"enterprise-rag:ingestion-lock:{job_id}",
        timeout=_settings.celery_time_limit + 60,
        blocking_timeout=0,
    )
    if not lock.acquire(blocking=False):
        return 0
    try:
        job = repository.get_job(job_id)
        if job["status"] == "completed":
            upload_store.delete(content_path)
            return 0
        try:
            count = get_ingestion_service().process_file(
                job_id,
                document_id,
                filename,
                content_path,
            )
        except Exception as exc:
            if self.request.retries < _settings.celery_max_retries:
                repository.update_job(job_id, "retrying", public_error(exc))
                countdown = min(60, 2 ** (self.request.retries + 1))
                raise self.retry(exc=exc, countdown=countdown)
            upload_store.delete(content_path)
            raise
        upload_store.delete(content_path)
        return count
    finally:
        try:
            lock.release()
        except LockError:
            pass
