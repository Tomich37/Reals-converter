from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from app.errors import UnsupportedMedia
from app.models import DownloadedMedia, DownloadedPost, MediaKind
from app.services.media_sender import MediaSender, build_caption


def test_caption_is_limited_and_keeps_source() -> None:
    source = "https://www.instagram.com/p/Code12345/"

    caption = build_caption("Я" * 2_000, source)

    assert len(caption) <= 1024
    assert caption.endswith(f"Источник: {source}")


@pytest.mark.asyncio
async def test_empty_publication_is_rejected() -> None:
    message = AsyncMock()
    post = DownloadedPost(
        media=(),
        caption=None,
        source_url="https://www.instagram.com/p/Code12345/",
    )

    with pytest.raises(UnsupportedMedia):
        await MediaSender().send(message, post)


@pytest.mark.asyncio
async def test_single_photo_is_sent_as_photo(tmp_path: Path) -> None:
    path = tmp_path / "01.jpg"
    path.write_bytes(b"image")
    message = AsyncMock()
    post = DownloadedPost(
        media=(DownloadedMedia(path=path, kind=MediaKind.PHOTO, size=5),),
        caption="Подпись",
        source_url="https://www.instagram.com/p/Code12345/",
    )

    await MediaSender().send(message, post)

    message.answer_photo.assert_awaited_once()
    message.answer_video.assert_not_awaited()
    message.answer_media_group.assert_not_awaited()


@pytest.mark.asyncio
async def test_mixed_carousel_is_sent_as_one_album(tmp_path: Path) -> None:
    photo = tmp_path / "01.jpg"
    video = tmp_path / "02.mp4"
    photo.write_bytes(b"image")
    video.write_bytes(b"video")
    message = AsyncMock()
    post = DownloadedPost(
        media=(
            DownloadedMedia(path=photo, kind=MediaKind.PHOTO, size=5),
            DownloadedMedia(path=video, kind=MediaKind.VIDEO, size=5),
        ),
        caption="Подпись",
        source_url="https://www.instagram.com/p/Code12345/",
    )

    await MediaSender().send(message, post)

    message.answer_media_group.assert_awaited_once()
    album = message.answer_media_group.await_args.kwargs["media"]
    assert len(album) == 2
    assert album[0].caption is not None
    assert album[1].caption is None
