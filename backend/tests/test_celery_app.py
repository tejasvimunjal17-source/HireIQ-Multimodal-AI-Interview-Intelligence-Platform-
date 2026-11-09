"""Celery configuration and task registration. Eager mode = no Redis needed (labelled)."""

import pytest

from app.workers.celery_app import celery_app
from app.workers.tasks import ping


def test_celery_uses_redis_from_settings():
    assert celery_app.conf.broker_url.startswith("redis://")
    assert celery_app.conf.result_backend.startswith("redis://")


def test_celery_serialization_is_json_only():
    conf = celery_app.conf
    assert conf.task_serializer == "json"
    assert conf.result_serializer == "json"
    assert list(conf.accept_content) == ["json"]  # pickle disabled


def test_celery_reliability_and_scaling_settings():
    conf = celery_app.conf
    assert conf.task_acks_late is True
    assert conf.task_reject_on_worker_lost is True
    assert conf.worker_prefetch_multiplier == 1
    assert conf.result_expires == 3600
    assert conf.task_time_limit > conf.task_soft_time_limit
    assert conf.timezone == "UTC"


def test_demo_task_is_registered():
    celery_app.loader.import_default_modules()
    assert "hireiq.ping" in celery_app.tasks


def test_demo_task_retry_configuration():
    assert ping.max_retries == 3
    assert ConnectionError in ping.autoretry_for
    assert ping.retry_backoff is True


@pytest.mark.mocked
def test_demo_task_runs_in_eager_mode(monkeypatch):
    """MOCKED broker: eager mode runs the task in-process, so this does NOT prove Redis/worker work."""
    monkeypatch.setattr(celery_app.conf, "task_always_eager", True)
    result = ping.delay("hello").get()
    assert result["status"] == "ok"
    assert result["message"] == "hello"
    assert result["worker"]
