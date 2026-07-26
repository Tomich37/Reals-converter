"""Получение метаданных Instagram и безопасная загрузка медиа."""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import mimetypes
import multiprocessing
import socket
from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager, suppress
from itertools import islice
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Protocol
from urllib.parse import urljoin, urlsplit

import instaloader
import requests
from instaloader.exceptions import (
    BadResponseException,
    ConnectionException,
    InstaloaderException,
    LoginRequiredException,
    PrivateProfileNotFollowedException,
    ProfileNotExistsException,
    QueryReturnedBadRequestException,
    QueryReturnedForbiddenException,
    QueryReturnedNotFoundException,
    TooManyRequestsException,
)

from app import texts
from app.config import Settings
from app.errors import (
    AppError,
    ContentUnavailable,
    DownloadFailed,
    DownloadTimedOut,
    FileTooLarge,
    InstagramAccessBlocked,
    TooManyItems,
    TotalSizeExceeded,
    UnsupportedMedia,
)
from app.models import (
    DownloadedMedia,
    DownloadedPost,
    InstagramUrl,
    MediaKind,
    RemoteMedia,
)

logger = logging.getLogger(__name__)

_ALLOWED_MEDIA_DOMAINS = ("instagram.com", "cdninstagram.com", "fbcdn.net")
_ALLOWED_KKINSTAGRAM_HOSTS = {
    "kkinstagram.com",
    "www.kkinstagram.com",
    "kkclip.com",
    "www.kkclip.com",
}
_KKINSTAGRAM_BASE_URL = "https://www.kkinstagram.com"
_KKINSTAGRAM_USER_AGENT = "TelegramBot (like TwitterBot)"
_PHOTO_CONTENT_TYPES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
}
_VIDEO_CONTENT_TYPES = {
    "video/mp4": ".mp4",
}
_REDIRECT_CODES = {301, 302, 303, 307, 308}
_MAX_NETWORK_STEPS = 4
_PROCESS_POLL_INTERVAL = 0.05
_PROCESS_STOP_GRACE_SECONDS = 0.25
_PROCESS_TERMINATE_GRACE_SECONDS = 1.0
_FALLBACK_CANDIDATE_EXCEPTIONS = (
    BadResponseException,
    ConnectionException,
    LoginRequiredException,
    QueryReturnedBadRequestException,
    QueryReturnedForbiddenException,
    TooManyRequestsException,
)
_PERMANENT_UNAVAILABLE_EXCEPTIONS = (
    PrivateProfileNotFollowedException,
    ProfileNotExistsException,
    QueryReturnedNotFoundException,
)


class _WorkerCancelled(Exception):
    """Внутренний сигнал остановки блокирующего рабочего потока."""


class CancellationSignal(Protocol):
    """Минимальный интерфейс события отмены для потока или процесса."""

    def is_set(self) -> bool:
        """Сообщает, что работу пора остановить."""


class SyncInstagramWorker(Protocol):
    """Интерфейс синхронного загрузчика для подмены в тестах."""

    def download(
        self,
        instagram_url: InstagramUrl,
        directory: Path,
        cancel_event: CancellationSignal,
    ) -> DownloadedPost:
        """Загружает публикацию в указанный каталог."""


def extract_media_sources(post: object, max_items: int) -> tuple[RemoteMedia, ...]:
    """Преобразует объект Instaloader Post в упорядоченный список медиа."""

    typename = getattr(post, "typename", "")
    sources: list[RemoteMedia] = []

    if typename == "GraphSidecar":
        media_count = int(getattr(post, "mediacount", 0) or 0)
        if media_count > max_items:
            raise TooManyItems

        nodes = list(islice(post.get_sidecar_nodes(), max_items + 1))
        if len(nodes) > max_items:
            raise TooManyItems

        for node in nodes:
            is_video = bool(node.is_video)
            media_url = node.video_url if is_video else node.display_url
            if not media_url:
                raise UnsupportedMedia
            sources.append(
                RemoteMedia(
                    url=str(media_url),
                    kind=MediaKind.VIDEO if is_video else MediaKind.PHOTO,
                )
            )
    else:
        is_video = bool(getattr(post, "is_video", False))
        media_url = getattr(post, "video_url", None) if is_video else getattr(post, "url", None)
        if not media_url:
            raise UnsupportedMedia
        sources.append(
            RemoteMedia(
                url=str(media_url),
                kind=MediaKind.VIDEO if is_video else MediaKind.PHOTO,
            )
        )

    if not sources:
        raise UnsupportedMedia
    return tuple(sources)


