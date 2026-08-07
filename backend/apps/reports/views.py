from __future__ import annotations

from typing import cast

from django.http import FileResponse
from django.shortcuts import get_object_or_404
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.core.permissions import IsAdministrator
from apps.core.views import ok

from .mail_services import SMTPConfigurationError, smtp_configuration
from .models import GeneratedReport, ReportEmailDelivery, ReportType
from .serializers import EmailDeliverySerializer, ReportSerializer, SMTPConfigurationSerializer
from .services import create_report
from .tasks import send_report_email


class ReportListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportSerializer

    def get(self, request: Request) -> Response:
        reports = GeneratedReport.objects.all()
        report_type = request.query_params.get("report_type")
        if report_type:
            reports = reports.filter(report_type=report_type)
        return ok(ReportSerializer(reports[:100], many=True).data)


class ReportDownloadView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = ReportSerializer

    def get(self, request: Request, pk: int) -> Response | FileResponse:
        report = get_object_or_404(GeneratedReport, pk=pk)
        if not report.report_file:
            return Response(
                {
                    "success": False,
                    "error": {"code": "REPORT_FILE_EXPIRED", "message": "报表文件已按保留策略清理，可重新生成。"},
                },
                status=404,
            )
        record_audit(request, action_type="REPORT_DOWNLOAD", target_type="GeneratedReport", target_id=report.id)
        return FileResponse(
            report.report_file.open("rb"),
            as_attachment=True,
            filename=f"{report.report_type.lower()}-{report.report_date.isoformat()}-v{report.version}.xlsx",
        )


class ReportRegenerateView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = ReportSerializer

    def post(self, request: Request, pk: int) -> Response:
        source = get_object_or_404(GeneratedReport, pk=pk)
        actor = cast(User, request.user)
        report = create_report(
            report_type=source.report_type,
            report_date=source.report_date,
            period_start=source.period_start,
            period_end=source.period_end,
            snapshot=source.snapshot,
            generated_by=actor,
            regenerate=True,
        )
        record_audit(
            request,
            action_type="REPORT_REGENERATE",
            target_type="GeneratedReport",
            target_id=report.id,
            after_data={"source_report_id": source.id, "version": report.version},
        )
        return ok(ReportSerializer(report).data, status.HTTP_201_CREATED)


class SMTPConfigurationView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = SMTPConfigurationSerializer

    def get(self, request: Request) -> Response:
        return ok(SMTPConfigurationSerializer(smtp_configuration()).data)

    def patch(self, request: Request) -> Response:
        config = smtp_configuration()
        serializer = SMTPConfigurationSerializer(config, data=request.data, partial=True)
        serializer.is_valid(raise_exception=True)
        try:
            changed = serializer.save(updated_by=request.user)
        except SMTPConfigurationError as error:
            return Response(
                {"success": False, "error": {"code": "SMTP_CONFIG_ERROR", "message": str(error)}}, status=400
            )
        record_audit(request, action_type="SMTP_CONFIG_UPDATE", target_type="SMTPConfiguration", target_id=changed.id)
        return ok(SMTPConfigurationSerializer(changed).data)


class EmailDeliveryListView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = EmailDeliverySerializer

    def get(self, request: Request) -> Response:
        return ok(EmailDeliverySerializer(ReportEmailDelivery.objects.all()[:100], many=True).data)


class EmailDeliveryResendView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = EmailDeliverySerializer

    def post(self, request: Request, pk: int) -> Response:
        source = get_object_or_404(ReportEmailDelivery, pk=pk)
        actor = cast(User, request.user)
        delivery = ReportEmailDelivery.objects.create(
            report=source.report,
            recipients=source.recipients,
            cc_recipients=source.cc_recipients,
            requested_by=actor,
        )
        send_report_email.delay(delivery.id)
        record_audit(
            request, action_type="REPORT_EMAIL_RESEND", target_type="ReportEmailDelivery", target_id=delivery.id
        )
        return ok(EmailDeliverySerializer(delivery).data, status.HTTP_201_CREATED)


class TestEmailView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = EmailDeliverySerializer

    def post(self, request: Request) -> Response:
        latest_weekly = GeneratedReport.objects.filter(report_type=ReportType.WEEKLY).first()
        if latest_weekly is None:
            return Response(
                {"success": False, "error": {"code": "REPORT_NOT_FOUND", "message": "尚无周报附件可发送测试邮件。"}},
                status=400,
            )
        config = smtp_configuration()
        actor = cast(User, request.user)
        delivery = ReportEmailDelivery.objects.create(
            report=latest_weekly,
            recipients=list(config.recipients),
            cc_recipients=list(config.cc_recipients),
            requested_by=actor,
        )
        send_report_email.delay(delivery.id)
        record_audit(request, action_type="SMTP_TEST_EMAIL", target_type="ReportEmailDelivery", target_id=delivery.id)
        return ok(EmailDeliverySerializer(delivery).data, status.HTTP_201_CREATED)
