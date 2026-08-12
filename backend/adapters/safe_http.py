"""Pinned, allow-listed HTTP client for every external platform adapter."""

from __future__ import annotations

import ipaddress
import logging
import socket
from collections.abc import Iterable
from dataclasses import dataclass
from enum import StrEnum
from urllib.parse import urljoin, urlsplit

import httpx

logger = logging.getLogger(__name__)

DEFAULT_ALLOWED_PORTS = frozenset({80, 443})
DEFAULT_MAX_REDIRECTS = 5
DEFAULT_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


class SafeHttpErrorCode(StrEnum):
    INVALID_URL = "INVALID_URL"
    DOMAIN_NOT_ALLOWED = "DOMAIN_NOT_ALLOWED"
    DIRECT_IP_NOT_ALLOWED = "DIRECT_IP_NOT_ALLOWED"
    PORT_NOT_ALLOWED = "PORT_NOT_ALLOWED"
    DNS_RESOLUTION_FAILED = "DNS_RESOLUTION_FAILED"
    UNSAFE_RESOLVED_IP = "UNSAFE_RESOLVED_IP"
    DNS_REBINDING_DETECTED = "DNS_REBINDING_DETECTED"
    TOO_MANY_REDIRECTS = "TOO_MANY_REDIRECTS"
    RESPONSE_TOO_LARGE = "RESPONSE_TOO_LARGE"
    REQUEST_FAILED = "REQUEST_FAILED"


