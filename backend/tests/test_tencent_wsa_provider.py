from __future__ import annotations

import json
from datetime import datetime
from typing import cast

import pytest
from django.test import override_settings
from django.utils import timezone

from adapters.safe_http import SafeHttpResponse
from search_providers.exceptions import SearchProviderRateLimited
from search_providers.providers.tencent_wsa import TencentWsaSearchProvider
from search_providers.registry import configured_search_provider


@override_settings(SEARCH_PROVIDER="tencent_wsa", TENCENTCLOUD_WSA_APIKEY="test-key")
def test_tencent_wsa_provider_posts_documented_payload_and_parses_pages(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = configured_search_provider()
    assert isinstance(provider, TencentWsaSearchProvider)
    captured: dict[str, object] = {}
    response_payload = {
        "Response": {
            "Pages": [
                json.dumps(
                    {
                        "title": "Example repost title",
                        "url": "https://news.example.com/repost",
                        "date": "2026/08/12 10:30:00",
                        "passage": "Example summary",
                        "site": "Example News",
                    }
                )
            ]
        }
    }

    def fake_post(url: str, *, headers: dict[str, str], content: bytes) -> SafeHttpResponse:
        captured.update({"url": url, "headers": headers, "content": content})
        return SafeHttpResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            headers={},
            content=json.dumps(response_payload).encode(),
            redirects=(),
            resolved_addresses=("1.1.1.1",),
        )

    monkeypatch.setattr(provider.client, "post", fake_post)
    candidates = provider.search("Example repost title", limit=20)

    assert captured["url"] == "https://api.wsa.cloud.tencent.com/SearchPro"
    assert captured["headers"] == {
        "Accept": "application/json",
        "Authorization": "Bearer test-key",
        "Content-Type": "application/json; charset=utf-8",
    }
    assert json.loads(cast(bytes, captured["content"]).decode()) == {
        "Query": "Example repost title",
        "Mode": 0,
        "Cnt": 20,
    }
    assert len(candidates) == 1
    assert candidates[0].provider == "tencent_wsa"
    assert candidates[0].published_at == timezone.make_aware(datetime(2026, 8, 12, 10, 30))


@override_settings(TENCENTCLOUD_WSA_APIKEY="test-key")
def test_tencent_wsa_provider_maps_api_rate_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = TencentWsaSearchProvider()

    def fake_post(url: str, *, headers: dict[str, str], content: bytes) -> SafeHttpResponse:
        return SafeHttpResponse(
            requested_url=url,
            final_url=url,
            status_code=200,
            headers={},
            content=b'{"Response":{"Error":{"Code":"RequestLimitExceeded"}}}',
            redirects=(),
            resolved_addresses=("1.1.1.1",),
        )

    monkeypatch.setattr(provider.client, "post", fake_post)
    with pytest.raises(SearchProviderRateLimited):
        provider.search("rate limited")
