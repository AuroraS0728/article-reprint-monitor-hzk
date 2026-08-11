from __future__ import annotations

from datetime import datetime, time, timedelta

from celery import shared_task
from django.core.cache import cache
from django.db import transaction
from django.utils import timezone

from apps.articles.models import Article, ArticleStatus
from apps.core.redaction import safe_error_message
from apps.platforms.models import Platform, PlatformStatus
from apps.reports.models import ReportEmailDelivery, ReportType
from apps.reports.services import create_report
from apps.reports.tasks import send_report_email

from .batch_services import automatic_idempotency_key, create_batch
from .models import BatchStatus, DetectionBatch, SnapshotType, TaskFailureLog
from .services import evaluate_detection
from .snapshot_services import create_status_snapshot


@shared_task(
    bind=True,
    autoretry_for=(ConnectionError,),
    retry_backoff=True,
    retry_kwargs={"max_retries": 3},
    soft_time_limit=25 * 60,
    time_limit=30 * 60,
)
def run_detection_batch(self, batch_id: int) -> str:
    lock_key = f"monitoring:batch:{batch_id}"
    if not cache.add(lock_key, self.request.id, timeout=60 * 30):
        return "already-running"
    try:
        with transaction.atomic():
            batch = DetectionBatch.objects.select_for_update().get(pk=batch_id)
            if batch.status == BatchStatus.COMPLETED:
                return "already-completed"
            batch.status = BatchStatus.RUNNING
            batch.started_at = batch.started_at or timezone.now()
            batch.save(update_fields=["status", "started_at"])
        for result in batch.results.select_related("article", "platform").all():
            evaluate_detection(result=result)
        batch.status = BatchStatus.COMPLETED
        batch.completed_at = timezone.now()
        batch.failure_message = ""
        batch.save(update_fields=["status", "completed_at", "failure_message"])
        return "completed"
    except Exception as error:
        error_message = safe_error_message(error, limit=500)
        DetectionBatch.objects.filter(pk=batch_id).update(status=BatchStatus.FAILED, failure_message=error_message)
        TaskFailureLog.objects.create(
            task_name="run_detection_batch",
            batch_id=batch_id,
            error_type=type(error).__name__,
            message=error_message,
        )
        raise
    finally:
        cache.delete(lock_key)


@shared_task
def schedule_automatic_batches() -> int:
    now = timezone.localtime()
    week_start = now.date() - timedelta(days=now.weekday())
    articles = Article.objects.filter(
        status=ArticleStatus.ACTIVE, published_date__gte=week_start, published_date__lte=now.date()
    )
    platforms = Platform.objects.filter(status=PlatformStatus.ENABLED)
    if not articles.exists() or not platforms.exists():
        return 0
    batch = create_batch(
        trigger="AUTOMATIC",
        article_ids=articles.values_list("id", flat=True),
        platform_ids=platforms.values_list("id", flat=True),
        created_by=None,
        idempotency_key=automatic_idempotency_key(week=str(now.isocalendar().week), hour=now.strftime("%Y%m%d%H")),
    )
    run_detection_batch.delay(batch.id)
    return batch.id


@shared_task
def schedule_weekly_final_batch() -> int:
    now = timezone.localtime()
    current_week_start = now.date() - timedelta(days=now.weekday())
    previous_week_start = current_week_start - timedelta(days=7)
    articles = Article.objects.filter(
        status=ArticleStatus.ACTIVE, published_date__gte=previous_week_start, published_date__lt=current_week_start
    )
    platforms = Platform.objects.filter(status=PlatformStatus.ENABLED)
    if not articles.exists() or not platforms.exists():
        return 0
    batch = create_batch(
        trigger="WEEKLY_FINAL",
        article_ids=articles.values_list("id", flat=True),
        platform_ids=platforms.values_list("id", flat=True),
        created_by=None,
        idempotency_key=f"weekly-final:{previous_week_start.isoformat()}",
    )
    run_detection_batch.delay(batch.id)
    return batch.id


@shared_task
def create_daily_status_snapshot() -> int:
    now = timezone.localtime()
    cutoff_at = timezone.make_aware(datetime.combine(now.date(), time.min))
    snapshot = create_status_snapshot(snapshot_type=SnapshotType.DAILY, cutoff_at=cutoff_at)
    report_date = now.date() - timedelta(days=1)
    create_report(
        report_type=ReportType.DAILY,
        report_date=report_date,
        period_start=report_date,
        period_end=report_date,
        snapshot=snapshot,
        generated_by=None,
    )
    return snapshot.id


@shared_task(bind=True)
def create_weekly_status_snapshot(self) -> int:
    now = timezone.localtime()
    week_start = now.date() - timedelta(days=now.weekday())
    final_batch = (
        DetectionBatch.objects.filter(
            trigger="WEEKLY_FINAL",
            status=BatchStatus.COMPLETED,
            completed_at__gte=timezone.make_aware(datetime.combine(week_start, time.min)),
        )
        .order_by("-completed_at")
        .first()
    )
    cutoff_at = timezone.make_aware(datetime.combine(week_start, time(hour=7)))
    if final_batch is None:
        TaskFailureLog.objects.create(
            task_name="create_weekly_status_snapshot",
            error_type="FINAL_BATCH_NOT_COMPLETED",
            message="周一 07:30 尚无已完成的周最终检测批次；未生成空周报快照。",
        )
        raise self.retry(countdown=60, max_retries=30)
    snapshot = create_status_snapshot(snapshot_type=SnapshotType.WEEKLY, cutoff_at=cutoff_at, source_batch=final_batch)
    previous_week_start = week_start - timedelta(days=7)
    report = create_report(
        report_type=ReportType.WEEKLY,
        report_date=previous_week_start,
        period_start=previous_week_start,
        period_end=week_start - timedelta(days=1),
        snapshot=snapshot,
        generated_by=None,
    )
    from apps.reports.mail_services import smtp_configuration

    config = smtp_configuration()
    if config.enabled and config.recipients:
        delivery = ReportEmailDelivery.objects.create(
            report=report,
            recipients=list(config.recipients),
            cc_recipients=list(config.cc_recipients),
        )
        send_report_email.delay(delivery.id)
    return snapshot.id
