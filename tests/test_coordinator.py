import asyncio

import pytest

from app.errors import AlreadyProcessing, RateLimited, ServiceBusy
from app.services.coordinator import RequestCoordinator


@pytest.mark.asyncio
async def test_second_request_from_same_user_is_rejected() -> None:
    coordinator = RequestCoordinator(max_concurrent=2, max_pending=2)

    async with coordinator.slot(10):
        with pytest.raises(AlreadyProcessing):
            async with coordinator.slot(10):
                pass


@pytest.mark.asyncio
async def test_request_is_rejected_when_queue_is_disabled() -> None:
    coordinator = RequestCoordinator(max_concurrent=1, max_pending=0)

    async with coordinator.slot(10):
        with pytest.raises(ServiceBusy):
            async with coordinator.slot(20):
                pass


@pytest.mark.asyncio
async def test_waiting_request_runs_after_slot_is_released() -> None:
    coordinator = RequestCoordinator(max_concurrent=1, max_pending=1)
    first_started = asyncio.Event()
    release_first = asyncio.Event()
    second_started = asyncio.Event()

    async def first() -> None:
        async with coordinator.slot(1):
            first_started.set()
            await release_first.wait()

    async def second() -> None:
        await first_started.wait()
        async with coordinator.slot(2):
            second_started.set()

    first_task = asyncio.create_task(first())
    second_task = asyncio.create_task(second())
    await first_started.wait()
    await asyncio.sleep(0)

    assert not second_started.is_set()
    release_first.set()
    await asyncio.gather(first_task, second_task)

    assert second_started.is_set()


@pytest.mark.asyncio
async def test_user_request_rate_is_limited() -> None:
    coordinator = RequestCoordinator(
        max_concurrent=1,
        max_pending=1,
        max_requests_per_user_minute=1,
        max_requests_per_minute=10,
    )

    async with coordinator.slot(10):
        pass

    with pytest.raises(RateLimited):
        async with coordinator.slot(10):
            pass


@pytest.mark.asyncio
async def test_global_request_rate_is_limited() -> None:
    coordinator = RequestCoordinator(
        max_concurrent=1,
        max_pending=1,
        max_requests_per_user_minute=10,
        max_requests_per_minute=1,
    )

    async with coordinator.slot(10):
        pass

    with pytest.raises(ServiceBusy):
        async with coordinator.slot(20):
            pass
