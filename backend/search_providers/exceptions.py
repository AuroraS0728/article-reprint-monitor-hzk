from __future__ import annotations


class SearchProviderError(RuntimeError):
    code = "SEARCH_PROVIDER_ERROR"


class SearchProviderNotConfigured(SearchProviderError):
    code = "SEARCH_PROVIDER_NOT_CONFIGURED"


class SearchProviderRateLimited(SearchProviderError):
    code = "SEARCH_PROVIDER_RATE_LIMITED"


class SearchProviderUnavailable(SearchProviderError):
    code = "SEARCH_PROVIDER_UNAVAILABLE"


class SearchProviderCaptchaRequired(SearchProviderError):
    """The provider presented a CAPTCHA or anti-automation challenge."""

    code = "SEARCH_PROVIDER_CAPTCHA_REQUIRED"


class SearchProviderLoginRequired(SearchProviderError):
    """The provider redirected to or rendered a sign-in requirement."""

    code = "SEARCH_PROVIDER_LOGIN_REQUIRED"


class SearchProviderParseError(SearchProviderError):
    """The public search page no longer has a verified result structure."""

    code = "SEARCH_PROVIDER_PARSE_ERROR"
