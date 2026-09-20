import logging
import sys

from celery import Celery

from app.core.config import get_settings

settings = get_settings()

celery_app = Celery(
    "event_booking_workers",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.workers.tasks.booking_email",
        "app.workers.tasks.event_notification",
    ],
)

celery_app.conf.update(
    task_serializer="json",
    accept_content=["json"],
    result_serializer="json",
    timezone="UTC",
    enable_utc=True,
    task_track_started=True,
    task_time_limit=3600,
    worker_prefetch_multiplier=1,
    task_acks_late=True,  # Important for idempotency and at-least-once processing
)

# Fail clearly if resend_api_key is missing
if not settings.resend_api_key:
    logging.critical("RESEND_API_KEY is not set. Worker cannot send emails.")
    sys.exit(1)
