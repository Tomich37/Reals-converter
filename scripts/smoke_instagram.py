"""Ручная сетевая проверка загрузчика без запуска Telegram-бота."""

from __future__ import annotations

import asyncio
import sys

from app.config import Settings
from app.errors import AppError
from app.services.instagram import InstagramDownloader
from app.services.url_validator import parse_instagram_url


async def check(raw_url: str) -> None:
    """Скачивает публикацию во временный каталог и выводит только сводку."""

    settings = Settings.from_mapping(
        {
            "BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456",
            "DOWNLOAD_TIMEOUT_SECONDS": "60",
            "MEDIA_REQUEST_TIMEOUT_SECONDS": "20",
        }
    )
    downloader = InstagramDownloader(settings)
    instagram_url = parse_instagram_url(raw_url)

    async with downloader.download(instagram_url) as post:
        print(f"Получено медиафайлов: {len(post.media)}")
        for index, item in enumerate(post.media, start=1):
            print(f"{index}: {item.kind.value}, {item.size} байт")


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Использование: python scripts/smoke_instagram.py <ссылка>")

    try:
        asyncio.run(check(sys.argv[1]))
    except AppError as error:
        raise SystemExit(f"Проверка не пройдена: {type(error).__name__}") from error


if __name__ == "__main__":
    main()
