"""``SignalLane`` — a bounded, single-writer-drained background lane (CAS-168 item 4).

Generic plumbing for "gather off the hot path, defer-not-drop" work. ``offer`` is the response-path
entry point: it never blocks, never awaits, never raises. A full bounded queue under
``backpressure='defer'`` spills to a low-priority backlog that the drainer re-admits as it catches up
(work is deferred, not lost); ``drop`` discards on a full queue for bounded memory. A *single* drainer
task consumes the queue, so the sink sees no write contention with the response path.

Stack-agnostic: the payload is opaque (``Any``) and the ``sink`` is injected, so any subsystem can
reuse the lane (fingerprint/health today; others later).
"""

from __future__ import annotations

import asyncio
import contextlib
from collections import deque
from collections.abc import Awaitable, Callable
from enum import Enum
from typing import Any


class LaneOutcome(str, Enum):
    """What ``offer`` did with an item — useful for telemetry/tests, ignorable on the hot path."""

    QUEUED = 'queued'
    DEFERRED = 'deferred'
    DROPPED = 'dropped'
    OFF = 'off'


class SignalLane:
    """Bounded background lane drained by a single writer task."""

    def __init__(
        self,
        sink: Callable[[Any], Awaitable[None]],
        *,
        enabled: bool = True,
        backpressure: str = 'defer',
        max_queue: int = 256,
    ) -> None:
        """Drain ``sink(item)`` for each offered item; ``backpressure`` governs a full queue."""
        self._sink = sink
        self._enabled = enabled
        self._backpressure = backpressure
        self._queue: asyncio.Queue[Any] = asyncio.Queue(maxsize=max_queue)
        self._backlog: deque[Any] = deque()
        self._drainer: asyncio.Task[None] | None = None

    @property
    def pending(self) -> int:
        """Items not yet handed to the sink (queued + deferred backlog)."""
        return self._queue.qsize() + len(self._backlog)

    def offer(self, item: Any) -> LaneOutcome:
        """Enqueue from the response path — non-blocking, never raises."""
        if not self._enabled:
            return LaneOutcome.OFF
        try:
            self._queue.put_nowait(item)
            return LaneOutcome.QUEUED
        except asyncio.QueueFull:
            if self._backpressure == 'drop':
                return LaneOutcome.DROPPED
            self._backlog.append(item)  # defer: low-priority, re-admitted as the drainer catches up
            return LaneOutcome.DEFERRED

    async def start(self) -> None:
        """Spawn the single drainer task (idempotent; no-op when disabled)."""
        if self._enabled and self._drainer is None:
            self._drainer = asyncio.create_task(self._run())

    async def aclose(self) -> None:
        """Flush every pending item (incl. deferred backlog) through the sink, then stop."""
        if self._drainer is None:
            return
        while self._backlog or not self._queue.empty():
            self._readmit_backlog()
            await self._queue.join()
        self._drainer.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await self._drainer

    async def _run(self) -> None:
        while True:
            item = await self._queue.get()
            try:
                await self._sink(item)
            except Exception:  # noqa: BLE001 - a bad signal must never kill the lane (off-path, best-effort)
                pass
            finally:
                self._queue.task_done()
            self._readmit_backlog()

    def _readmit_backlog(self) -> None:
        while self._backlog:
            try:
                self._queue.put_nowait(self._backlog[0])
            except asyncio.QueueFull:
                break
            self._backlog.popleft()
