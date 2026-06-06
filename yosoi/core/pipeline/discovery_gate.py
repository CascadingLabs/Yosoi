"""Single-flight discovery gate.

Concurrent scrapes of the same ``(domain, contract)`` discover ONCE; the rest wait and read
the warm cache. This keeps the simple call simple: ``ys.scrape(many_urls, Contract)`` runs
every unit concurrently, and the engine — not the caller — makes sure only the first cold
unit pays an LLM discovery while the others replay it.
"""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager


class DiscoveryGate:
    """A keyed async single-flight lock.

    Concurrent units for the same key (``"{domain}::{contract_signature}"``) serialize, so
    only the FIRST runs discovery; the rest wait, then find the cache warm and replay.
    Different keys never block each other — distinct contracts (or domains) discover in
    parallel, so the discrimination case is unaffected.
    """

    def __init__(self) -> None:
        """Create an empty gate (a fresh per-key lock registry)."""
        self._locks: dict[str, asyncio.Lock] = {}
        self._guard = asyncio.Lock()

    @asynccontextmanager
    async def hold(self, key: str) -> AsyncIterator[None]:
        """Hold the single-flight lock for ``key`` for the duration of the block."""
        async with self._guard:
            lock = self._locks.get(key)
            if lock is None:
                lock = asyncio.Lock()
                self._locks[key] = lock
        async with lock:
            yield
