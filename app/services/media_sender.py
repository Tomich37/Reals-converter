"""Формирование подписей и отправка файлов через aiogram."""

from __future__ import annotations

from pathlib import Path

from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, Message

from app.errors import UnsupportedMedia
from app.models import DownloadedPost, MediaKind
from app.services.video_compressor import VideoCompressor

_CAPTION_LIMIT = 1024


def build_caption(text: str | None, source_url: str, limit: int = _CAPTION_LIMIT) -> str:
    """Добавляет источник и аккуратно обрезает длинную подпись Instagram."""

    clean_text = (text or "").replace("\x00", "").strip()
    source = f"Источник: {source_url}"
    if not clean_text:
        return source[:limit]

    suffix = f"\n\n{source}"
    available = max(0, limit - len(suffix))
    if len(clean_text) > available:
        clean_text = clean_text[: max(0, available - 1)].rstrip() + "…"
    return f"{clean_text}{suffix}"[:limit]


class MediaSender:
    """Отправляет один файл или смешанный альбом в исходный чат."""

    def __init__(self, compressor: VideoCompressor | None = None) -> None:
        self._compressor = compressor

    async def _prepare_path(self, path: Path, kind: MediaKind) -> Path:
        if kind is MediaKind.VIDEO and self._compressor is not None:
            return await self._compressor.compress(path)
        return path

    async def send(self, message: Message, post: DownloadedPost) -> None:
        if not post.media:
            raise UnsupportedMedia

        caption = build_caption(post.caption, post.source_url)

        if len(post.media) == 1:
            item = post.media[0]
            prepared = await self._prepare_path(item.path, item.kind)
            try:
                upload = FSInputFile(prepared)
                if item.kind is MediaKind.PHOTO:
                    await message.answer_photo(photo=upload, caption=caption)
                else:
                    await message.answer_video(
                        video=upload,
                        caption=caption,
                        supports_streaming=True,
                    )
            finally:
                if self._compressor is not None:
                    self._compressor.remove_result(prepared, item.path)
            return

        album: list[InputMediaPhoto | InputMediaVideo] = []
        prepared_items = []
        try:
            for index, item in enumerate(post.media):
                prepared = await self._prepare_path(item.path, item.kind)
                prepared_items.append((prepared, item.path))
                upload = FSInputFile(prepared)
                item_caption = caption if index == 0 else None
                if item.kind is MediaKind.PHOTO:
                    album.append(InputMediaPhoto(media=upload, caption=item_caption))
                else:
                    album.append(
                        InputMediaVideo(
                            media=upload,
                            caption=item_caption,
                            supports_streaming=True,
                        )
                    )

            await message.answer_media_group(media=album)
        finally:
            if self._compressor is not None:
                for prepared, source in prepared_items:
                    self._compressor.remove_result(prepared, source)
