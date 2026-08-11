from __future__ import annotations

from celery import shared_task

from .mail_services import send_delivery
from .models import ReportEmailDelivery


@shared_task(bind=True, autoretry_for=(Exception,), retry_backoff=True, retry_kwargs={"max_retries": 2})
def send_report_email(self, delivery_id: int) -> str:
    delivery = ReportEmailDelivery.objects.select_related("report").get(pk=delivery_id)
    send_delivery(delivery)
    return "sent"
