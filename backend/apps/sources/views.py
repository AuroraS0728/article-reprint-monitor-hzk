from __future__ import annotations

from datetime import datetime
from typing import cast

from drf_spectacular.utils import extend_schema
from rest_framework import permissions, status
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.accounts.models import User
from apps.audit.services import record_audit
from apps.core.views import ok

from .authentication import SourceTokenAuthentication
from .models import SourceIngestToken
from .serializers import SourceArticleIngestSerializer
from .services import ingest_source_article


class SourceArticleIngestView(APIView):
    authentication_classes = [SourceTokenAuthentication]
    permission_classes = [permissions.IsAuthenticated]
    serializer_class = SourceArticleIngestSerializer

    @extend_schema(operation_id="source_article_ingest", request=SourceArticleIngestSerializer)
    def post(self, request: Request) -> Response:
        serializer = SourceArticleIngestSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        data = serializer.validated_data
        token = cast(SourceIngestToken, request.auth)
        try:
            result = ingest_source_article(
                source=token.source,
                title=cast(str, data["title"]),
                author=cast(str, data["author"]),
                published_at=cast(datetime, data["published_at"]),
                original_url=cast(str, data["original_url"]),
                created_by=cast(User, request.user),
            )
        except ValueError as error:
            return Response(
                {"success": False, "error": {"code": "INVALID_SOURCE_ARTICLE", "message": str(error)}},
                status=status.HTTP_400_BAD_REQUEST,
            )
        record_audit(
            request,
            action_type="SOURCE_ARTICLE_CREATE" if result.created else "SOURCE_ARTICLE_UPDATE",
            target_type="Article",
            target_id=result.article.id,
            after_data={
                "source": token.source.code,
                "article_id": result.article.id,
                "created": result.created,
                "updated": result.updated,
            },
        )
        return ok(
            {
                "created": result.created,
                "updated": result.updated,
                "article_id": result.article.id,
                "monitoring": result.article.monitoring_status == "ACTIVE",
                "monitor_until": result.article.monitor_until,
                "retention_until": result.article.retention_until,
            },
            status.HTTP_201_CREATED if result.created else status.HTTP_200_OK,
        )
