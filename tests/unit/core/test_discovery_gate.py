"""Single-flight DiscoveryGate: same key serializes, different keys run in parallel."""

from __future__ import annotations

import asyncio

from yosoi.core.pipeline.discovery_gate import DiscoveryGate


async def test_same_key_serializes() -> None:
    gate = DiscoveryGate()
    order: list[str] = []

    async def worker(name: str) -> None:
        async with gate.hold('domain::sig'):
            order.append(f'{name}-in')
            await asyncio.sleep(0.01)
            order.append(f'{name}-out')

    await asyncio.gather(worker('a'), worker('b'))
    # No interleaving — one fully completes before the other starts.
    assert order in (['a-in', 'a-out', 'b-in', 'b-out'], ['b-in', 'b-out', 'a-in', 'a-out'])


async def test_different_keys_run_in_parallel() -> None:
    gate = DiscoveryGate()
    inside: list[str] = []
    both = asyncio.Event()

    async def worker(key: str) -> None:
        async with gate.hold(key):
            inside.append(key)
            if len(inside) == 2:
                both.set()
            await asyncio.wait_for(both.wait(), timeout=1.0)  # both must be inside at once

    await asyncio.gather(worker('d1::sig'), worker('d2::sig'))
    assert set(inside) == {'d1::sig', 'd2::sig'}  # distinct keys never blocked each other
