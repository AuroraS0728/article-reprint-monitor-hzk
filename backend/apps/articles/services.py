import html
import re
import unicodedata
from collections.abc import Iterable
from typing import Final

TITLE_TRANSLATION: Final[dict[str, str | int | None]] = {"“": '"', "”": '"', "‘": "'", "’": "'", "，": ",", "：": ":"}


def normalize_title(value: str, confirmed_suffixes: Iterable[str] = ()) -> str:
    normalized = unicodedata.normalize("NFKC", html.unescape(value)).strip()
    normalized = re.sub(r"\s+", " ", normalized)
    normalized = normalized.translate(str.maketrans(TITLE_TRANSLATION))
    for suffix in confirmed_suffixes:
        suffix_value = suffix.strip()
        if not suffix_value:
            continue
        for marker in (
            suffix_value,
            f" - {suffix_value}",
            f" _ {suffix_value}",
            f"_{suffix_value}",
            f"（{suffix_value}）",
            f"({suffix_value})",
        ):
            if normalized.endswith(marker):
                normalized = normalized[: -len(marker)].rstrip(" _-*")
                break
    return normalized