def _is_allowed_domain(host: str) -> bool:
    return any(host == domain or host.endswith(f".{domain}") for domain in _ALLOWED_MEDIA_DOMAINS)


def _ensure_public_address(host: str) -> None:
    """Отклоняет адреса, которые могут вести во внутреннюю сеть сервера."""

    try:
        addresses = socket.getaddrinfo(host, 443, type=socket.SOCK_STREAM)
    except OSError as error:
        raise DownloadFailed from error

    if not addresses:
        raise UnsupportedMedia

    for address in addresses:
        raw_ip = address[4][0].split("%", maxsplit=1)[0]
        try:
            parsed_ip = ipaddress.ip_address(raw_ip)
        except ValueError as error:
            raise UnsupportedMedia from error
        if not parsed_ip.is_global:
            raise UnsupportedMedia


def _validate_remote_url(url: str) -> str:
    """Проверяет CDN-адрес перед каждым сетевым переходом."""

    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as error:
        raise UnsupportedMedia from error

    if (
        parts.scheme.lower() != "https"
        or not _is_allowed_domain(host)
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
    ):
        raise UnsupportedMedia

    _ensure_public_address(host)
    return url


def _validate_kkinstagram_url(url: str) -> str:
    """Разрешает только фиксированные HTTPS-адреса резервного сервиса."""

    try:
        parts = urlsplit(url)
        host = (parts.hostname or "").rstrip(".").lower()
        port = parts.port
    except ValueError as error:
        raise UnsupportedMedia from error

    if (
        parts.scheme.lower() != "https"
        or host not in _ALLOWED_KKINSTAGRAM_HOSTS
        or parts.username is not None
        or parts.password is not None
        or port not in {None, 443}
    ):
        raise UnsupportedMedia

    _ensure_public_address(host)
    return url


def _content_type(response: requests.Response) -> str:
    return response.headers.get("Content-Type", "").split(";", maxsplit=1)[0].strip().lower()


def _media_kind_for_response(response: requests.Response) -> MediaKind:
    content_type = _content_type(response)
    if content_type in _PHOTO_CONTENT_TYPES:
        return MediaKind.PHOTO
    if content_type in _VIDEO_CONTENT_TYPES:
        return MediaKind.VIDEO
    raise UnsupportedMedia


def _extension_for(kind: MediaKind, response: requests.Response) -> str:
    content_type = _content_type(response)
    extensions = _PHOTO_CONTENT_TYPES if kind is MediaKind.PHOTO else _VIDEO_CONTENT_TYPES
    extension = extensions.get(content_type)
    if extension is not None:
        return extension

    guessed = mimetypes.guess_extension(content_type)
    if guessed in extensions.values():
        return guessed
    raise UnsupportedMedia


