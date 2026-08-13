from __future__ import annotations

from types import SimpleNamespace

import pytest

from search_providers.exceptions import SearchProviderCaptchaRequired, SearchProviderParseError
from search_providers.providers.bing_html import BingHtmlSearchProvider


def _response(document: str, *, status_code: int = 200, final_url: str = "https://cn.bing.com/search?q=test") -> object:
    return SimpleNamespace(status_code=status_code, final_url=final_url, content=document.encode("utf-8"))


def test_bing_public_page_parses_only_result_page_fields(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BingHtmlSearchProvider()
    document = """
    <ol id="b_results">
      <li class="b_algo">
        <cite>https://www.116.com.cn / articles</cite>
        <h2><a href="https://www.116.com.cn/a">Test title - TianTian</a></h2>
      </li>
      <li class="b_algo">
        <cite>http://www.sanhuba.com / gsdt</cite>
        <h2><a href="http://www.sanhuba.com/b">Test title - Sanhuba</a></h2>
      </li>
    </ol>
    """
    calls: list[str] = []

    def get(url: str, *, headers: dict[str, str]) -> object:
        calls.append(url)
        assert headers["User-Agent"] == provider.user_agent
        return _response(document)

    monkeypatch.setattr(provider.client, "get", get)
    results = provider.search('"Test title"', limit=20)

    assert calls == ["https://www.bing.com/search?q=%22Test+title%22&count=20"]
    assert [(item.site_name, item.title, item.url) for item in results] == [
        ("https://www.116.com.cn / articles", "Test title - TianTian", "https://www.116.com.cn/a"),
        ("http://www.sanhuba.com / gsdt", "Test title - Sanhuba", "http://www.sanhuba.com/b"),
    ]


def test_bing_public_page_stops_on_captcha(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BingHtmlSearchProvider()
    monkeypatch.setattr(
        provider.client,
        "get",
        lambda *args, **kwargs: _response('<html><div id="b_captcha">verification</div></html>'),
    )
    with pytest.raises(SearchProviderCaptchaRequired):
        provider.search("Test title")


def test_bing_public_page_rejects_unverified_structure(monkeypatch: pytest.MonkeyPatch) -> None:
    provider = BingHtmlSearchProvider()
    monkeypatch.setattr(provider.client, "get", lambda *args, **kwargs: _response("<html><body>empty</body></html>"))
    with pytest.raises(SearchProviderParseError):
        provider.search("Test title")
