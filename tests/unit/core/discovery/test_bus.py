"""Unit tests for DiscoveryBus and ScopedBus."""

from __future__ import annotations

import asyncio

import pytest

from yosoi.core.discovery.bus import DiscoveryBus
from yosoi.models.selectors import FieldSelectors


def _make_selectors(selector: str = 'h1.title') -> FieldSelectors:
    return FieldSelectors(primary=selector)


# ---------------------------------------------------------------------------
# Basic acquisition / leadership
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_first_acquire_returns_true():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    is_leader = await scoped.acquire('sig1')
    assert is_leader is True


@pytest.mark.anyio
async def test_second_acquire_returns_false():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    await scoped.acquire('sig1')
    is_leader = await scoped.acquire('sig1')
    assert is_leader is False


@pytest.mark.anyio
async def test_different_domains_independent():
    bus = DiscoveryBus()
    a = bus.scoped('alpha.com')
    b = bus.scoped('beta.com')
    assert await a.acquire('sig1') is True
    assert await b.acquire('sig1') is True  # different domain → different slot


# ---------------------------------------------------------------------------
# Publish / wait_for protocol
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_wait_for_after_publish_returns_result():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    selectors = _make_selectors()

    await scoped.acquire('sig1')
    await scoped.publish('sig1', selectors)

    # Late waiter (slot already DONE) should get result immediately
    _ = await scoped.acquire('sig1')  # returns False
    result = await scoped.wait_for('sig1')
    assert result is not None
    assert result.primary.value == 'h1.title'


@pytest.mark.anyio
async def test_publish_none_unblocks_waiters():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')

    await scoped.acquire('sig1')
    await scoped.publish('sig1', None)

    result = await scoped.wait_for('sig1')
    assert result is None


@pytest.mark.anyio
async def test_publish_wakes_concurrent_waiter():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    selectors = _make_selectors('span.price')

    received: list[FieldSelectors | None] = []

    async def waiter() -> None:
        # Acquire returns False — slot already taken by leader below
        is_leader = await scoped.acquire('sig1')
        assert is_leader is False
        result = await scoped.wait_for('sig1')
        received.append(result)

    async def leader() -> None:
        await scoped.acquire('sig1')
        await asyncio.sleep(0)  # yield so waiter can call wait_for
        await scoped.publish('sig1', selectors)

    await asyncio.gather(leader(), waiter())

    assert len(received) == 1
    assert received[0] is not None
    assert received[0].primary.value == 'span.price'


# ---------------------------------------------------------------------------
# Concurrent stress test
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_concurrent_acquire_only_one_leader():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    leader_count = 0

    async def try_acquire() -> None:
        nonlocal leader_count
        if await scoped.acquire('stress-sig'):
            leader_count += 1

    await asyncio.gather(*[try_acquire() for _ in range(20)])
    assert leader_count == 1


@pytest.mark.anyio
async def test_concurrent_publish_and_wait():
    """5 tasks race; exactly one becomes leader and publishes; all 4 waiters unblock."""
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    selectors = _make_selectors('div.item')
    results: list[FieldSelectors | None] = []

    async def participant() -> None:
        is_leader = await scoped.acquire('c-sig')
        if is_leader:
            try:
                await asyncio.sleep(0)  # simulate LLM call
                await scoped.publish('c-sig', selectors)
            except Exception:  # noqa: BLE001
                await scoped.publish('c-sig', None)
        else:
            result = await scoped.wait_for('c-sig')
            results.append(result)

    await asyncio.gather(*[participant() for _ in range(5)])

    # 4 waiters should have received the selectors
    assert len(results) == 4
    assert all(r is not None and r.primary.value == 'div.item' for r in results)


# ---------------------------------------------------------------------------
# clear()
# ---------------------------------------------------------------------------


@pytest.mark.anyio
async def test_clear_resets_slots():
    bus = DiscoveryBus()
    scoped = bus.scoped('example.com')
    await scoped.acquire('sig1')
    await scoped.publish('sig1', _make_selectors())

    bus.clear()

    # After clear, the slot is gone — next acquire is leadership again
    assert await scoped.acquire('sig1') is True
