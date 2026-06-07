"""W3: per-engine settle-time measurement scaffold (tenacity-instrumented).

The scaffold polls a 'location-applied' predicate via the blessed async retryer
(no raw sleep loop) and records a per-engine settle distribution. It fail-fasts
when an engine never localizes. All waits are defanged to keep tests instant.
"""

from __future__ import annotations

import pytest

from yosoi.core.replay.runtime import ReplayExecutionError
from yosoi.core.replay.settle import SettleTable, measure_settle
from yosoi.models.replay import AssertKind, ReplayCondition


class _CountingTab:
    """Fake tab whose content gains the city name after N polls (the 'lag')."""

    def __init__(self, *, appears_after: int, city: str = 'Arlington') -> None:
        self._appears_after = appears_after
        self._city = city
        self._content_calls = 0

    async def content(self) -> str:
        self._content_calls += 1
        return self._city if self._content_calls > self._appears_after else 'loading...'


@pytest.fixture(autouse=True)
def _no_retry_sleep(monkeypatch):
    """Make tenacity's async wait instant so the polling loop doesn't sleep."""

    async def _instant(self, *a, **k):
        return None

    import tenacity.asyncio as ta

    monkeypatch.setattr(ta.AsyncRetrying, 'sleep', _instant, raising=False)


async def test_measure_settle_applied_records_timing():
    tab = _CountingTab(appears_after=2)
    table = SettleTable()
    cond = ReplayCondition(kind=AssertKind.TEXT, value='Arlington')
    m = await measure_settle(tab, 'google', cond, table=table)
    assert m.applied is True
    assert m.engine == 'google'
    assert m.attempts >= 3  # had to retry past the lag
    assert table.worst_elapsed('google') is not None
    assert table.mean_elapsed('google') is not None


async def test_measure_settle_first_try_applied():
    tab = _CountingTab(appears_after=0)
    cond = ReplayCondition(kind=AssertKind.TEXT, value='Arlington')
    m = await measure_settle(tab, 'bing', cond)
    assert m.applied is True
    assert m.attempts == 1


async def test_measure_settle_never_applies_fails_fast():
    tab = _CountingTab(appears_after=999)
    table = SettleTable()
    cond = ReplayCondition(kind=AssertKind.TEXT, value='Arlington')
    with pytest.raises(ReplayExecutionError, match='settle never applied for brave'):
        await measure_settle(tab, 'brave', cond, max_attempts=3, table=table)
    # The failed observation is still recorded for the distribution.
    obs = table.by_engine['brave']
    assert len(obs) == 1
    assert obs[0].applied is False


async def test_measure_settle_accepts_callable_predicate():
    state = {'n': 0}

    async def predicate(_tab) -> bool:
        state['n'] += 1
        return state['n'] >= 2

    m = await measure_settle(object(), 'ddg', predicate, max_attempts=5)
    assert m.applied is True
    assert m.attempts == 2


def test_settle_table_summaries_empty_engine():
    table = SettleTable()
    assert table.worst_elapsed('unknown') is None
    assert table.mean_elapsed('unknown') is None
