"""Regression coverage for same-domain concurrent VoidCrawl pool use."""

from __future__ import annotations

import asyncio
import time
from typing import Any

import pytest

from yosoi.core.fetcher.dom import LoadResult
from yosoi.core.fetcher.voiddriver import _VoidCrawlFetcher


class _ConcurrentAcquirePool:
    def __init__(self, tabs: list[_ConcurrentTab]) -> None:
        self._tabs = tabs
        self.active = 0
        self.max_active = 0

    def acquire(self) -> _AcquireContext:
        return _AcquireContext(self, self._tabs.pop(0))


class _AcquireContext:
    def __init__(self, pool: _ConcurrentAcquirePool, tab: _ConcurrentTab) -> None:
        self._pool = pool
        self._tab = tab

    async def __aenter__(self) -> _ConcurrentTab:
        self._pool.active += 1
        self._pool.max_active = max(self._pool.max_active, self._pool.active)
        return self._tab

    async def __aexit__(self, *_exc: Any) -> None:
        self._pool.active -= 1


class _ConcurrentTab:
    def __init__(self, name: str, started: list[str], both_started: asyncio.Event) -> None:
        self.name = name
        self._started = started
        self._both_started = both_started
        self.urls: list[str] = []

    async def goto(self, url: str, timeout: float) -> None:
        self.urls.append(url)
        self._started.append(self.name)
        if len(self._started) == 2:
            self._both_started.set()
        await asyncio.wait_for(self._both_started.wait(), timeout=1)


class _TabEchoDOMLoader:
    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        pass

    async def run(self, tab: _ConcurrentTab) -> LoadResult:
        body = f'<article>{tab.name}</article>' + ('x' * 600)
        return LoadResult(
            success=True,
            content_start=1,
            content_final=1,
            elapsed_ms=1,
            html=f'<html><body>{body}</body></html>',
        )


@pytest.mark.asyncio
async def test_same_domain_concurrent_fetches_use_distinct_acquired_tabs(mocker) -> None:
    """Concurrent same-origin fetches must not serialize or share tab navigation state."""
    both_started = asyncio.Event()
    started: list[str] = []
    tabs = [_ConcurrentTab('tab-a', started, both_started), _ConcurrentTab('tab-b', started, both_started)]
    pool = _ConcurrentAcquirePool(tabs)
    fetcher = _VoidCrawlFetcher(min_content_length=1)
    fetcher._pool = pool
    mocker.patch('yosoi.core.fetcher.voiddriver.DOMLoader', _TabEchoDOMLoader)

    first, second = await asyncio.wait_for(
        asyncio.gather(
            fetcher._do_fetch('https://example.com/a', time.time(), 'fetch'),
            fetcher._do_fetch('https://example.com/b', time.time(), 'fetch'),
        ),
        timeout=1,
    )

    assert pool.max_active == 2
    assert started == ['tab-a', 'tab-b']
    assert first.html is not None
    assert second.html is not None
    assert 'tab-a' in first.html
    assert 'tab-b' in second.html
