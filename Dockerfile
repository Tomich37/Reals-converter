FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Сначала копируем метаданные и код отдельно, чтобы Docker мог кешировать установку.
COPY pyproject.toml README.md ./
COPY app ./app

RUN python -m pip install --no-cache-dir . \
    && useradd --create-home --uid 10001 bot

# Бот не требует прав root; временные файлы сохраняются в системный /tmp.
USER bot

CMD ["python", "-m", "app"]
