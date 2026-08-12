from __future__ import annotations

from config import celery_app


def test_shared_tasks_use_configured_redis_broker(settings: object) -> None:
    assert celery_app.conf.broker_url == "redis://redis:6379/0"
    assert celery_app.conf.result_backend == "redis://redis:6379/1"
