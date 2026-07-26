from __future__ import annotations

import socket
import threading
from dataclasses import replace
from pathlib import Path

import pytest

import app.services.instagram as instagram_service
from app.config import Settings
from app.errors import FileTooLarge, UnsupportedMedia
from app.models import InstagramUrl, MediaKind, RemoteMedia
from app.services.instagram import KKInstagramWorker


def settings() -> Settings:
    return Settings.from_mapping({"BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"})


class FakeResponse:
    def __init__(
        self,
        *,
        status_code: int = 200,
        content_type: str = "image/jpeg",
        content_length: int | None = None,
        location: str | None = None,
        chunks: tuple[bytes, ...] = (b"image",),
        url: str = "https://cdninstagram.com/media",
    ) -> None:
        self.status_code = status_code
        self.url = url
        self.headers = {"Content-Type": content_type}
        if content_length is not None:
            self.headers["Content-Length"] = str(content_length)
        if location is not None:
            self.headers["Location"] = location
        self._chunks = chunks
        self.closed = False

    def raise_for_status(self) -> None:
        return None

    def iter_content(self, chunk_size: int):
        del chunk_size
        yield from self._chunks

    def close(self) -> None:
        self.closed = True


class FakeSession:
    def __init__(self, response: FakeResponse) -> None:
        self.response = response
        self.calls = 0

    def get(self, *args, **kwargs) -> FakeResponse:
        del args, kwargs
        self.calls += 1
        return self.response


class SequencedSession:
    def __init__(self, *responses: FakeResponse) -> None:
        self.responses = list(responses)
        self.requests: list[tuple[str, dict[str, object]]] = []
        self.closed = False

    def get(self, url: str, **kwargs) -> FakeResponse:
        self.requests.append((url, kwargs))
        return self.responses.pop(0)

    def close(self) -> None:
        self.closed = True


def download_photo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse,
    *,
    worker_settings: Settings | None = None,
) -> None:
    monkeypatch.setattr(instagram_service, "_ensure_public_address", lambda host: None)
    worker = KKInstagramWorker(worker_settings or settings())
    worker._download_source(
        session=FakeSession(response),
        source=RemoteMedia(
            url="https://cdninstagram.com/media",
            kind=MediaKind.PHOTO,
        ),
        directory=tmp_path,
        index=1,
        current_total=0,
        cancel_event=threading.Event(),
    )


def test_private_dns_address_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        socket,
        "getaddrinfo",
        lambda *args, **kwargs: [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("127.0.0.1", 443))],
    )

    with pytest.raises(UnsupportedMedia):
        instagram_service._validate_remote_url("https://cdninstagram.com/media")


def test_similar_but_foreign_domain_is_rejected() -> None:
    with pytest.raises(UnsupportedMedia):
        instagram_service._validate_remote_url("https://cdninstagram.com.evil.example/media")


def test_similar_kkinstagram_domain_is_rejected() -> None:
    with pytest.raises(UnsupportedMedia):
        instagram_service._validate_kkinstagram_url(
            "https://www.kkinstagram.com.evil.example/reel/Code12345/"
        )


def test_kkinstagram_resolver_follows_only_checked_redirects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(instagram_service, "_ensure_public_address", lambda host: None)
    session = SequencedSession(
        FakeResponse(
            status_code=302,
            location="https://cdninstagram.com/video.mp4",
            url="https://www.kkinstagram.com/reel/Code12345/",
        ),
        FakeResponse(
            content_type="video/mp4",
            url="https://cdninstagram.com/video.mp4",
        ),
    )
    worker = KKInstagramWorker(settings())
    instagram_url = InstagramUrl(
        canonical="https://www.instagram.com/reel/Code12345/",
        shortcode="Code12345",
        publication_type="reel",
    )

    source = worker._resolve_kkinstagram_source(
        session,
        instagram_url,
        threading.Event(),
    )

    assert source == RemoteMedia(
        url="https://cdninstagram.com/video.mp4",
        kind=MediaKind.VIDEO,
    )
    assert [request[0] for request in session.requests] == [
        "https://www.kkinstagram.com/reel/Code12345/",
        "https://cdninstagram.com/video.mp4",
    ]
    assert session.requests[0][1]["allow_redirects"] is False
    assert session.requests[0][1]["headers"] == {"User-Agent": "TelegramBot (like TwitterBot)"}


