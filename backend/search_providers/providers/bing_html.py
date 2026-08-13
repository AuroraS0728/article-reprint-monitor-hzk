"""Verified public Bing result-page provider.

This source only reads the Bing result page. It does not visit result URLs,
does not send cookies, and never attempts to bypass CAPTCHA or sign-in flows.
"""

from __future__ import annotations

import re
from html import unescape
from html.parser import HTMLParser
from urllib.parse import urlencode, urlsplit

from django.conf import settings

from adapters.safe_http import SafeHttpClient, SafeHttpError

from ..exceptions import (
    SearchProviderCaptchaRequired,
    SearchProviderParseError,
    SearchProviderUnavailable,
)
from ..types import SearchCandidate


class _BingResultParser(HTMLParser):
    """Extract only verified result fields from ``ol#b_results > li.b_algo``."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._depth = 0
        self._result_depth: int | None = None
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._parts: list[str] = []
        self._in_heading = False
        self.saw_results_container = False
        self.saw_no_results = False
        self.rows: list[dict[str, str]] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self._depth += 1
        attributes = {key: value or "" for key, value in attrs}
        classes = set(attributes.get("class", "").split())
        if tag == "ol" and attributes.get("id") == "b_results":
            self.saw_results_container = True
        if tag == "li" and "b_no" in classes:
            self.saw_no_results = True
        if tag == "li" and "b_algo" in classes and self._current is None:
            self._result_depth = self._depth
            self._current = {"site_name": "", "title": "", "url": ""}
            return
        if self._current is None:
            return
        if tag == "h2":
            self._in_heading = True
        elif tag == "cite":
            self._capture = "site_name"
            self._parts = []
        elif tag == "a" and self._in_heading and not self._current["url"]:
            href = attributes.get("href", "").strip()
            if href:
                self._current["url"] = href
                self._capture = "title"
                self._parts = []

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None:
            if tag == "cite" and self._capture == "site_name":
                self._current["site_name"] = self._clean(self._parts)
                self._capture = None
            elif tag == "a" and self._capture == "title":
                self._current["title"] = self._clean(self._parts)
                self._capture = None
            elif tag == "h2":
                self._in_heading = False
            elif tag == "li" and self._result_depth == self._depth:
                if self._current["title"] and self._current["url"]:
                    self.rows.append(self._current)
                self._current = None
                self._result_depth = None
                self._capture = None
                self._parts = []
                self._in_heading = False
        self._depth -= 1

    def handle_data(self, data: str) -> None:
        if self._capture is not None:
            self._parts.append(data)

    @staticmethod
    def _clean(parts: list[str]) -> str:
        return " ".join(unescape("".join(parts)).split())


class BingHtmlSearchProvider:
    """Public Bing HTML search with no credential, cookies, or browser state."""

    code = "bing_html"
    endpoint = "https://www.bing.com/search"
    allowed_domains = ("www.bing.com", "cn.bing.com")
    user_agent = "ArticleReprintMonitor/1.1 (+https://monitor.wiseprop.online)"
    _captcha_pattern = re.compile(
        r"(?:id|class)=[\"'][^\"']*(?:b_captcha|captcha|challenge)[^\"']*[\"']",
        re.IGNORECASE,
    )
    _captcha_text_markers = ("unusual traffic", "verify you are human", "安全验证", "人机验证")

    def __init__(self) -> None:
        self.client = SafeHttpClient(
            allowed_domains=self.allowed_domains,
            timeout_seconds=settings.SEARCH_REQUEST_TIMEOUT_SECONDS,
            max_response_bytes=settings.SEARCH_MAX_RESPONSE_BYTES,
        )

    def search(
        self,
        query: str,
        *,
        freshness_from: object = None,
        freshness_to: object = None,
        limit: int | None = None,
    ) -> list[SearchCandidate]:
        del freshness_from, freshness_to
        requested_limit = min(limit or settings.SEARCH_RESULT_LIMIT, 20)
        url = f"{self.endpoint}?{urlencode({'q': query, 'count': requested_limit})}"
        try:
            response = self.client.get(
                url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "Accept-Language": "zh-CN,zh;q=0.9",
                    "User-Agent": self.user_agent,
                },
            )
        except SafeHttpError as error:
            raise SearchProviderUnavailable("Bing public result page request failed.") from error
        if response.status_code == 429:
            raise SearchProviderCaptchaRequired("Bing public result page rate limited the request.")
        if response.status_code != 200:
            raise SearchProviderUnavailable(f"Bing public result page returned HTTP {response.status_code}.")
        final_host = (urlsplit(response.final_url).hostname or "").lower()
        if final_host not in self.allowed_domains:
            raise SearchProviderUnavailable("Bing public result page redirected away from verified domains.")
        document = response.content.decode("utf-8", errors="replace")
        lowered = document.lower()
        if self._captcha_pattern.search(document) or any(marker in lowered for marker in self._captcha_text_markers):
            raise SearchProviderCaptchaRequired(
                "Bing public result page presented a CAPTCHA or verification challenge."
            )
        parser = _BingResultParser()
        parser.feed(document)
        parser.close()
        if not parser.saw_results_container:
            raise SearchProviderParseError("Bing public result page no longer has the verified result container.")
        if not parser.rows and not parser.saw_no_results:
            raise SearchProviderParseError(
                "Bing public result page has no verified result rows or empty-result marker."
            )
        candidates: list[SearchCandidate] = []
        for row in parser.rows[:requested_limit]:
            url_value = row["url"]
            hostname = (urlsplit(url_value).hostname or "").lower()
            if hostname:
                candidates.append(
                    SearchCandidate(
                        title=row["title"],
                        url=url_value,
                        display_url=url_value,
                        domain=hostname,
                        provider=self.code,
                        site_name=row["site_name"],
                    )
                )
        return candidates
