from __future__ import annotations

import socket
import threading
from dataclasses import replace
from pathlib import Path

import pytest

import app.services.instagram as instagram_service
from app.config import Settings
from app.errors import FileTooLarge, UnsupportedMedia
from app.models import MediaKind, RemoteMedia
from app.services.instagram import InstaloaderWorker


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
    ) -> None:
        self.status_code = status_code
        self.url = "https://cdninstagram.com/media"
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


def download_photo(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    response: FakeResponse,
    *,
    worker_settings: Settings | None = None,
) -> None:
    monkeypatch.setattr(instagram_service, "_ensure_public_address", lambda host: None)
    worker = InstaloaderWorker(worker_settings or settings())
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
    worker = InstaloaderWorker(settings())

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