def test_worker_downloads_only_through_kkinstagram(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(instagram_service, "_ensure_public_address", lambda host: None)
    session = SequencedSession(
        FakeResponse(
            status_code=302,
            location="https://cdninstagram.com/video.mp4",
            url="https://www.kkinstagram.com/reel/Code12345/",
        ),
        FakeResponse(
            content_type="video/mp4",
            url="https://cdninstagram.com/video.mp4",
        ),
        FakeResponse(
            content_type="video/mp4",
            chunks=(b"video",),
            url="https://cdninstagram.com/video.mp4",
        ),
    )
    monkeypatch.setattr(instagram_service.requests, "Session", lambda: session)
    worker = KKInstagramWorker(settings())
    instagram_url = InstagramUrl(
        canonical="https://www.instagram.com/reel/Code12345/",
        shortcode="Code12345",
        publication_type="reel",
    )

    post = worker.download(instagram_url, tmp_path, threading.Event())

    assert len(post.media) == 1
    assert post.media[0].kind is MediaKind.VIDEO
    assert post.media[0].path.read_bytes() == b"video"
    assert post.caption == instagram_service.texts.KKINSTAGRAM_CAPTION
    assert session.closed
    assert [request[0] for request in session.requests] == [
        "https://www.kkinstagram.com/reel/Code12345/",
        "https://cdninstagram.com/video.mp4",
        "https://cdninstagram.com/video.mp4",
    ]


def test_kkinstagram_resolver_rejects_foreign_redirect_before_request(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(instagram_service, "_ensure_public_address", lambda host: None)
    session = SequencedSession(
        FakeResponse(
            status_code=302,
            location="https://evil.example/video.mp4",
            url="https://www.kkinstagram.com/reel/Code12345/",
        )
    )
    worker = KKInstagramWorker(settings())
    instagram_url = InstagramUrl(
        canonical="https://www.instagram.com/reel/Code12345/",
        shortcode="Code12345",
        publication_type="reel",
    )

    with pytest.raises(UnsupportedMedia):
        worker._resolve_kkinstagram_source(
            session,
            instagram_url,
            threading.Event(),
        )

    assert len(session.requests) == 1


def test_declared_file_size_is_checked_before_download(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(content_length=9_500_001)

    with pytest.raises(FileTooLarge):
        download_photo(tmp_path, monkeypatch, response)

    assert response.closed


def test_streamed_file_size_is_checked_while_downloading(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    small_limit = replace(settings(), max_photo_bytes=5)
    response = FakeResponse(chunks=(b"123", b"456"))

    with pytest.raises(FileTooLarge):
        download_photo(
            tmp_path,
            monkeypatch,
            response,
            worker_settings=small_limit,
        )

    assert response.closed


def test_unexpected_mime_type_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    response = FakeResponse(content_type="application/pdf")

    with pytest.raises(UnsupportedMedia):
        download_photo(tmp_path, monkeypatch, response)


def test_redirect_to_foreign_domain_is_rejected(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(instagram_service, "_ensure_public_address", lambda host: None)
    response = FakeResponse(
        status_code=302,
        location="https://evil.example/media.jpg",
    )
    session = FakeSession(response)
    worker = KKInstagramWorker(settings())

    with pytest.raises(UnsupportedMedia):
        worker._download_source(
            session=session,
            source=RemoteMedia(
                url="https://cdninstagram.com/media",
                kind=MediaKind.PHOTO,
            ),
            directory=tmp_path,
            index=1,
            current_total=0,
            cancel_event=threading.Event(),
        )

    assert session.calls == 1
