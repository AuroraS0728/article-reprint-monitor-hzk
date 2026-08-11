from __future__ import annotations


class SearchProviderError(RuntimeError):
    code = "SEARCH_PROVIDER_ERROR"


class SearchProviderNotConfigured(SearchProviderError):
    code = "SEARCH_PROVIDER_NOT_CONFIGURED"


class SearchProviderRateLimited(SearchProviderError):
    code = "SEARCH_PROVIDER_RATE_LIMITED"


class SearchProviderUnavailable(SearchProviderError):
    code = "SEARCH_PROVIDER_UNAVAILABLE"
