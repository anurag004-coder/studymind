"""Celery task worker setup for asynchronous ingestion and processing."""

from app.core.config import settings

try:
    from celery import Celery  # type: ignore[import-untyped,import-not-found]

    celery_app = Celery(
        "studymind_tasks",
        broker=settings.REDIS_URL,
        backend=settings.REDIS_URL,
    )
    celery_app.conf.update(
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",
        timezone="UTC",
        enable_utc=True,
    )
except ImportError:
    celery_app = None  # type: ignore[assignment]
