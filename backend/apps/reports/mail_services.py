from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken
from django.conf import settings
from django.core.mail import EmailMessage, get_connection
from django.utils import timezone

from apps.core.redaction import safe_error_message

from .models import DeliveryStatus, ReportEmailDelivery, SMTPConfiguration


class SMTPConfigurationError(ValueError):
    pass


def _fernet() -> Fernet:
    key = getattr(settings, "FIELD_ENCRYPTION_KEY", "")
    if not key:
        raise SMTPConfigurationError("未配置 FIELD_ENCRYPTION_KEY，无法保存或使用 SMTP 授权码。")
    try:
        return Fernet(key.encode())
    except (TypeError, ValueError) as error:
        raise SMTPConfigurationError("FIELD_ENCRYPTION_KEY 格式无效。") from error


def encrypt_authorization_code(value: str) -> str:
    return _fernet().encrypt(value.encode()).decode()


def decrypt_authorization_code(value: str) -> str:
    try:
        return _fernet().decrypt(value.encode()).decode()
    except InvalidToken as error:
        raise SMTPConfigurationError("SMTP 授权码无法解密，请由管理员重新配置。") from error


def smtp_configuration() -> SMTPConfiguration:
    return SMTPConfiguration.objects.order_by("id").first() or SMTPConfiguration()


def validate_configuration(config: SMTPConfiguration) -> None:
    if not config.enabled:
        raise SMTPConfigurationError("SMTP 未启用。")
    if not (config.host and config.from_email and config.encrypted_authorization_code and config.recipients):
        raise SMTPConfigurationError("SMTP 配置不完整。")


def send_delivery(delivery: ReportEmailDelivery) -> None:
    config = smtp_configuration()
    try:
        validate_configuration(config)
        password = decrypt_authorization_code(config.encrypted_authorization_code)
        connection = get_connection(
            host=config.host,
            port=config.port,
            username=config.username,
            password=password,
            use_tls=config.use_tls,
            fail_silently=False,
        )
        report = delivery.report
        message = EmailMessage(
            subject=(
                f"文章转载监测周报 {report.period_start.isoformat()} 至 "
                f"{report.period_end.isoformat()} V{report.version}"
            ),
            body="附件为系统生成的周报。",
            from_email=config.from_email,
            to=list(delivery.recipients),
            cc=list(delivery.cc_recipients),
            connection=connection,
        )
        with report.report_file.open("rb") as report_file:
            message.attach(
                report.report_file.name.rsplit("/", maxsplit=1)[-1],
                report_file.read(),
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        message.send()
        delivery.status = DeliveryStatus.SENT
        delivery.error_message = ""
        delivery.sent_at = timezone.now()
    except Exception as error:
        delivery.status = DeliveryStatus.FAILED
        delivery.error_message = safe_error_message(error)
        raise
    finally:
        delivery.attempt_count += 1
        delivery.save(update_fields=["status", "error_message", "sent_at", "attempt_count"])
