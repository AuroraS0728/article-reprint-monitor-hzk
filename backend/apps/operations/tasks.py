from celery import shared_task

from .services import cleanup_expired_data, create_database_backup


@shared_task
def cleanup_expired_data_task() -> int:
    return cleanup_expired_data().id


@shared_task
def create_database_backup_task() -> int:
    return create_database_backup().id
