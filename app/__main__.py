"""Точка входа: настройка зависимостей и запуск long polling."""

from __future__ import annotations

import asyncio
import logging

from aiogram import Bot, Dispatcher
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.types import BotCommand

from app.config import Settings, load_settings
from app.errors import ConfigError
from app.handlers import create_router
from app.services.coordinator import RequestCoordinator
from app.services.instagram import InstagramDownloader
from app.services.media_sender import MediaSender
from app.services.video_compressor import VideoCompressor


async def run_bot(settings: Settings) -> None:
    """Создаёт сервисы и запускает получение сообщений Telegram."""

    session = AiohttpSession(timeout=settings.telegram_request_timeout_seconds)
    bot = Bot(token=settings.bot_token, session=session)
    dispatcher = Dispatcher()

    coordinator = RequestCoordinator(
        max_concurrent=settings.max_concurrent_requests,
        max_pending=settings.max_pending_requests,
        max_requests_per_user_minute=settings.max_requests_per_user_minute,
        max_requests_per_minute=settings.max_requests_per_minute,
    )
    downloader = InstagramDownloader(settings)
    sender = MediaSender(
        VideoCompressor(
            threshold_bytes=settings.video_compression_threshold_bytes,
            crf=settings.video_compression_crf,
            max_width=settings.video_compression_max_width,
        )
    )
    dispatcher.include_router(create_router(downloader, sender, coordinator))

    await bot.set_my_commands(
        [
            BotCommand(command="start", description="Как пользоваться ботом"),
            BotCommand(command="help", description="Поддерживаемые ссылки"),
            BotCommand(command="privacy", description="Обработка данных"),
            BotCommand(command="terms", description="Условия использования"),
            BotCommand(command="report", description="Сообщить о проблеме"),
        ]
    )
    await bot.delete_webhook(drop_pending_updates=False)

    try:
        logging.getLogger(__name__).info("Бот запущен и ожидает ссылки.")
        await dispatcher.start_polling(
            bot,
            allowed_updates=dispatcher.resolve_used_update_types(),
        )
    finally:
        await bot.session.close()


def main() -> None:
    """Читает настройки и запускает асинхронное приложение."""

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
    )
    try:
        settings = load_settings()
    except ConfigError as error:
        raise SystemExit(f"Ошибка конфигурации: {error}") from error

    asyncio.run(run_bot(settings))


if __name__ == "__main__":
    main()
