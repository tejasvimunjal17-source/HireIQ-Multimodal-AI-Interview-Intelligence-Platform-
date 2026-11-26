"""Celery tasks. Day 1 contains only a demonstration task."""

import socket

from app.workers.celery_app import celery_app


@celery_app.task(
    bind=True,
    name="hireiq.ping",
    autoretry_for=(ConnectionError, TimeoutError),
    retry_backoff=True,
    retry_backoff_max=60,
    retry_jitter=True,
    max_retries=3,
)
def ping(self, message: str = "pong") -> dict[str, str]:
    """Demo task proving the API -> Redis -> worker path works.

    Never pass candidate data (transcripts, names) as task arguments or results.
    """
    return {
        "status": "ok",
        "message": message,
        "task_id": str(self.request.id or ""),
        "worker": socket.gethostname(),
    }
