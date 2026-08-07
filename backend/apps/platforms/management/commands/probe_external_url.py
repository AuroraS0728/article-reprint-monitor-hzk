"""Safely probe one supplied public URL without persisting business data."""

from __future__ import annotations

import hashlib
import json
from html import unescape
from html.parser import HTMLParser
from typing import cast
from urllib.parse import urlsplit

from django.core.management.base import BaseCommand, CommandError, CommandParser

from adapters.safe_http import SafeHttpClient, SafeHttpError
from apps.articles.services import normalize_title


class _TitleParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.in_title = False
        self.parts: list[str] = []
        self.metadata: dict[str, str] = {}
        self.time_values: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attributes = {key.lower(): value for key, value in attrs if value is not None}
        if tag.lower() == "title":
            self.in_title = True
        if tag.lower() == "meta":
            key = (attributes.get("property") or attributes.get("name") or "").lower()
            if key in {
                "og:title",
                "og:url",
                "article:published_time",
                "article:modified_time",
                "publishdate",
                "pubdate",
                "date",
                "author",
            } and attributes.get("content"):
                self.metadata[key] = attributes["content"]
        if tag.lower() == "link" and attributes.get("rel", "").lower() == "canonical" and attributes.get("href"):
            self.metadata["canonical"] = attributes["href"]
        if tag.lower() == "time" and attributes.get("datetime"):
            self.time_values.append(attributes["datetime"])

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "title":
            self.in_title = False

    def handle_data(self, data: str) -> None:
        if self.in_title:
            self.parts.append(data)

    @property
    def title(self) -> str:
        return unescape("".join(self.parts)).strip()


class Command(BaseCommand):
    help = "Safely retrieve one explicit public URL for manual validation; it never writes platform or article data."

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("--url", required=True, help="Explicit URL to validate.")
        parser.add_argument(
            "--allowed-domain", action="append", required=True, help="Approved platform domain; may repeat."
        )
        parser.add_argument("--expected-title", help="Optional expected title for a manual validation comparison.")
        parser.add_argument("--timeout", type=float, default=15, help="Request timeout in seconds.")

    def handle(self, *args: object, **options: object) -> None:
        url = str(options["url"])
        expected_title = str(options.get("expected_title") or "")
        allowed_domains = cast(list[str], options["allowed_domain"])
        try:
            response = SafeHttpClient(
                allowed_domains=allowed_domains,
                timeout_seconds=cast(float, options["timeout"]),
            ).get(url)
        except SafeHttpError as error:
            raise CommandError(f"安全请求被拒绝或失败：{error.code}") from error

        parser = _TitleParser()
        parser.feed(response.content.decode("utf-8", errors="replace"))
        requested = urlsplit(response.requested_url)
        final = urlsplit(response.final_url)
        payload = {
            "request_success": True,
            "requested": f"{requested.scheme}://{requested.hostname}{requested.path}",
            "final": f"{final.scheme}://{final.hostname}{final.path}",
            "status_code": response.status_code,
            "content_sha256": hashlib.sha256(response.content).hexdigest(),
            "content_bytes": len(response.content),
            "html_title": parser.title,
            "document_metadata": parser.metadata,
            "time_elements": parser.time_values,
            "title_exact_match": (
                normalize_title(parser.title) == normalize_title(expected_title) if expected_title else None
            ),
            "classification": "UNSPECIFIED_TEST_DATA",
        }
        self.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2))
