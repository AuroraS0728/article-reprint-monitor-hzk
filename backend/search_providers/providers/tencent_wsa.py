from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from urllib.parse import urlsplit

from django.conf import settings
from django.utils import timezone
from django.utils.dateparse import parse_datetime

from adapters.safe_http import SafeHttpClient, SafeHttpError

from ..exceptions import SearchProviderRateLimited, SearchProviderUnavailable
from ..types import SearchCandidate


class TencentWsaSearchProvider:
    """Tencent Cloud Web Search API provider using its documented API KEY endpoint."""

    code = "tencent_wsa"
    endpoint = "https://api.wsa.cloud.tencent.com/SearchPro"

    def __init__(self) -> None:
        self.api_key = settings.TENCENTCLOUD_WSA_APIKEY
        self.client = SafeHttpClient(
            allowed_domains=["api.wsa.cloud.tencent.com"],
            timeout_seconds=settings.SEARCH_REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=settings.SEARCH_MAX_RESPONSE_BYTES,
        )

    def search(
        self,
        query: str,
        *,
        freshness_from: datetime | None = None,
        freshness_to: datetime | None = None,
        limit: int | None = None,
    ) -> list[SearchCandidate]:
        del freshness_from, freshness_to
        payload: dict[str, object] = {"Query": query, "Mode": 0}
        requested_limit = limit or settings.SEARCH_RESULT_LIMIT
        if requested_limit in {10, 20, 30, 40, 50}:
            payload["Cnt"] = requested_limit
        try:
            response = self.client.post(
                self.endpoint,
                headers={
                    "Accept": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json; charset=utf-8",
                },
                content=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            )
        except SafeHttpError as error:
            raise SearchProviderUnavailable("Tencent Cloud web search request failed.") from error
        if response.status_code == 429:
            raise SearchProviderRateLimited("Tencent Cloud web search rate limit or quota reached.")
        if response.status_code >= 500:
            raise SearchProviderUnavailable("Tencent Cloud web search is temporarily unavailable.")
        if response.status_code != 200:
            raise SearchProviderUnavailable(f"Tencent Cloud web search returned HTTP {response.status_code}.")
        try:
            payload_data = json.loads(response.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SearchProviderUnavailable("Tencent Cloud web search returned invalid JSON.") from error
        response_data = payload_data.get("Response") if isinstance(payload_data, dict) else None
        if not isinstance(response_data, dict):
            raise SearchProviderUnavailable("Tencent Cloud web search response is missing Response data.")
        error_data = response_data.get("Error")
        if isinstance(error_data, dict):
            error_code = str(error_data.get("Code", ""))
            if error_code == "RequestLimitExceeded":
                raise SearchProviderRateLimited("Tencent Cloud web search rate limit exceeded.")
            raise SearchProviderUnavailable("Tencent Cloud web search returned an API error.")
        pages = response_data.get("Pages", [])
        candidates: list[SearchCandidate] = []
        for page in pages if isinstance(pages, list) else []:
            item = self._decode_page(page)
            if item is None:
                continue
            url = str(item.get("url", ""))
            title = str(item.get("title", ""))
            if not url or not title:
                continue
            candidates.append(
                SearchCandidate(
                    title=title,
                    url=url,
                    snippet=str(item.get("passage", "")),
                    display_url=url,
                    domain=(urlsplit(url).hostname or "").lower(),
                    published_at=self._parse_published_at(item.get("date")),
                    provider=self.code,
                    site_name=str(item.get("site", "")),
                    raw_data={str(key): value for key, value in item.items()},
                )
            )
        return candidates

    @staticmethod
    def _decode_page(page: object) -> dict[str, object] | None:
        if isinstance(page, dict):
            return cast(dict[str, object], page)
        if not isinstance(page, str):
            return None
        try:
            decoded = json.loads(page)
        except json.JSONDecodeError:
            return None
        return cast(dict[str, object], decoded) if isinstance(decoded, dict) else None

    @staticmethod
    def _parse_published_at(value: object) -> datetime | None:
        if not value:
            return None
        raw = str(value).strip()
        parsed = parse_datetime(raw)
        if parsed is None:
            for format_string in ("%Y/%m/%d %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
                try:
                    parsed = datetime.strptime(raw, format_string)
                    break
                except ValueError:
                    continue
        if parsed is not None and timezone.is_naive(parsed):
            return timezone.make_aware(parsed, timezone.get_current_timezone())
        return parsed
