from pathlib import Path

import pytest

from app.config import Settings, load_settings
from app.errors import ConfigError


def valid_values() -> dict[str, str]:
    return {"BOT_TOKEN": "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"}


def test_settings_uses_defaults() -> None:
    settings = Settings.from_mapping(valid_values())

    assert settings.bot_token == "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZ_123456"
    assert settings.max_media_items == 10
    assert settings.max_video_bytes == 49_000_000
    assert settings.max_concurrent_requests == 2
    assert settings.telegram_request_timeout_seconds == 300
    assert settings.max_requests_per_user_minute == 3
    assert settings.kkinstagram_fallback_enabled is True


def test_empty_token_is_rejected() -> None:
    with pytest.raises(ConfigError, match="BOT_TOKEN"):
        Settings.from_mapping({"BOT_TOKEN": "   "})


def test_invalid_token_format_is_rejected() -> None:
    with pytest.raises(ConfigError, match="формат"):
        Settings.from_mapping({"BOT_TOKEN": "это не токен"})


def test_invalid_integer_has_clear_error() -> None:
    values = {**valid_values(), "MAX_MEDIA_ITEMS": "много"}

    with pytest.raises(ConfigError, match="MAX_MEDIA_ITEMS"):
        Settings.from_mapping(values)


@pytest.mark.parametrize("value", ["false", "0", "no", "off"])
def test_kkinstagram_fallback_can_be_disabled(value: str) -> None:
    values = {**valid_values(), "KKINSTAGRAM_FALLBACK_ENABLED": value}

    assert Settings.from_mapping(values).kkinstagram_fallback_enabled is False


def test_invalid_boolean_has_clear_error() -> None:
    values = {**valid_values(), "KKINSTAGRAM_FALLBACK_ENABLED": "иногда"}

    with pytest.raises(ConfigError, match="KKINSTAGRAM_FALLBACK_ENABLED"):
        Settings.from_mapping(values)


def test_telegram_album_limit_cannot_be_exceeded() -> None:
    values = {**valid_values(), "MAX_MEDIA_ITEMS": "11"}

    with pytest.raises(ConfigError, match="MAX_MEDIA_ITEMS"):
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
