"""Bounded, isolated, order-preserving concurrent fan-out — the PoC concurrency primitive.

The use case: run N A3Node-replay jobs at once (e.g. six Maps cities), capped at a
concurrency limit, where one job failing doesn't abort the batch and results come back
in submission order. Deliberately tiny and browser-free so it's unit-testable on its
own; the live demo (`fanout_maps.py`) just feeds it real replay jobs.

A "job" is a zero-arg async callable, so the caller binds its own args (city, config,
plan). Each job owns its isolated resources (a fresh BrowserSession per Maps job), so
there is no shared mutable state across the fan-out.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from typing import TypeVar

T = TypeVar('T')


async def fan_out(jobs: Sequence[Callable[[], Awaitable[T]]], *, limit: int) -> list[T | Exception]:
    """Run `jobs` concurrently, at most `limit` at a time, isolating per-job failures.

    Returns one entry per job, in submission order: the job's result, or the Exception
    it raised (so a single captcha/timeout doesn't sink the batch). BaseException
    (cancellation, KeyboardInterrupt) is NOT swallowed — it propagates.
    """
    semaphore = asyncio.Semaphore(limit)

    async def _guarded(job: Callable[[], Awaitable[T]]) -> T | Exception:
        async with semaphore:
            try:
                return await job()
            except Exception as exc:  # deliberate per-job isolation: returned, not raised
                return exc

    return await asyncio.gather(*(_guarded(job) for job in jobs))
