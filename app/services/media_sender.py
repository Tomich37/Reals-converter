"""Формирование подписей и отправка файлов через aiogram."""

from __future__ import annotations

from aiogram.types import FSInputFile, InputMediaPhoto, InputMediaVideo, Message

from app.errors import UnsupportedMedia
from app.models import DownloadedPost, MediaKind

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

    async def send(self, message: Message, post: DownloadedPost) -> None:
        if not post.media:
            raise UnsupportedMedia

        caption = build_caption(post.caption, post.source_url)

        if len(post.media) == 1:
            item = post.media[0]
            upload = FSInputFile(item.path)
            if item.kind is MediaKind.PHOTO:
                await message.answer_photo(photo=upload, caption=caption)
            else:
                await message.answer_video(
                    video=upload,
                    caption=caption,
                    supports_streaming=True,
                )
            return

        album: list[InputMediaPhoto | InputMediaVideo] = []
        for index, item in enumerate(post.media):
            upload = FSInputFile(item.path)
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
