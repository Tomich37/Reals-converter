"""Небольшие модели данных, которыми обмениваются сервисы."""

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path


class MediaKind(StrEnum):
    """Тип медиа для выбора подходящего метода Telegram."""

    PHOTO = "photo"
    VIDEO = "video"


@dataclass(frozen=True, slots=True)
class InstagramUrl:
    """Проверенная и очищенная ссылка Instagram."""

    canonical: str
    shortcode: str
    publication_type: str


@dataclass(frozen=True, slots=True)
class RemoteMedia:
    """Проверенный прямой адрес медиафайла Instagram CDN."""

    url: str
    kind: MediaKind


@dataclass(frozen=True, slots=True)
class DownloadedMedia:
    """Локальный файл, готовый к отправке в Telegram."""

    path: Path
    kind: MediaKind
    size: int


@dataclass(frozen=True, slots=True)
class DownloadedPost:
    """Полностью загруженная публикация."""

    media: tuple[DownloadedMedia, ...]
    caption: str | None
    source_url: str
