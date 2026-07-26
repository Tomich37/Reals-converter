from __future__ import annotations

import threading
import time
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.config import Settings
from app.errors import DownloadFailed, DownloadTimedOut, TooManyItems
from app.models import DownloadedMedia, DownloadedPost, InstagramUrl, MediaKind
from app.services.instagram import InstagramDownloader, extract_media_sources


def settings(temp_root: Path) -> Settings:
    return Settings.from_mapping(
        {
            "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456",
            "TEMP_ROOT": str(temp_root),
        }
    )


class FakePost:
    def __init__(self, nodes: list[SimpleNamespace]) -> None:
        self.typename = "GraphSidecar"
        self.mediacount = len(nodes)
        self._nodes = nodes

    def get_sidecar_nodes(self):
        yield from self._nodes


def test_sidecar_order_and_media_types_are_preserved() -> None:
    post = FakePost(
        [
            SimpleNamespace(
                is_video=False,
                display_url="https://cdninstagram.com/one.jpg",
                video_url=None,
            ),
            SimpleNamespace(
                is_video=True,
                display_url="https://cdninstagram.com/two.jpg",
                video_url="https://cdninstagram.com/two.mp4",
            ),
        ]
    )

    sources = extract_media_sources(post, max_items=10)

    assert [source.kind for source in sources] == [MediaKind.PHOTO, MediaKind.VIDEO]
    assert [source.url for source in sources] == [
        "https://cdninstagram.com/one.jpg",
        "https://cdninstagram.com/two.mp4",
    ]


def test_sidecar_larger_than_album_limit_is_rejected() -> None:
    nodes = [
        SimpleNamespace(
            is_video=False,
            display_url=f"https://cdninstagram.com/{index}.jpg",
            video_url=None,
        )
        for index in range(11)
    ]

    with pytest.raises(TooManyItems):
        extract_media_sources(FakePost(nodes), max_items=10)


class SuccessfulWorker:
    def download(
        self,
        instagram_url: InstagramUrl,
        directory: Path,
        cancel_event: threading.Event,
    ) -> DownloadedPost:
        path = directory / "01.jpg"
        path.write_bytes(b"image")
        return DownloadedPost(
            media=(DownloadedMedia(path=path, kind=MediaKind.PHOTO, size=5),),
            caption="Подпись",
            source_url=instagram_url.canonical,
        )


@pytest.mark.asyncio
async def test_temporary_directory_lives_until_context_exit(tmp_path: Path) -> None:
    worker = SuccessfulWorker()
    downloader = InstagramDownloader(settings(tmp_path), worker=worker)
    url = InstagramUrl(
        canonical="https://www.instagram.com/p/Code12345/",
        shortcode="Code12345",
        publication_type="p",
    )

    async with downloader.download(url) as post:
        directory = post.media[0].path.parent
        assert directory.exists()
        assert post.media[0].path.exists()

    assert not directory.exists()


@pytest.mark.asyncio
async def test_context_does_not_replace_sender_error(tmp_path: Path) -> None:
    downloader = InstagramDownloader(settings(tmp_path), worker=SuccessfulWorker())
    url = InstagramUrl(
        canonical="https://www.instagram.com/p/Code12345/",
        shortcode="Code12345",
        publication_type="p",
    )

    with pytest.raises(RuntimeError, match="ошибка отправки"):
        async with downloader.download(url):
            raise RuntimeError("ошибка отправки")


class SlowWorker:
    def download(
        self,
        instagram_url: InstagramUrl,
        directory: Path,
        cancel_event: threading.Event,
    ) -> DownloadedPost:
        time.sleep(2)
        raise DownloadFailed


@pytest.mark.asyncio
async def test_timeout_stops_worker_before_cleanup(tmp_path: Path) -> None:
    short_settings = replace(settings(tmp_path), download_timeout_seconds=0.01)
    downloader = InstagramDownloader(short_settings, worker=SlowWorker())
    url = InstagramUrl(
        canonical="https://www.instagram.com/reel/Code12345/",
        shortcode="Code12345",
        publication_type="reel",
    )

    started = time.monotonic()
    with pytest.raises(DownloadTimedOut):
        async with downloader.download(url):
            pytest.fail("Контекст не должен быть открыт после тайм-аута.")
    assert time.monotonic() - started < 1.5
