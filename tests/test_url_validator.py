import pytest

from app.errors import InvalidInstagramUrl
from app.services.url_validator import parse_instagram_url


@pytest.mark.parametrize(
    ("text", "canonical", "shortcode", "publication_type"),
    [
        (
            "https://www.instagram.com/p/AbC_123-xy/?igsh=tracking",
            "https://www.instagram.com/p/AbC_123-xy/",
            "AbC_123-xy",
            "p",
        ),
        (
            "Смотри: https://instagram.com/reel/C0de_12345/.",
            "https://www.instagram.com/reel/C0de_12345/",
            "C0de_12345",
            "reel",
        ),
        (
            "«https://instagram.com/p/C0de_55555/»",
            "https://www.instagram.com/p/C0de_55555/",
            "C0de_55555",
            "p",
        ),
        (
            "https://www.instagram.com/reels/C0de_98765",
            "https://www.instagram.com/reel/C0de_98765/",
            "C0de_98765",
            "reel",
        ),
        (
            "https://www.instagram.com:443/p/Code12345/#fragment",
            "https://www.instagram.com/p/Code12345/",
            "Code12345",
            "p",
        ),
    ],
)
def test_supported_links_are_canonicalized(
    text: str,
    canonical: str,
    shortcode: str,
    publication_type: str,
) -> None:
    result = parse_instagram_url(text)

    assert result.canonical == canonical
    assert result.shortcode == shortcode
    assert result.publication_type == publication_type


@pytest.mark.parametrize(
    "text",
    [
        "",
        "http://www.instagram.com/p/Code12345/",
        "https://instagram.com.evil.example/p/Code12345/",
        "https://evil.example/p/Code12345/",
        "https://user@www.instagram.com/p/Code12345/",
        "https://www.instagram.com:8443/p/Code12345/",
        "https://www.instagram.com/stories/user/123456/",
        "https://www.instagram.com/share/reel/Code12345/",
        "https://www.instagram.com/user/",
        "https://www.instagram.com/p/a/",
        ("https://www.instagram.com/p/Code12345/ https://www.instagram.com/reel/Code67890/"),
        ("http://www.instagram.com/p/Code12345/ https://www.instagram.com/reel/Code67890/"),
        ("https://www.instagram.com/p/Code12345/?next=https://www.instagram.com/reel/Code67890/"),
    ],
)
def test_unsupported_or_ambiguous_links_are_rejected(text: str) -> None:
    with pytest.raises(InvalidInstagramUrl):
        parse_instagram_url(text)
