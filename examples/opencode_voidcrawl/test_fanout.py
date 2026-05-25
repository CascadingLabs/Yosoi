"""Unit tests for the fan-out concurrency contract — no browser, no network.

Two halves:
  * fan_out() — bounded concurrency, submission-order results, per-job failure isolation.
  * execute_plan() — the A3Node replay is race-free: N concurrent runs over one shared
    (read-only) plan, each on its own page, don't interfere.

Run: uv run pytest examples/opencode_voidcrawl/test_fanout.py
"""

from __future__ import annotations

import asyncio
from functools import partial

import pytest
from fanout import fan_out
from replay_runtime import execute_plan

from yosoi.models.replay import ReplayPlan, navigate

pytestmark = pytest.mark.asyncio


async def test_fan_out_preserves_submission_order() -> None:
    """Results map 1:1 to inputs in order, even when later jobs finish first."""

    async def job(value: int, delay: float) -> int:
        await asyncio.sleep(delay)
        return value

    # job 0 is slowest, job 3 fastest — completion order is reversed from submission.
    jobs = [lambda v=v, d=d: job(v, d) for v, d in [(0, 0.04), (1, 0.03), (2, 0.02), (3, 0.01)]]
    results = await fan_out(jobs, limit=4)
    assert results == [0, 1, 2, 3]


async def test_fan_out_respects_concurrency_limit() -> None:
    """At most `limit` jobs run at once — proven by tracking live concurrency."""
    live = 0
    peak = 0

    async def job() -> None:
        nonlocal live, peak
        live += 1
        peak = max(peak, live)
        await asyncio.sleep(0.02)
        live -= 1

    await fan_out([job for _ in range(8)], limit=3)
    assert peak <= 3
    assert peak == 3  # 8 jobs / limit 3 must saturate the cap


async def test_fan_out_isolates_failures() -> None:
    """One job raising is returned in its slot as the exception; others still succeed."""

    async def ok(value: int) -> int:
        return value

    async def boom() -> int:
        raise ValueError('captcha')

    jobs = [lambda: ok(10), boom, lambda: ok(30)]
    results = await fan_out(jobs, limit=3)
    assert results[0] == 10
    assert isinstance(results[1], ValueError)
    assert str(results[1]) == 'captcha'
    assert results[2] == 30


async def test_fan_out_does_not_swallow_base_exception() -> None:
    """Cancellation/BaseException propagates — only Exception is isolated."""

    async def cancel_me() -> int:
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        await fan_out([cancel_me], limit=1)


class _FakePage:
    """Minimal voidcrawl-page double: records this page's own navigations only."""

    def __init__(self) -> None:
        self.navigations: list[str] = []

    async def navigate(self, url: str) -> None:
        await asyncio.sleep(0)  # yield so concurrent runs interleave
        self.navigations.append(url)


async def test_execute_plan_is_race_free_across_concurrent_pages() -> None:
    """N concurrent replays of ONE shared plan, each on its own page, don't cross-talk.

    Shared plan = concurrent read-only access to the same nodes; per-page recording =
    no shared mutable execution state. If the executor leaked state, navigation counts
    or report scores would be wrong.
    """
    plan = ReplayPlan(target='shared', task='race', nodes=[navigate('https://x.test/a')])
    pages = [_FakePage() for _ in range(6)]

    reports = await fan_out([partial(execute_plan, plan, p) for p in pages], limit=6)

    for page, report in zip(pages, reports, strict=True):
        assert not isinstance(report, Exception)
        assert report.ok  # navigate node passed (no expect -> trivially true)
        assert page.navigations == ['https://x.test/a']  # exactly its own one nav
