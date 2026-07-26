from app import texts
from app.errors import InstagramAccessBlocked
from app.handlers import _text_for_error


def test_temporary_instagram_block_has_separate_user_message() -> None:
    assert _text_for_error(InstagramAccessBlocked()) == texts.INSTAGRAM_ACCESS_BLOCKED
