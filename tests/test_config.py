from pathlib import Path

import pytest

from app.config import Settings, load_settings
from app.errors import ConfigError


def valid_values() -> dict[str, str]:
    return {"BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"}


def test_settings_uses_defaults() -> None:
    settings = Settings.from_mapping(valid_values())

    assert settings.bot_token == "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    assert settings.max_video_bytes == 49_000_000
    assert settings.max_concurrent_requests == 2
    assert settings.telegram_request_timeout_seconds == 300
    assert settings.video_compression_threshold_bytes == 8_000_000
    assert settings.video_compression_crf == 28
    assert settings.video_compression_max_width == 1_280
    assert settings.max_requests_per_user_minute == 3


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        Settings.from_mapping({"BOT_TOKEN": "   "})


def test_invalid_token_format_is_rejected() -> None:
    with pytest.raises(ConfigError, match="формат"):
        Settings.from_mapping({"BOT_TOKEN": "это не токен"})


def test_invalid_integer_has_clear_error() -> None:
    values = {**valid_values(), "MAX_VIDEO_BYTES": "много"}

    with pytest.raises(ConfigError, match="MAX_VIDEO_BYTES"):
        Settings.from_mapping(values)


def test_env_file_allows_spaces_around_equal_sign(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    env_path = tmp_path / ".env"
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    env_path.write_text(f"BOT_TOKEN = {token}\n", encoding="utf-8")

    settings = load_settings(env_path)

    assert settings.bot_token == token


def test_env_file_with_utf8_bom_is_supported(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("BOT_TOKEN", raising=False)
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    env_path = tmp_path / ".env"
    env_path.write_text(f"\ufeffBOT_TOKEN={token}\n", encoding="utf-8")

    assert load_settings(env_path).bot_token == token


def test_environment_has_priority_over_env_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    env_path = tmp_path / ".env"
    env_path.write_text(
        "BOT_TOKEN=123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("BOT_TOKEN", "987654321:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB")

    settings = load_settings(env_path)

    assert settings.bot_token == "987654321:BBBBBBBBBBBBBBBBBBBBBBBBBBBBBB"
