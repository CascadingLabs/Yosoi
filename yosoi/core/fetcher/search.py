"""DDGS-backed search fetcher boundary."""

from __future__ import annotations

import asyncio
from typing import Any, Literal, Protocol

from ddgs import DDGS
from ddgs.exceptions import DDGSException

from yosoi.utils.retry import get_async_retryer, log_retry


class _SearchNoResultsError(RuntimeError):
    """Raised when DDGS exhausts backend candidates without any rows."""


def _backend_candidates(backend: str) -> list[str]:
    """Return DDGS backend attempts from most specific to broadest."""
    value = backend.strip()
    parts = [part.strip() for part in value.split(',') if part.strip()]
    candidates = [value]
    if len(parts) > 1:
        candidates.extend(parts)
    if value not in {'auto', 'all'}:
        candidates.append('auto')

    deduped: list[str] = []
    for candidate in candidates:
        if candidate and candidate not in deduped:
            deduped.append(candidate)
    return deduped or ['auto']


def _is_no_results_exception(exc: Exception) -> bool:
    return 'No results found' in str(exc)


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
    errors: list[str] = []
    transient_errors: list[Exception] = []
    with DDGS() as ddgs:
        for backend in _backend_candidates(request.backend):
            try:
                rows = ddgs.text(
                    request.query,
                    backend=backend,
                    region=request.region,
                    safesearch=request.safesearch,
                    timelimit=request.timelimit,
                    max_results=request.max_results,
                    page=request.page,
                )
            except DDGSException as exc:
                errors.append(f'{backend}: {exc}')
                if not _is_no_results_exception(exc):
                    transient_errors.append(exc)
                continue
            if rows:
                return rows
            errors.append(f'{backend}: no results')

    message = '; '.join(errors) or 'No results found.'
    if transient_errors:
        raise DDGSException(message)
    raise _SearchNoResultsError(message)


async def fetch_ddgs_text(request: DDGSTextRequest) -> list[dict[str, Any]]:
    """Fetch DDGS text rows using Yosoi's async retry policy."""
    async for attempt in get_async_retryer(
        max_attempts=3,
        wait_min=0.5,
        wait_max=5.0,
        log_callback=log_retry,
        non_retry_exceptions=(_SearchNoResultsError,),
    ):
        with attempt:
            return await asyncio.to_thread(_run_ddgs_text_sync, request)
    raise RuntimeError('DDGS search retryer exited without a result')
