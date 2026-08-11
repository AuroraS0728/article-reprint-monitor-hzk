from __future__ import annotations

import json
from datetime import datetime
from typing import cast
from urllib.parse import urlencode, urlsplit

from django.conf import settings
from django.utils.dateparse import parse_datetime

from adapters.safe_http import SafeHttpClient, SafeHttpError

from ..exceptions import SearchProviderRateLimited, SearchProviderUnavailable
from ..types import SearchCandidate


class BraveSearchProvider:
    code = "brave"
    endpoint = "https://api.search.brave.com/res/v1/web/search"

    def __init__(self) -> None:
        self.api_key = settings.BRAVE_SEARCH_API_KEY
        self.client = SafeHttpClient(
            allowed_domains=["api.search.brave.com"],
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
        parameters: list[tuple[str, str]] = [
            ("q", query),
            ("count", str(min(limit or settings.SEARCH_RESULT_LIMIT, 20))),
            ("safesearch", "moderate"),
            ("text_decorations", "false"),
            ("result_filter", "web"),
        ]
        if freshness_from and freshness_to:
            parameters.append(("freshness", f"{freshness_from.date().isoformat()}to{freshness_to.date().isoformat()}"))
        try:
            response = self.client.get(
                f"{self.endpoint}?{urlencode(parameters)}",
                headers={"Accept": "application/json", "X-Subscription-Token": self.api_key},
            )
        except SafeHttpError as error:
            raise SearchProviderUnavailable("搜索服务请求失败。") from error
        if response.status_code == 429:
            raise SearchProviderRateLimited("搜索服务达到调用频率或配额限制。")
        if response.status_code >= 500:
            raise SearchProviderUnavailable("搜索服务暂时不可用。")
        if response.status_code != 200:
            raise SearchProviderUnavailable(f"搜索服务返回 HTTP {response.status_code}。")
        try:
            payload = json.loads(response.content)
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SearchProviderUnavailable("搜索服务返回无法解析的 JSON。") from error
        results = payload.get("web", {}).get("results", [])
        candidates: list[SearchCandidate] = []
        for item in results if isinstance(results, list) else []:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))
            title = str(item.get("title", ""))
            if not url or not title:
                continue
            profile_value = item.get("profile")
            meta_url_value = item.get("meta_url")
            profile = cast(dict[str, object], profile_value) if isinstance(profile_value, dict) else {}
            meta_url = cast(dict[str, object], meta_url_value) if isinstance(meta_url_value, dict) else {}
            published_at = parse_datetime(str(item.get("page_age", ""))) if item.get("page_age") else None
            candidates.append(
                SearchCandidate(
                    title=title,
                    url=url,
                    snippet=str(item.get("description", "")),
                    display_url=str(meta_url.get("display_url", "")),
                    domain=(urlsplit(url).hostname or "").lower(),
                    published_at=published_at,
                    provider=self.code,
                    site_name=str(profile.get("long_name", "")),
                    raw_data={str(key): value for key, value in item.items()},
                )
            )
        return candidates
