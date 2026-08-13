from __future__ import annotations

from rest_framework import permissions
from rest_framework.request import Request
from rest_framework.response import Response
from rest_framework.views import APIView

from apps.core.serializers import EmptySerializer
from apps.core.views import ok
from apps.reposts.models import ContentRelation, RepostRecord

from .models import OwnedChannel


class OwnedChannelReadingView(APIView):
    """A safe reading-metric boundary: configuration and owned publications only.

    No reading provider is called until a real approved provider is integrated.
    """

    permission_classes = [permissions.IsAuthenticated]
    serializer_class = EmptySerializer

    def get(self, request: Request) -> Response:
        channels = OwnedChannel.objects.filter(is_active=True).order_by("code")
        records = RepostRecord.objects.filter(
            is_valid=True,
            content_relation=ContentRelation.OWNED,
        ).select_related("article", "owned_channel")
        return ok(
            {
                "provider_status": "接口待接入",
                "channels": [
                    {
                        "id": channel.id,
                        "code": channel.code,
                        "name": channel.name,
                        "channel_type": channel.channel_type,
                        "notes": channel.notes,
                    }
                    for channel in channels
                ],
                "publications": [
                    {
                        "id": record.id,
                        "article_id": record.article_id,
                        "article_title": record.article.title,
                        "channel_name": (record.owned_channel.name if record.owned_channel else ""),
                        "url": record.canonical_url or record.normalized_url,
                        "published_at": record.result_published_at,
                        "reading_count": None,
                        "reading_status": "接口待接入",
                    }
                    for record in records.order_by("-first_found_at", "-id")[:500]
                ],
            }
        )