class InstaloaderWorker:
    """Синхронный адаптер Instaloader с контролем адресов и размеров."""

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._request_timeout = min(
            settings.media_request_timeout_seconds,
            settings.download_timeout_seconds,
        )

    def download(
        self,
        instagram_url: InstagramUrl,
        directory: Path,
        cancel_event: CancellationSignal,
    ) -> DownloadedPost:
        loader = instaloader.Instaloader(
            sleep=True,
            quiet=True,
            download_pictures=False,
            download_videos=False,
            download_video_thumbnails=False,
            download_geotags=False,
            download_comments=False,
            save_metadata=False,
            post_metadata_txt_pattern="",
            max_connection_attempts=1,
            request_timeout=self._request_timeout,
        )

        try:
            if cancel_event.is_set():
                raise _WorkerCancelled

            post = instaloader.Post.from_shortcode(loader.context, instagram_url.shortcode)
            sources = extract_media_sources(post, self._settings.max_media_items)
            caption = getattr(post, "caption", None)

            session = loader.context.get_anonymous_session()
            try:
                media = self._download_sources(
                    session=session,
                    sources=sources,
                    directory=directory,
                    cancel_event=cancel_event,
                )
            finally:
                session.close()

            return DownloadedPost(
                media=media,
                caption=str(caption) if caption else None,
                source_url=instagram_url.canonical,
            )
        except AppError:
            raise
        except _WorkerCancelled:
            raise
        except InstaloaderException as error:
            if self._is_temporary_instaloader_error(error):
                if self._settings.kkinstagram_fallback_enabled:
                    return self._use_kkinstagram_or_raise(
                        instagram_url,
                        directory,
                        cancel_event,
                        error_type=InstagramAccessBlocked,
                    )
                raise InstagramAccessBlocked from error
            raise ContentUnavailable from error
        except (KeyError, TypeError) as error:
            raise ContentUnavailable from error
        except requests.RequestException as error:
            if self._settings.kkinstagram_fallback_enabled:
                return self._use_kkinstagram_or_raise(
                    instagram_url,
                    directory,
                    cancel_event,
                    error_type=DownloadFailed,
                )
            raise DownloadFailed from error
        finally:
            loader.close()

    @staticmethod
    def _is_temporary_instaloader_error(error: InstaloaderException) -> bool:
        if isinstance(error, _PERMANENT_UNAVAILABLE_EXCEPTIONS):
            return False
        return isinstance(error, _FALLBACK_CANDIDATE_EXCEPTIONS)

    def _use_kkinstagram_or_raise(
        self,
        instagram_url: InstagramUrl,
        directory: Path,
        cancel_event: CancellationSignal,
        *,
        error_type: type[AppError],
    ) -> DownloadedPost:
        """Запускает резервный путь и сохраняет понятную исходную категорию ошибки."""

        logger.info(
            "Instagram отклонил прямой запрос; используется резервный источник KKInstagram."
        )
        try:
            return self._download_via_kkinstagram(
                instagram_url,
                directory,
                cancel_event,
            )
        except _WorkerCancelled:
            raise
        except (FileTooLarge, TotalSizeExceeded):
            raise
        except Exception as fallback_error:
            raise error_type from fallback_error

    def _download_via_kkinstagram(
        self,
        instagram_url: InstagramUrl,
        directory: Path,
        cancel_event: CancellationSignal,
    ) -> DownloadedPost:
        """Получает один прямой CDN-файл через резервный сервис и скачивает его."""

        session = requests.Session()
        try:
            source = self._resolve_kkinstagram_source(
                session,
                instagram_url,
                cancel_event,
            )
            media, _ = self._download_source(
                session=session,
                source=source,
                directory=directory,
                index=1,
                current_total=0,
                cancel_event=cancel_event,
            )
        finally:
            session.close()

        return DownloadedPost(
            media=(media,),
            caption=texts.FALLBACK_CAPTION,
            source_url=instagram_url.canonical,
        )

    def _resolve_kkinstagram_source(
        self,
        session: requests.Session,
        instagram_url: InstagramUrl,
        cancel_event: CancellationSignal,
    ) -> RemoteMedia:
        """Следует только по проверенным переходам до прямого CDN-файла."""

        current_url = (
            f"{_KKINSTAGRAM_BASE_URL}/{instagram_url.publication_type}/{instagram_url.shortcode}/"
        )

        for _ in range(_MAX_NETWORK_STEPS):
            if cancel_event.is_set():
                raise _WorkerCancelled

            host = (urlsplit(current_url).hostname or "").rstrip(".").lower()
            if host in _ALLOWED_KKINSTAGRAM_HOSTS:
                _validate_kkinstagram_url(current_url)
            else:
                _validate_remote_url(current_url)

            response = session.get(
                current_url,
                stream=True,
                allow_redirects=False,
                timeout=(min(10, self._request_timeout), self._request_timeout),
                headers={"User-Agent": _KKINSTAGRAM_USER_AGENT},
            )

            if response.status_code in _REDIRECT_CODES:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise DownloadFailed
                current_url = urljoin(current_url, location)
                continue

            try:
                response.raise_for_status()
                _validate_remote_url(response.url)
                return RemoteMedia(
                    url=response.url,
                    kind=_media_kind_for_response(response),
                )
            finally:
                response.close()

        raise DownloadFailed

    def _download_sources(
        self,
        *,
        session: requests.Session,
        sources: Sequence[RemoteMedia],
        directory: Path,
        cancel_event: CancellationSignal,
    ) -> tuple[DownloadedMedia, ...]:
        downloaded: list[DownloadedMedia] = []
        total_size = 0

        for index, source in enumerate(sources, start=1):
            media, total_size = self._download_source(
                session=session,
                source=source,
                directory=directory,
                index=index,
                current_total=total_size,
                cancel_event=cancel_event,
            )
            downloaded.append(media)

        return tuple(downloaded)

    def _download_source(
        self,
        *,
        session: requests.Session,
        source: RemoteMedia,
        directory: Path,
        index: int,
        current_total: int,
        cancel_event: CancellationSignal,
    ) -> tuple[DownloadedMedia, int]:
        current_url = source.url

        for _ in range(_MAX_NETWORK_STEPS):
            if cancel_event.is_set():
                raise _WorkerCancelled

            _validate_remote_url(current_url)
            response = session.get(
                current_url,
                stream=True,
                allow_redirects=False,
                timeout=(min(10, self._request_timeout), self._request_timeout),
                headers={"Referer": "https://www.instagram.com/"},
            )

            if response.status_code in _REDIRECT_CODES:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise DownloadFailed
                current_url = urljoin(current_url, location)
                continue

            try:
                response.raise_for_status()
                _validate_remote_url(response.url)
                extension = _extension_for(source.kind, response)
                destination = (directory / f"{index:02d}{extension}").resolve()
                if destination.parent != directory.resolve():
                    raise UnsupportedMedia

                item_limit = (
                    self._settings.max_photo_bytes
                    if source.kind is MediaKind.PHOTO
                    else self._settings.max_video_bytes
                )
                try:
                    declared_size = int(response.headers.get("Content-Length", "0") or 0)
                except ValueError:
                    declared_size = 0
                if declared_size > item_limit:
                    raise FileTooLarge
                if current_total + declared_size > self._settings.max_total_bytes:
                    raise TotalSizeExceeded

                item_size = 0
                with destination.open("xb") as output:
                    for chunk in response.iter_content(chunk_size=256 * 1024):
                        if cancel_event.is_set():
                            raise _WorkerCancelled
                        if not chunk:
                            continue

                        item_size += len(chunk)
                        if item_size > item_limit:
                            raise FileTooLarge
                        if current_total + item_size > self._settings.max_total_bytes:
                            raise TotalSizeExceeded
                        output.write(chunk)

                if item_size == 0:
                    raise DownloadFailed

                return (
                    DownloadedMedia(
                        path=destination,
                        kind=source.kind,
                        size=item_size,
                    ),
                    current_total + item_size,
                )
            finally:
                response.close()

        raise DownloadFailed


