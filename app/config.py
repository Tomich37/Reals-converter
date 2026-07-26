"""Загрузка и проверка настроек из переменных окружения и файла .env."""

from __future__ import annotations

import os
import re
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from dotenv import dotenv_values

from app.errors import ConfigError


def _string_value(values: Mapping[str, object], name: str, default: str = "") -> str:
    value = values.get(name, default)
    return str(value).strip() if value is not None else default


def _integer_value(
    values: Mapping[str, object],
    name: str,
    default: int,
    *,
    minimum: int,
    maximum: int,
) -> int:
    raw_value = _string_value(values, name, str(default))
    try:
        value = int(raw_value)
    except ValueError as error:
        raise ConfigError(f"{name} должен быть целым числом.") from error

    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} должен быть от {minimum} до {maximum}.")
    return value


def _float_value(
    values: Mapping[str, object],
    name: str,
    default: float,
    *,
    minimum: float,
    maximum: float,
) -> float:
    raw_value = _string_value(values, name, str(default))
    try:
        value = float(raw_value)
    except ValueError as error:
        raise ConfigError(f"{name} должен быть числом.") from error

    if not minimum <= value <= maximum:
        raise ConfigError(f"{name} должен быть от {minimum:g} до {maximum:g}.")
    return value


def _boolean_value(
    values: Mapping[str, object],
    name: str,
    default: bool,
) -> bool:
    """Читает логическую настройку в привычном для .env формате."""

    raw_value = _string_value(values, name, str(default)).lower()
    if raw_value in {"1", "true", "yes", "on"}:
        return True
    if raw_value in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} должен быть true или false.")


@dataclass(frozen=True, slots=True)
class Settings:
    """Проверенные настройки приложения."""

    bot_token: str
    max_media_items: int
    max_photo_bytes: int
    max_video_bytes: int
    max_total_bytes: int
    download_timeout_seconds: float
    media_request_timeout_seconds: float
    telegram_request_timeout_seconds: float
    max_concurrent_requests: int
    max_pending_requests: int
    max_requests_per_user_minute: int
    max_requests_per_minute: int
    kkinstagram_fallback_enabled: bool
    temp_root: Path | None

    @classmethod
    def from_mapping(cls, values: Mapping[str, object]) -> Settings:
        """Создаёт настройки из словаря и выдаёт понятные ошибки."""

        bot_token = _string_value(values, "BOT_TOKEN")
        if not bot_token:
            raise ConfigError("В .env не задан BOT_TOKEN.")
        if re.fullmatch(r"\d{5,20}:[A-Za-z0-9_-]{20,}", bot_token) is None:
            raise ConfigError("BOT_TOKEN имеет неверный формат.")

        temp_root_value = _string_value(values, "TEMP_ROOT")
        temp_root = Path(temp_root_value).expanduser().resolve() if temp_root_value else None

        return cls(
            bot_token=bot_token,
            max_media_items=_integer_value(
                values,
                "MAX_MEDIA_ITEMS",
                10,
                minimum=1,
                maximum=10,
            ),
            max_photo_bytes=_integer_value(
                values,
                "MAX_PHOTO_BYTES",
                9_500_000,
                minimum=1_000_000,
                maximum=10_000_000,
            ),
            max_video_bytes=_integer_value(
                values,
                "MAX_VIDEO_BYTES",
                49_000_000,
                minimum=1_000_000,
                maximum=50_000_000,
            ),
            max_total_bytes=_integer_value(
                values,
                "MAX_TOTAL_BYTES",
                100_000_000,
                minimum=1_000_000,
                maximum=500_000_000,
            ),
            download_timeout_seconds=_float_value(
                values,
                "DOWNLOAD_TIMEOUT_SECONDS",
                120,
                minimum=10,
                maximum=600,
            ),
            media_request_timeout_seconds=_float_value(
                values,
                "MEDIA_REQUEST_TIMEOUT_SECONDS",
                30,
                minimum=5,
                maximum=120,
            ),
            telegram_request_timeout_seconds=_float_value(
                values,
                "TELEGRAM_REQUEST_TIMEOUT_SECONDS",
                300,
                minimum=60,
                maximum=1_800,
            ),
            max_concurrent_requests=_integer_value(
                values,
                "MAX_CONCURRENT_REQUESTS",
                2,
                minimum=1,
                maximum=4,
            ),
            max_pending_requests=_integer_value(
                values,
                "MAX_PENDING_REQUESTS",
                8,
                minimum=0,
                maximum=100,
            ),
            max_requests_per_user_minute=_integer_value(
                values,
                "MAX_REQUESTS_PER_USER_MINUTE",
                3,
                minimum=1,
                maximum=60,
            ),
            max_requests_per_minute=_integer_value(
                values,
                "MAX_REQUESTS_PER_MINUTE",
                20,
                minimum=1,
                maximum=600,
            ),
            kkinstagram_fallback_enabled=_boolean_value(
                values,
                "KKINSTAGRAM_FALLBACK_ENABLED",
                True,
            ),
            temp_root=temp_root,
        )


def load_settings(env_path: str | Path = ".env") -> Settings:
    """Читает .env в UTF-8, при этом системные переменные имеют приоритет."""

    path = Path(env_path)
    file_values: dict[str, object] = {}
    if path.is_file():
        file_values.update(dotenv_values(path, encoding="utf-8-sig"))

    values: dict[str, object] = {**file_values, **os.environ}
    return Settings.from_mapping(values)
