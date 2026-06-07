"""Tests for _VoidCrawlFetcher.fetch_with_plan — the execute_plan hotpath wiring (W4 PR2).

No real browser: the pool is mocked to yield a fake pooled tab. These guard that
a learned ReplayPlan actually drives a tab via the deterministic runtime, behind
the ``experimental_replay_plan`` opt-in, with params substituted into the URL.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

import pytest
from pytest_mock import MockerFixture

from yosoi.core.fetcher.voiddriver import HeadlessFetcher
from yosoi.core.replay.runtime import ReplayExecutionError
from yosoi.models.replay import ActKind, ReplayAct, ReplayNode, ReplayPlan


class _FakeTab:
    class _Resp:
        antibot = None

    def __init__(self, html: str = '<main>' + 'x' * 200 + '</main>', challenged: bool = False) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self._html = html
        self._challenged = challenged

    async def goto(self, url: str):
        self.calls.append(('goto', (url,)))
        resp = self._Resp()
        if self._challenged:
            resp.antibot = type('AntiBot', (), {'challenged': True})()
        return resp

    async def content(self) -> str:
        return self._html


def _pooled(fetcher: HeadlessFetcher, tab: _FakeTab) -> None:
    @asynccontextmanager
    async def _acquire():
        yield tab

    pool = type('Pool', (), {'acquire': staticmethod(_acquire)})()
    fetcher._pool = pool


def _plan() -> ReplayPlan:
    return ReplayPlan(
        nodes=[ReplayNode(id='nav', intent='open engine', act=ReplayAct(kind=ActKind.NAVIGATE, url='https://e/{d}/'))]
    )


async def test_fetch_with_plan_disabled_raises():
    f = HeadlessFetcher(min_content_length=10)  # flag defaults off
    with pytest.raises(RuntimeError, match='replay-plan fetch is disabled'):
        await f.fetch_with_plan(_plan(), params={'d': 'acme.com'})


async def test_fetch_with_plan_substitutes_param_and_drives_tab(mocker: MockerFixture):
    f = HeadlessFetcher(experimental_replay_plan=True, min_content_length=10)
    f._console = mocker.MagicMock()
    tab = _FakeTab()
    _pooled(f, tab)

    result = await f.fetch_with_plan(_plan(), params={'d': 'acme.com'})

    assert ('goto', ('https://e/acme.com/',)) in tab.calls
    assert result.html is not None
    assert result.status_code == 200


async def test_fetch_with_plan_propagates_antibot_fail_fast(mocker: MockerFixture):
    f = HeadlessFetcher(experimental_replay_plan=True, min_content_length=10)
    f._console = mocker.MagicMock()
    tab = _FakeTab(challenged=True)
    _pooled(f, tab)

    with pytest.raises(ReplayExecutionError, match='antibot challenge detected'):
        await f.fetch_with_plan(_plan(), params={'d': 'acme.com'})
