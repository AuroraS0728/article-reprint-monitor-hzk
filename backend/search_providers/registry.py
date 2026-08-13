from __future__ import annotations

from django.conf import settings

from .base import SearchProvider
from .exceptions import SearchProviderNotConfigured
from .providers.brave import BraveSearchProvider
from .providers.tencent_wsa import TencentWsaSearchProvider

SUPPORTED_PROVIDER_CODES = ("tencent_wsa", "brave")


def search_provider_for_code(provider_code: str) -> SearchProvider:
    """Return only a provider with a real, configured official API credential."""

    provider = provider_code.strip().lower()
    if provider == "brave":
        if not settings.BRAVE_SEARCH_API_KEY:
            raise SearchProviderNotConfigured("未配置 BRAVE_SEARCH_API_KEY。")
        return BraveSearchProvider()
    if provider == "tencent_wsa":
        if not settings.TENCENTCLOUD_WSA_APIKEY:
            raise SearchProviderNotConfigured("Tencent Cloud WSA API key is not configured.")
        return TencentWsaSearchProvider()
    raise SearchProviderNotConfigured(f"不支持的 SEARCH_PROVIDER：{provider}")


def configured_search_provider() -> SearchProvider:
    provider = settings.SEARCH_PROVIDER.strip().lower()
    if not provider:
        raise SearchProviderNotConfigured("未配置 SEARCH_PROVIDER。")
    return search_provider_for_code(provider)
