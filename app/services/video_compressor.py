"""Сжатие больших видео перед загрузкой в Telegram."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


class VideoCompressor:
    """Перекодирует большие ролики и оставляет исходник при неудаче."""

    def __init__(self, *, threshold_bytes: int, crf: int, max_width: int) -> None:
        self._threshold_bytes = threshold_bytes
        self._crf = crf
        self._max_width = max_width

    async def compress(self, source: Path) -> Path:
        """Возвращает более компактный MP4 либо исходный файл."""

        source_size = source.stat().st_size
        if source_size <= self._threshold_bytes:
            return source

        destination = source.with_name(f"{source.stem}.compressed.mp4")
        command = (
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(source),
            "-map_metadata",
            "-1",
            "-vf",
            f"scale='min({self._max_width},iw)':-2",
            "-c:v",
            "libx264",
            "-preset",
            "veryfast",
            "-crf",
            str(self._crf),
            "-c:a",
            "aac",
            "-b:a",
            "96k",
            "-movflags",
            "+faststart",
            str(destination),
        )

        try:
            process = await asyncio.create_subprocess_exec(
                *command,
                stdout=asyncio.subprocess.DEVNULL,
                stderr=asyncio.subprocess.PIPE,
            )
            _, stderr = await process.communicate()
        except OSError as error:
            logger.warning("Не удалось запустить ffmpeg: %s", error)
            return source

        if process.returncode != 0 or not destination.is_file():
            message = stderr.decode("utf-8", errors="replace").strip()
            logger.warning("ffmpeg не смог сжать %s: %s", source.name, message[-500:])
            destination.unlink(missing_ok=True)
            return source

        compressed_size = destination.stat().st_size
        if compressed_size >= source_size:
            destination.unlink(missing_ok=True)
            logger.info("Сжатие %s не уменьшило файл; используется оригинал.", source.name)
            return source

        logger.info(
            "Видео %s сжато с %.1f до %.1f МБ.",
            source.name,
            source_size / 1_000_000,
            compressed_size / 1_000_000,
        )
        return destination

    @staticmethod
    def remove_result(result: Path, source: Path) -> None:
        """Удаляет созданную копию, не затрагивая скачанный оригинал."""

        if result != source:
            result.unlink(missing_ok=True)
