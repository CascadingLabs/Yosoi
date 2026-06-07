"""W3: teleport-before-first-paint ordering + TeleportSpec fail-fast.

The per-plan ``ReplayPlan.teleport`` field must be applied by ``execute_plan``
BEFORE the node loop — i.e. before the first NAVIGATE's goto — so the CDP
geolocation override is live before first paint. These tests pin that ordering
against a fake tab (no browser) and the fail-fast coordinate validator.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from yosoi.core.replay.runtime import execute_plan
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
    TeleportSpec,
)


class OrderTab:
    """Fake tab recording the exact call order of set_geolocation vs goto."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []
        self.url = 'https://example.invalid/'

    async def set_geolocation(self, lat, lon):
        self.calls.append(('geo', lat, lon))

    async def set_timezone(self, tz):
        self.calls.append(('tz', tz))

    async def set_locale(self, loc):
        self.calls.append(('locale', loc))

    async def goto(self, url, **kw):
        self.calls.append(('goto', url))

    async def content(self):
        return ''


def _navigate_plan(url: str, teleport: TeleportSpec | None = None) -> ReplayPlan:
    return ReplayPlan(
        nodes=[ReplayNode(id='nav', intent='open', act=ReplayAct(kind=ActKind.NAVIGATE, url=url))],
        teleport=teleport,
    )


async def test_teleport_applied_before_first_navigate():
    tab = OrderTab()
    plan = _navigate_plan(
        'https://google.com/search?q=pizza',
        TeleportSpec(latitude=38.88, longitude=-77.10, timezone='America/New_York', locale='en-US'),
    )
    result = await execute_plan(tab, plan)
    assert result.passed == 1

    geo_idx = next(i for i, c in enumerate(tab.calls) if c[0] == 'geo')
    goto_idx = next(i for i, c in enumerate(tab.calls) if c[0] == 'goto')
    assert geo_idx < goto_idx, f'geolocation must precede goto, got {tab.calls}'
    # timezone/locale also installed pre-navigate
    assert ('tz', 'America/New_York') in tab.calls
    assert ('locale', 'en-US') in tab.calls
    assert tab.calls.index(('tz', 'America/New_York')) < goto_idx
    assert tab.calls.index(('locale', 'en-US')) < goto_idx


async def test_no_teleport_means_no_geo_call():
    tab = OrderTab()
    plan = _navigate_plan('https://google.com/search?q=pizza', teleport=None)
    await execute_plan(tab, plan)
    assert not any(c[0] == 'geo' for c in tab.calls)
    assert ('goto', 'https://google.com/search?q=pizza') in tab.calls


async def test_no_example_com_prime_navigation():
    """The example.com secure-context prime is DISCOVERY-time, never on replay.

    Replay must issue exactly the plan's navigations — one goto for a single
    NAVIGATE node — with no extra prime load injected by teleport.
    """
    tab = OrderTab()
    plan = _navigate_plan(
        'https://brave.com/search?q=dentist',
        TeleportSpec(latitude=40.0, longitude=-74.0),
    )
    await execute_plan(tab, plan)
    gotos = [c for c in tab.calls if c[0] == 'goto']
    assert gotos == [('goto', 'https://brave.com/search?q=dentist')]


async def test_teleport_omits_optional_fields_when_unset():
    tab = OrderTab()
    plan = _navigate_plan('https://x.test/', TeleportSpec(latitude=1.0, longitude=2.0))
    await execute_plan(tab, plan)
    assert ('geo', 1.0, 2.0) in tab.calls
    assert not any(c[0] == 'tz' for c in tab.calls)
    assert not any(c[0] == 'locale' for c in tab.calls)


def test_teleport_spec_rejects_out_of_range_coords():
    with pytest.raises(ValidationError):
        TeleportSpec(latitude=200.0, longitude=0.0)
    with pytest.raises(ValidationError):
        TeleportSpec(latitude=0.0, longitude=999.0)


def test_plan_without_teleport_is_valid():
    plan = ReplayPlan(nodes=[])
    assert plan.teleport is None


async def test_teleport_with_assess_condition_still_orders_first():
    """Even when the first node has an assess gate, teleport precedes everything."""
    tab = OrderTab()
    plan = ReplayPlan(
        nodes=[
            ReplayNode(
                id='nav',
                intent='open',
                assess=ReplayCondition(kind=AssertKind.NONE),
                act=ReplayAct(kind=ActKind.NAVIGATE, url='https://bing.com/search?q=tacos'),
            )
        ],
        teleport=TeleportSpec(latitude=34.0, longitude=-118.2),
    )
    await execute_plan(tab, plan)
    assert tab.calls[0] == ('geo', 34.0, -118.2)
