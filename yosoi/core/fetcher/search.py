"""DDGS-backed search fetcher boundary."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Protocol

from ddgs import DDGS

from yosoi.utils.retry import get_async_retryer, log_retry


class DDGSTextRequest(Protocol):
    """Subset of ``SearchRequest`` needed by the DDGS boundary."""

    query: str
    backend: str
    region: str
    safesearch: Literal['on', 'moderate', 'off']
    timelimit: str | None
    max_results: int
    page: int


def _run_ddgs_text_sync(request: DDGSTextRequest) -> list[dict[str, Any]]:
    """Run DDGS text search synchronously inside a worker thread."""
    with DDGS() as ddgs:
        return ddgs.text(
            request.query,
            backend=request.backend,
            region=request.region,
            safesearch=request.safesearch,
            timelimit=request.timelimit,
            max_results=request.max_results,
            page=request.page,
        )


async def fetch_ddgs_text(request: DDGSTextRequest) -> list[dict[str, Any]]:
    """Fetch DDGS text rows using Yosoi's async retry policy."""
    async for attempt in get_async_retryer(max_attempts=3, wait_min=0.5, wait_max=5.0, log_callback=log_retry):
        with attempt:
            return await asyncio.to_thread(_run_ddgs_text_sync, request)
    raise RuntimeError('DDGS search retryer exited without a result')