class SafeHttpError(RuntimeError):
    def __init__(self, code: SafeHttpErrorCode, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class ResolvedTarget:
    hostname: str
    port: int
    addresses: tuple[ipaddress.IPv4Address | ipaddress.IPv6Address, ...]


@dataclass(frozen=True)
class SafeHttpResponse:
    requested_url: str
    final_url: str
    status_code: int
    headers: dict[str, str]
    content: bytes
    redirects: tuple[str, ...]
    resolved_addresses: tuple[str, ...]


class SafeHttpClient:
    """External HTTP client with SSRF and DNS-rebinding controls.

    Every request and redirect is resolved and validated. Connections use a
    validated IP while HTTPS retains the original hostname as SNI, preventing a
    later DNS lookup from redirecting the connection to an internal address.
    """

    def __init__(
        self,
        *,
        allowed_domains: Iterable[str],
        timeout_seconds: float,
        max_response_bytes: int = DEFAULT_MAX_RESPONSE_BYTES,
        max_redirects: int = DEFAULT_MAX_REDIRECTS,
        allowed_ports: frozenset[int] = DEFAULT_ALLOWED_PORTS,
    ) -> None:
        self.allowed_domains = frozenset(self._normalize_domain(value) for value in allowed_domains)
        self.timeout_seconds = timeout_seconds
        self.max_response_bytes = max_response_bytes
        self.max_redirects = max_redirects
        if not allowed_ports.issubset(DEFAULT_ALLOWED_PORTS):
            raise ValueError("安全 HTTP 客户端不允许放开 HTTP/HTTPS 标准端口以外的端口。")
        self.allowed_ports = allowed_ports
        if not self.allowed_domains:
            raise ValueError("安全 HTTP 客户端必须配置至少一个平台域名白名单。")
        if timeout_seconds <= 0 or max_response_bytes <= 0 or max_redirects < 0:
            raise ValueError("超时、响应大小和重定向限制必须为有效值。")

    @staticmethod
    def _normalize_domain(value: str) -> str:
        return value.strip().lower().rstrip(".")

    def _is_allowed_domain(self, hostname: str) -> bool:
        return hostname in self.allowed_domains

    @staticmethod
    def _is_public_address(value: ipaddress.IPv4Address | ipaddress.IPv6Address) -> bool:
        return value.is_global and not value.is_multicast and not value.is_unspecified

    def resolve_and_validate(self, url: str) -> ResolvedTarget:
        parsed = urlsplit(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            raise SafeHttpError(SafeHttpErrorCode.INVALID_URL, "仅允许无凭据的绝对 HTTP(S) URL。")
        hostname = self._normalize_domain(parsed.hostname)
        try:
            ipaddress.ip_address(hostname)
        except ValueError:
            pass
        else:
            raise SafeHttpError(SafeHttpErrorCode.DIRECT_IP_NOT_ALLOWED, "不允许直接使用 IP 地址作为目标。")
        if hostname == "localhost" or not self._is_allowed_domain(hostname):
            raise SafeHttpError(SafeHttpErrorCode.DOMAIN_NOT_ALLOWED, "目标不在平台域名白名单中。")
        default_port = 443 if parsed.scheme == "https" else 80
        port = parsed.port or default_port
        if port != default_port or port not in self.allowed_ports:
            raise SafeHttpError(SafeHttpErrorCode.PORT_NOT_ALLOWED, "仅允许平台的 HTTP/HTTPS 标准端口。")
        try:
            records = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
        except socket.gaierror as error:
            raise SafeHttpError(SafeHttpErrorCode.DNS_RESOLUTION_FAILED, "平台域名 DNS 解析失败。") from error
        addresses = tuple(dict.fromkeys(ipaddress.ip_address(record[4][0]) for record in records))
        if not addresses:
            raise SafeHttpError(SafeHttpErrorCode.DNS_RESOLUTION_FAILED, "平台域名未解析到可用地址。")
        if any(not self._is_public_address(address) for address in addresses):
            raise SafeHttpError(SafeHttpErrorCode.UNSAFE_RESOLVED_IP, "DNS 解析结果含内网、回环、保留或链路本地地址。")
        return ResolvedTarget(hostname=hostname, port=port, addresses=addresses)

    def get(self, url: str, *, headers: dict[str, str] | None = None) -> SafeHttpResponse:
        return self.request("GET", url, headers=headers)

    def post(
        self, url: str, *, headers: dict[str, str] | None = None, content: bytes | None = None
    ) -> SafeHttpResponse:
        return self.request("POST", url, headers=headers, content=content)

    def request(
        self,
        method: str,
        url: str,
        *,
        headers: dict[str, str] | None = None,
        content: bytes | None = None,
    ) -> SafeHttpResponse:
        normalized_method = method.upper()
        if normalized_method not in {"GET", "POST"}:
            raise ValueError("Only GET and POST requests are supported by the safe HTTP client.")
        requested_url = url
        current_url = url
        redirects: list[str] = []
        for _ in range(self.max_redirects + 1):
            target = self.resolve_and_validate(current_url)
            if normalized_method == "GET":
                response, client = self._get_pinned(current_url, target, headers=headers)
            else:
                response, client = self._request_pinned(
                    normalized_method,
                    current_url,
                    target,
                    headers=headers,
                    content=content,
                )
            try:
                if response.is_redirect:
                    location = response.headers.get("location")
                    if not location:
                        raise SafeHttpError(SafeHttpErrorCode.REQUEST_FAILED, "重定向响应缺少 Location。")
                    if len(redirects) >= self.max_redirects:
                        raise SafeHttpError(SafeHttpErrorCode.TOO_MANY_REDIRECTS, "重定向次数超过上限。")
                    current_url = urljoin(current_url, location)
                    redirects.append(current_url)
                    continue
                content = self._read_limited(response)
                final_target = self.resolve_and_validate(current_url)
                if set(final_target.addresses).isdisjoint(target.addresses):
                    raise SafeHttpError(SafeHttpErrorCode.DNS_REBINDING_DETECTED, "请求期间检测到 DNS 地址变化。")
                self._log_request(requested_url, current_url, response.status_code)
                return SafeHttpResponse(
                    requested_url=requested_url,
                    final_url=current_url,
                    status_code=response.status_code,
                    headers={key.lower(): value for key, value in response.headers.items()},
                    content=content,
                    redirects=tuple(redirects),
                    resolved_addresses=tuple(str(address) for address in target.addresses),
                )
            finally:
                response.close()
                client.close()
        raise SafeHttpError(SafeHttpErrorCode.TOO_MANY_REDIRECTS, "重定向次数超过上限。")

    def _request_pinned(
        self,
        method: str,
        url: str,
        target: ResolvedTarget,
        *,
        headers: dict[str, str] | None,
        content: bytes | None,
    ) -> tuple[httpx.Response, httpx.Client]:
        parsed = httpx.URL(url)
        pinned_url = parsed.copy_with(host=str(target.addresses[0]), port=target.port)
        request_headers = {key: value for key, value in (headers or {}).items() if key.lower() != "host"}
        request_headers["Host"] = target.hostname
        request = httpx.Request(
            method,
            pinned_url,
            headers=request_headers,
            content=content,
            extensions={"sni_hostname": target.hostname},
        )
        try:
            client = httpx.Client(timeout=httpx.Timeout(self.timeout_seconds), follow_redirects=False, trust_env=False)
            return client.send(request, stream=True), client
        except httpx.HTTPError as error:
            raise SafeHttpError(SafeHttpErrorCode.REQUEST_FAILED, "平台请求失败。") from error

    def _get_pinned(
        self, url: str, target: ResolvedTarget, *, headers: dict[str, str] | None
    ) -> tuple[httpx.Response, httpx.Client]:
        return self._request_pinned("GET", url, target, headers=headers, content=None)

    def _read_limited(self, response: httpx.Response) -> bytes:
        chunks: list[bytes] = []
        total = 0
        try:
            for chunk in response.iter_bytes():
                total += len(chunk)
                if total > self.max_response_bytes:
                    raise SafeHttpError(SafeHttpErrorCode.RESPONSE_TOO_LARGE, "平台响应超过安全大小限制。")
                chunks.append(chunk)
            return b"".join(chunks)
        finally:
            response.close()

    @staticmethod
    def _log_request(requested_url: str, final_url: str, status_code: int) -> None:
        requested = urlsplit(requested_url)
        final = urlsplit(final_url)
        logger.info(
            "safe_external_request requested=%s://%s%s final=%s://%s%s status=%s",
            requested.scheme,
            requested.hostname,
            requested.path,
            final.scheme,
            final.hostname,
            final.path,
            status_code,
        )