_WORKER_ERROR_TYPES: dict[str, type[AppError]] = {
    error_type.__name__: error_type
    for error_type in (
        ContentUnavailable,
        DownloadFailed,
        FileTooLarge,
        InstagramAccessBlocked,
        TooManyItems,
        TotalSizeExceeded,
        UnsupportedMedia,
    )
}


def _worker_process_entry(
    connection: object,
    worker: SyncInstagramWorker,
    instagram_url: InstagramUrl,
    directory: Path,
    cancel_event: CancellationSignal,
) -> None:
    """Выполняет загрузку в дочернем процессе без передачи деталей ошибок."""

    try:
        post = worker.download(instagram_url, directory, cancel_event)
    except _WorkerCancelled:
        connection.send(("error", DownloadFailed.__name__, None))
    except AppError as error:
        connection.send(("error", type(error).__name__, None))
    except BaseException:
        connection.send(("error", DownloadFailed.__name__, None))
    else:
        connection.send(("ok", "", post))
    finally:
        connection.close()


class InstagramDownloader:
    """Асинхронный фасад, сохраняющий временные файлы до конца отправки."""

    def __init__(
        self,
        settings: Settings,
        worker: SyncInstagramWorker | None = None,
    ) -> None:
        self._settings = settings
        self._worker = worker or InstaloaderWorker(settings)
        if settings.temp_root is not None:
            settings.temp_root.mkdir(parents=True, exist_ok=True)

    @asynccontextmanager
    async def download(self, instagram_url: InstagramUrl) -> AsyncIterator[DownloadedPost]:
        """Загружает публикацию и удаляет файлы после выхода из контекста."""

        temporary_root = str(self._settings.temp_root) if self._settings.temp_root else None
        with TemporaryDirectory(prefix="instagram_bot_", dir=temporary_root) as raw_directory:
            directory = Path(raw_directory).resolve()
            process_context = multiprocessing.get_context("spawn")
            receive_connection, send_connection = process_context.Pipe(duplex=False)
            cancel_event = process_context.Event()
            process = process_context.Process(
                target=_worker_process_entry,
                args=(
                    send_connection,
                    self._worker,
                    instagram_url,
                    directory,
                    cancel_event,
                ),
                daemon=True,
            )
            process_started = False

            try:
                try:
                    process.start()
                    process_started = True
                    send_connection.close()

                    completed = await self._wait_for_process(
                        process,
                        self._settings.download_timeout_seconds,
                    )
                    if not completed:
                        await self._stop_process(process, cancel_event)
                        raise DownloadTimedOut

                    post = self._receive_result(receive_connection)
                except asyncio.CancelledError:
                    await self._stop_process(process, cancel_event)
                    raise
                except (OSError, RuntimeError) as error:
                    raise DownloadFailed from error

                yield post
            finally:
                if process_started and process.is_alive():
                    await self._stop_process(process, cancel_event)
                if process_started and process.exitcode is not None:
                    process.close()
                receive_connection.close()
                with suppress(OSError):
                    send_connection.close()

    @staticmethod
    async def _wait_for_process(process: multiprocessing.Process, timeout: float) -> bool:
        """Ожидает процесс без блокировки цикла событий."""

        loop = asyncio.get_running_loop()
        deadline = loop.time() + timeout
        while process.is_alive():
            remaining = deadline - loop.time()
            if remaining <= 0:
                return False
            await asyncio.sleep(min(_PROCESS_POLL_INTERVAL, remaining))

        process.join(timeout=0)
        return True

    @classmethod
    async def _stop_process(
        cls,
        process: multiprocessing.Process,
        cancel_event: object,
    ) -> None:
        """Мягко останавливает процесс, затем гарантированно завершает его."""

        cancel_event.set()
        if await cls._wait_for_process(process, _PROCESS_STOP_GRACE_SECONDS):
            return

        process.terminate()
        if await cls._wait_for_process(process, _PROCESS_TERMINATE_GRACE_SECONDS):
            return

        process.kill()
        await cls._wait_for_process(process, _PROCESS_TERMINATE_GRACE_SECONDS)

    @staticmethod
    def _receive_result(connection: object) -> DownloadedPost:
        """Читает результат процесса и восстанавливает доменную ошибку."""

        try:
            if not connection.poll(0.5):
                raise DownloadFailed
            status, error_name, post = connection.recv()
        except (EOFError, OSError) as error:
            raise DownloadFailed from error

        if status == "ok" and isinstance(post, DownloadedPost):
            return post

        error_type = _WORKER_ERROR_TYPES.get(str(error_name), DownloadFailed)
        raise error_type
