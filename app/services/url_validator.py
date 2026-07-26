"""Строгая проверка пользовательских ссылок Instagram."""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from app.errors import InvalidInstagramUrl
from app.models import InstagramUrl

_URL_PATTERN = re.compile(r"https?://[^\s<>\u200b]+", re.IGNORECASE)
_PATH_PATTERN = re.compile(
    r"^/(?P<kind>p|reel|reels)/(?P<shortcode>[A-Za-z0-9_-]{5,64})/?$",
    re.IGNORECASE,
)
_ALLOWED_HOSTS = {"instagram.com", "www.instagram.com"}
_TRAILING_PUNCTUATION = ".,!?;:)]}>\"'»"


def parse_instagram_url(text: str) -> InstagramUrl:
    """Находит ровно одну ссылку и возвращает безопасный канонический адрес."""

    candidates = [
        candidate.rstrip(_TRAILING_PUNCTUATION) for candidate in _URL_PATTERN.findall(text or "")
    ]
    if len(candidates) != 1:
        raise InvalidInstagramUrl

    candidate = candidates[0]
    if len(candidate) > 2048:
        raise InvalidInstagramUrl

    try:
        parts = urlsplit(candidate)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as error:
        raise InvalidInstagramUrl from error

    if (
        parts.scheme.lower() != "https"
        or host not in _ALLOWED_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
        or "http://" in parts.query.lower()
        or "https://" in parts.query.lower()
        or "http://" in parts.fragment.lower()
        or "https://" in parts.fragment.lower()
    ):
        raise InvalidInstagramUrl

    path_match = _PATH_PATTERN.fullmatch(parts.path)
    if path_match is None:
        raise InvalidInstagramUrl

    publication_type = path_match.group("kind").lower()
    if publication_type == "reels":
        publication_type = "reel"
    shortcode = path_match.group("shortcode")
    canonical = f"https://www.instagram.com/{publication_type}/{shortcode}/"

    return InstagramUrl(
        canonical=canonical,
        shortcode=shortcode,
        publication_type=publication_type,
    )
