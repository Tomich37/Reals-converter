"""Telegram-обработчики и перевод доменных ошибок в русские ответы."""

from __future__ import annotations

import logging
import uuid
from contextlib import suppress

from aiogram import F, Router
from aiogram.exceptions import TelegramAPIError
from aiogram.filters import Command, CommandStart
from aiogram.types import Message

from app import texts
from app.errors import (
    AlreadyProcessing,
    AppError,
    ContentUnavailable,
    DownloadFailed,
    DownloadTimedOut,
    FileTooLarge,
    InstagramAccessBlocked,
    InvalidInstagramUrl,
    RateLimited,
    ServiceBusy,
    TooManyItems,
    TotalSizeExceeded,
    UnsupportedMedia,
)
from app.services.coordinator import RequestCoordinator
from app.services.instagram import InstagramDownloader
from app.services.media_sender import MediaSender
from app.services.url_validator import parse_instagram_url

logger = logging.getLogger(__name__)

_ERROR_TEXTS: tuple[tuple[type[AppError], str], ...] = (
    (InstagramAccessBlocked, texts.INSTAGRAM_ACCESS_BLOCKED),
    (ContentUnavailable, texts.CONTENT_UNAVAILABLE),
    (DownloadTimedOut, texts.DOWNLOAD_TIMEOUT),
    (TooManyItems, texts.TOO_MANY_ITEMS),
    (FileTooLarge, texts.FILE_TOO_LARGE),
    (TotalSizeExceeded, texts.TOTAL_SIZE_EXCEEDED),
    (UnsupportedMedia, texts.UNSUPPORTED_MEDIA),
    (DownloadFailed, texts.DOWNLOAD_FAILED),
)


def _text_for_error(error: AppError) -> str:
    for error_type, text in _ERROR_TEXTS:
        if isinstance(error, error_type):
            return text
    return texts.UNEXPECTED_ERROR


async def _replace_status(status: Message, text: str) -> None:
    """Показывает итог в служебном сообщении и имеет безопасный запасной путь."""

    try:
        await status.edit_text(text)
    except TelegramAPIError:
        await status.answer(text)


async def _delete_status(status: Message) -> None:
    with suppress(TelegramAPIError):
        await status.delete()


def create_router(
    downloader: InstagramDownloader,
    sender: MediaSender,
    coordinator: RequestCoordinator,
) -> Router:
    """Собирает маршруты с явно переданными зависимостями."""

    router = Router(name="instagram")

    @router.message(CommandStart())
    async def start_handler(message: Message) -> None:
        await message.answer(texts.START)

    @router.message(Command("help"))
    async def help_handler(message: Message) -> None:
        await message.answer(texts.HELP)

    @router.message(Command("privacy"))
    async def privacy_handler(message: Message) -> None:
        await message.answer(texts.PRIVACY)

    @router.message(Command("terms"))
    async def terms_handler(message: Message) -> None:
        await message.answer(texts.TERMS)

    @router.message(Command("report"))
    async def report_handler(message: Message) -> None:
        await message.answer(texts.REPORT)

    @router.message(F.text)
    async def instagram_handler(message: Message) -> None:
        try:
            instagram_url = parse_instagram_url(message.text or "")
        except InvalidInstagramUrl:
            await message.answer(texts.INVALID_LINK)
            return

        user_id = message.from_user.id if message.from_user else message.chat.id
        request_id = uuid.uuid4().hex[:10]

        try:
            async with coordinator.slot(user_id):
                status = await message.answer(texts.DOWNLOADING)
                try:
                    async with downloader.download(instagram_url) as post:
                        await sender.send(message, post)
                except AppError as error:
                    logger.info(
                        "Запрос %s завершён ожидаемой ошибкой %s.",
                        request_id,
                        type(error).__name__,
                    )
                    await _replace_status(status, _text_for_error(error))
                except TelegramAPIError as error:
                    logger.warning(
                        "Telegram не отправил запрос %s: %s.",
                        request_id,
                        type(error).__name__,
                    )
                    await _replace_status(status, texts.TELEGRAM_ERROR)
                except Exception as error:
                    logger.error(
                        "Неожиданная ошибка запроса %s: %s.",
                        request_id,
                        type(error).__name__,
                    )
                    await _replace_status(status, texts.UNEXPECTED_ERROR)
                else:
                    await _delete_status(status)
        except AlreadyProcessing:
            await message.answer(texts.ALREADY_PROCESSING)
        except ServiceBusy:
            await message.answer(texts.SERVICE_BUSY)
        except RateLimited:
            await message.answer(texts.RATE_LIMITED)

    @router.message()
    async def unsupported_handler(message: Message) -> None:
        await message.answer(texts.SEND_LINK)

    return router
