import ipaddress
import socket

import httpx
import pytest

from adapters.safe_http import ResolvedTarget, SafeHttpClient, SafeHttpError, SafeHttpErrorCode


@pytest.fixture
def safe_client() -> SafeHttpClient:
    return SafeHttpClient(allowed_domains=["example.com"], timeout_seconds=5)


@pytest.mark.parametrize(
    "url,code",
    [
        ("ftp://example.com/file", SafeHttpErrorCode.INVALID_URL),
        ("http://127.0.0.1/", SafeHttpErrorCode.DIRECT_IP_NOT_ALLOWED),
        ("http://[::1]/", SafeHttpErrorCode.DIRECT_IP_NOT_ALLOWED),
        ("http://localhost/", SafeHttpErrorCode.DOMAIN_NOT_ALLOWED),
        ("http://mysql/", SafeHttpErrorCode.DOMAIN_NOT_ALLOWED),
        ("http://redis/", SafeHttpErrorCode.DOMAIN_NOT_ALLOWED),
        ("https://not-allowed.example.net/", SafeHttpErrorCode.DOMAIN_NOT_ALLOWED),
        ("https://example.com:8080/", SafeHttpErrorCode.PORT_NOT_ALLOWED),
        ("https://example.com:80/", SafeHttpErrorCode.PORT_NOT_ALLOWED),
    ],
)
def test_safe_http_rejects_invalid_targets(safe_client: SafeHttpClient, url: str, code: SafeHttpErrorCode) -> None:
    with pytest.raises(SafeHttpError) as error:
        safe_client.resolve_and_validate(url)
    assert error.value.code == code


@pytest.mark.parametrize(
    "address",
    [
        "127.0.0.1",
        "10.0.0.1",
        "172.16.0.1",
        "192.168.1.1",
        "169.254.169.254",
        "::1",
        "fc00::1",
        "fe80::1",
    ],
)
def test_safe_http_rejects_internal_ipv4_and_ipv6_dns_results(
    monkeypatch: pytest.MonkeyPatch, safe_client: SafeHttpClient, address: str
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, 443))],
    )
    with pytest.raises(SafeHttpError) as error:
        safe_client.resolve_and_validate("https://example.com/search")
    assert error.value.code == SafeHttpErrorCode.UNSAFE_RESOLVED_IP


def test_safe_http_accepts_only_public_dns_answers(
    monkeypatch: pytest.MonkeyPatch, safe_client: SafeHttpClient
) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("8.8.8.8", 443))],
    )
    target = safe_client.resolve_and_validate("https://example.com/path")
    assert target.hostname == "example.com"
    assert target.port == 443
    assert tuple(str(address) for address in target.addresses) == ("8.8.8.8",)


def test_safe_http_requires_explicit_domain_and_standard_ports() -> None:
    with pytest.raises(ValueError, match="标准端口"):
        SafeHttpClient(allowed_domains=["example.com"], timeout_seconds=5, allowed_ports=frozenset({8080}))

    client = SafeHttpClient(allowed_domains=["example.com"], timeout_seconds=5)
    assert not client._is_allowed_domain("sub.example.com")


class _ClosedClient:
    def close(self) -> None:
        pass


def test_safe_http_detects_dns_rebinding_after_pinned_response(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SafeHttpClient(allowed_domains=["example.com"], timeout_seconds=5)
    targets = iter(
        [
            ResolvedTarget("example.com", 443, (ipaddress.ip_address("8.8.8.8"),)),
            ResolvedTarget("example.com", 443, (ipaddress.ip_address("1.1.1.1"),)),
        ]
    )
    monkeypatch.setattr(client, "resolve_and_validate", lambda url: next(targets))
    monkeypatch.setattr(
        client,
        "_get_pinned",
        lambda url, target, headers: (httpx.Response(200, content=b"ok"), _ClosedClient()),
    )

    with pytest.raises(SafeHttpError) as error:
        client.get("https://example.com/article")
    assert error.value.code == SafeHttpErrorCode.DNS_REBINDING_DETECTED


def test_safe_http_enforces_response_size_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    client = SafeHttpClient(allowed_domains=["example.com"], timeout_seconds=5, max_response_bytes=1)
    target = ResolvedTarget("example.com", 443, (ipaddress.ip_address("8.8.8.8"),))
    monkeypatch.setattr(client, "resolve_and_validate", lambda url: target)
    monkeypatch.setattr(
        client,
        "_get_pinned",
        lambda url, target, headers: (httpx.Response(200, content=b"too large"), _ClosedClient()),
    )

    with pytest.raises(SafeHttpError) as error:
        client.get("https://example.com/article")
    assert error.value.code == SafeHttpErrorCode.RESPONSE_TOO_LARGE
