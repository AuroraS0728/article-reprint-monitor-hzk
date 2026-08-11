from __future__ import annotations

from django.conf import settings

from .base import SearchProvider
from .exceptions import SearchProviderNotConfigured
from .providers.brave import BraveSearchProvider


def configured_search_provider() -> SearchProvider:
    provider = settings.SEARCH_PROVIDER.strip().lower()
    if not provider:
        raise SearchProviderNotConfigured("未配置 SEARCH_PROVIDER。")
    if provider == "brave":
        if not settings.BRAVE_SEARCH_API_KEY:
            raise SearchProviderNotConfigured("未配置 BRAVE_SEARCH_API_KEY。")
        return BraveSearchProvider()
    raise SearchProviderNotConfigured(f"不支持的 SEARCH_PROVIDER：{provider}")
