"""Ограничение параллельных запросов и длины очереди."""

from __future__ import annotations

import asyncio
from collections import deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from app.errors import AlreadyProcessing, RateLimited, ServiceBusy

_RATE_WINDOW_SECONDS = 60.0
_HISTORY_PRUNE_THRESHOLD = 1_024


class RequestCoordinator:
    """Не допускает дубли пользователя и переполнение общей очереди."""

    def __init__(
        self,
        max_concurrent: int,
        max_pending: int,
        max_requests_per_user_minute: int = 3,
        max_requests_per_minute: int = 20,
    ) -> None:
        self._semaphore = asyncio.Semaphore(max_concurrent)
        self._max_pending = max_pending
        self._max_requests_per_user = max_requests_per_user_minute
        self._max_requests = max_requests_per_minute
        self._lock = asyncio.Lock()
        self._users: set[int] = set()
        self._waiting = 0
        self._user_history: dict[int, deque[float]] = {}
        self._request_history: deque[float] = deque()

    @asynccontextmanager
    async def slot(self, user_id: int) -> AsyncIterator[None]:
        """Занимает место на весь сценарий: от скачивания до отправки."""

        counted_as_waiting = False
        acquired = False

        async with self._lock:
            if user_id in self._users:
                raise AlreadyProcessing

            if self._semaphore.locked():
                if self._waiting >= self._max_pending:
                    raise ServiceBusy
                self._waiting += 1
                counted_as_waiting = True

            now = asyncio.get_running_loop().time()
            cutoff = now - _RATE_WINDOW_SECONDS
            self._discard_expired(self._request_history, cutoff)
            if len(self._request_history) >= self._max_requests:
                if counted_as_waiting:
                    self._waiting -= 1
                raise ServiceBusy

            user_history = self._user_history.setdefault(user_id, deque())
            self._discard_expired(user_history, cutoff)
            if len(user_history) >= self._max_requests_per_user:
                if counted_as_waiting:
                    self._waiting -= 1
                raise RateLimited

            self._request_history.append(now)
            user_history.append(now)
            self._users.add(user_id)
            self._prune_user_history(cutoff)

        try:
            await self._semaphore.acquire()
            acquired = True

            if counted_as_waiting:
                async with self._lock:
                    self._waiting -= 1
                    counted_as_waiting = False

            yield
        finally:
            if acquired:
                self._semaphore.release()

            async with self._lock:
                if counted_as_waiting:
                    self._waiting -= 1
                self._users.discard(user_id)

    @staticmethod
    def _discard_expired(history: deque[float], cutoff: float) -> None:
        while history and history[0] <= cutoff:
            history.popleft()

    def _prune_user_history(self, cutoff: float) -> None:
        if len(self._user_history) <= _HISTORY_PRUNE_THRESHOLD:
            return

        stale_users = [
            user_id
            for user_id, history in self._user_history.items()
            if not history or history[-1] <= cutoff
        ]
        for user_id in stale_users:
            self._user_history.pop(user_id, None)
