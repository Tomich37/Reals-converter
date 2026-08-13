from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from app.services.video_compressor import VideoCompressor


@pytest.mark.asyncio
async def test_small_video_is_not_compressed(tmp_path: Path) -> None:
    source = tmp_path / "small.mp4"
    source.write_bytes(b"video")
    compressor = VideoCompressor(threshold_bytes=10, crf=28, max_width=1280)

    result = await compressor.compress(source)

    assert result == source


@pytest.mark.asyncio
async def test_smaller_compressed_video_is_used(tmp_path: Path) -> None:
    source = tmp_path / "large.mp4"
    source.write_bytes(b"large-video")
    process = AsyncMock()
    process.returncode = 0

    async def communicate() -> tuple[bytes, bytes]:
        (tmp_path / "large.compressed.mp4").write_bytes(b"small")
        return b"", b""

    process.communicate.side_effect = communicate
    compressor = VideoCompressor(threshold_bytes=1, crf=28, max_width=1280)

    with patch("asyncio.create_subprocess_exec", AsyncMock(return_value=process)):
        result = await compressor.compress(source)

    assert result.name == "large.compressed.mp4"
    compressor.remove_result(result, source)
    assert not result.exists()
    assert source.exists()
