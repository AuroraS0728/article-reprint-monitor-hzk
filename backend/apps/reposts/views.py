from __future__ import annotations

from typing import cast
from urllib.parse import quote

from django.http import HttpResponse
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.utils.dateparse import parse_date
from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.articles.models import Article
from apps.audit.services import record_audit
from apps.core.permissions import CanOperate, IsAdministrator
from apps.core.serializers import EmptySerializer
from apps.core.views import ok
from apps.platforms.models import Platform

from .export_services import GlobalExportFilters, build_global_repost_workbook
from .models import RepostRecord
from .serializers import ManualRepostCreateSerializer, ManualRepostStateSerializer, RepostRecordSerializer
from .services import (
    ManualSupplementConflict,
    create_manual_supplement,
    manual_repost_before_data,
    set_manual_supplement_validity,
)


class RepostRecordListView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = RepostRecordSerializer

    def get(self, request: Request) -> Response:
        queryset = RepostRecord.objects.select_related("article", "platform", "manually_added_by", "invalidated_by")
        if request.query_params.get("manual") == "true":
            queryset = queryset.filter(data_source="MANUAL_SUPPLEMENT")
        return ok(RepostRecordSerializer(queryset[:200], many=True).data)


class GlobalRepostExportView(APIView):
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> HttpResponse:
        start_date = parse_date(request.query_params.get("start_date", ""))
        end_date = parse_date(request.query_params.get("end_date", ""))
        raw_article_id = request.query_params.get("article_id", "")
        raw_has_repost = request.query_params.get("has_repost", "").lower()
        filters = GlobalExportFilters(
            start_date=start_date,
            end_date=end_date,
            article_id=int(raw_article_id) if raw_article_id.isdigit() else None,
            author=request.query_params.get("author", "").strip(),
            monitoring_status=request.query_params.get("monitoring_status", "").strip(),
            site_domain=request.query_params.get("site_domain", "").strip().lower(),
            has_repost=True if raw_has_repost == "true" else False if raw_has_repost == "false" else None,
        )
        content, export_as_of = build_global_repost_workbook(filters)
        if start_date and end_date:
            filename = f"文章转载监测_{start_date:%Y%m%d}-{end_date:%Y%m%d}.xlsx"
        else:
            filename = f"文章转载监测_{timezone.localtime(export_as_of):%Y%m%d_%H%M}.xlsx"
        response = HttpResponse(
            content,
            content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
        response["Content-Disposition"] = f"attachment; filename*=UTF-8''{quote(filename)}"
        return response


class ManualRepostCreateView(APIView):
    permission_classes = [CanOperate]
    serializer_class = ManualRepostCreateSerializer

    @extend_schema(operation_id="manual_repost_create")
    def post(self, request: Request) -> Response:
        serializer = ManualRepostCreateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        actor = cast(User, request.user)
        try:
            record = create_manual_supplement(
                article=cast(Article, data["article"]),
                platform=cast(Platform, data["platform"]),
                repost_url=cast(str, data["repost_url"]),
                reason=cast(str, data["reason"]),
                actor=actor,
            )
        except (ManualSupplementConflict, ValueError) as error:
            return Response(
                {"success": False, "error": {"code": "MANUAL_SUPPLEMENT_INVALID", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="MANUAL_REPOST_CREATE",
            target_type="RepostRecord",
            target_id=record.id,
            after_data=manual_repost_before_data(record),
        )
        return ok(RepostRecordSerializer(record).data, status.HTTP_201_CREATED)


class ManualRepostValidityView(APIView):
    permission_classes = [IsAdministrator]
    serializer_class = ManualRepostStateSerializer

    @extend_schema(operation_id="manual_repost_validity_update")
    def post(self, request: Request, pk: int, action: str) -> Response:
        serializer = ManualRepostStateSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        record = get_object_or_404(RepostRecord, pk=pk)
        before = manual_repost_before_data(record)
        valid = action == "restore"
        if action not in {"invalidate", "restore"}:
            return Response(
                {"success": False, "error": {"code": "VALIDATION_ERROR", "message": "不支持的人工补录操作。"}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        try:
            record = set_manual_supplement_validity(
                record=record,
                valid=valid,
                reason=cast(str, serializer.validated_data.get("reason", "")),
                actor=cast(User, request.user),
            )
        except ValueError as error:
            return Response(
                {"success": False, "error": {"code": "MANUAL_SUPPLEMENT_INVALID", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="MANUAL_REPOST_RESTORE" if valid else "MANUAL_REPOST_INVALIDATE",
            target_type="RepostRecord",
            target_id=record.id,
            before_data=before,
            after_data=manual_repost_before_data(record),
        )
        return ok(RepostRecordSerializer(record).data)
