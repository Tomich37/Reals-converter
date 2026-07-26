"""Доменные ошибки приложения, не зависящие от конкретных библиотек."""


class AppError(Exception):
    """Базовая ожидаемая ошибка приложения."""


class ConfigError(AppError):
    """Настройки отсутствуют или содержат недопустимое значение."""


class InvalidInstagramUrl(AppError):
    """Сообщение не содержит одну поддерживаемую ссылку Instagram."""


class ContentUnavailable(AppError):
    """Instagram не отдал публикацию без авторизации."""


class InstagramAccessBlocked(AppError):
    """Instagram временно отклонил анонимный запрос, а резервный источник не помог."""


class DownloadFailed(AppError):
    """Медиа не удалось загрузить из-за временной ошибки."""


class DownloadTimedOut(AppError):
    """Загрузка не завершилась за отведённое время."""


class TooManyItems(AppError):
    """В публикации больше медиафайлов, чем можно отправить одним альбомом."""


class FileTooLarge(AppError):
    """Один из файлов превышает лимит Telegram."""


class TotalSizeExceeded(AppError):
    """Суммарный размер публикации превышает настроенный лимит."""


class UnsupportedMedia(AppError):
    """Instagram вернул неподдерживаемый тип или адрес медиа."""


class AlreadyProcessing(AppError):
    """Для пользователя уже выполняется запрос."""


class ServiceBusy(AppError):
    """Очередь запросов заполнена."""


class RateLimited(AppError):
    """Пользователь слишком часто отправляет новые ссылки."""
