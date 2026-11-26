"""Celery application (Redis broker + Redis result backend).

Design rules (from the internship brief):
- Workers keep NO shared in-memory state. Tasks receive IDs and read/write PostgreSQL,
  so any number of workers can run side by side (horizontal scaling).
- JSON serialization only (pickle is unsafe and is disabled).
"""

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "hireiq",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=["app.workers.tasks", "app.workers.transcription_tasks", "app.workers.evaluation_tasks"],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    # Reliability: acknowledge after the task finishes, re-queue if a worker dies.
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Long AI tasks: take one task at a time so work spreads evenly across workers.
    worker_prefetch_multiplier=1,
    task_track_started=True,
    # Safety limits (seconds). Whisper tasks on Day 3 may need a higher limit.
    task_soft_time_limit=300,
    task_time_limit=330,
    # Task results are temporary status info, not a data store.
    result_expires=3600,
    broker_connection_retry_on_startup=True,
)
