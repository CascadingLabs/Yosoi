"""Replay-runtime coverage for act/condition branches not exercised elsewhere.

Complements test_runtime.py: TYPE/SCROLL/EVAL/WAIT/TELEPORT acts, the
TEXT/URL/DOM_STABLE/AX_TARGET conditions, repeat-until-expect, and expect
failure — all against a fake tab (no browser).
"""

from __future__ import annotations

import pytest

from yosoi.core.replay.runtime import ReplayExecutionError, execute_plan
from yosoi.models.replay import (
    ActKind,
    AssertKind,
    ReplayAct,
    ReplayCondition,
    ReplayNode,
    ReplayPlan,
)
from yosoi.models.selectors import css, role


class FakeTab:
    """Fake tab exposing the fill / eval_js / wait_for_network_idle / set_* surface."""

    def __init__(
        self, *, present: bool = True, content: str = 'hello world', url: str = 'https://x.com/p', ax_nodes=None
    ):
        self._present = present
        self._content = content
        self.url = url
        self._ax = ax_nodes if ax_nodes is not None else []
        self.calls: list[tuple] = []

    async def goto(self, url, **kw):
        self.calls.append(('goto', url))

    async def click_element(self, sel):
        self.calls.append(('click_element', sel))

    async def fill(self, sel, text):
        self.calls.append(('fill', sel, text))

    async def query_selector(self, sel):
        return object() if self._present else None

    async def query_selector_all(self, sel):
        return [object()] * 5

    async def eval_js(self, script):
        self.calls.append(('eval_js', script))
        return self.url

    async def content(self):
        return self._content

    async def wait_for_network_idle(self, timeout=5.0):
        self.calls.append(('idle', timeout))

    async def get_full_ax_tree(self):
        return self._ax

    async def set_geolocation(self, lat, lon):
        self.calls.append(('geo', lat, lon))

    async def set_timezone(self, tz):
        self.calls.append(('tz', tz))

    async def set_locale(self, loc):
        self.calls.append(('locale', loc))


def _node(name: str, act: ReplayAct, *, assess=None, expect=None) -> ReplayNode:
    return ReplayNode(
        id=name,
        intent=name,
        assess=assess or ReplayCondition(kind=AssertKind.NONE),
        act=act,
        expect=expect or ReplayCondition(kind=AssertKind.NONE),
    )


async def test_type_act_uses_fill():
    plan = ReplayPlan(nodes=[_node('type', ReplayAct(kind=ActKind.TYPE, targets=[css('input#q')], text='hello'))])
    tab = FakeTab()
    report = await execute_plan(tab, plan)
    assert report.passed == 1
    assert ('fill', 'input#q', 'hello') in tab.calls


async def test_scroll_eval_wait_acts():
    plan = ReplayPlan(
        nodes=[
            _node('scroll', ReplayAct(kind=ActKind.SCROLL, metadata={'pixels': 800})),
            _node('eval', ReplayAct(kind=ActKind.EVAL, script='document.title')),
            _node('wait', ReplayAct(kind=ActKind.WAIT, dwell_ms=1)),
        ]
    )
    tab = FakeTab()
    report = await execute_plan(tab, plan)
    assert report.passed == 3
    assert any(c == ('eval_js', 'window.scrollBy(0, 800)') for c in tab.calls)
    assert ('eval_js', 'document.title') in tab.calls


async def test_teleport_sets_geo_timezone_locale():
    plan = ReplayPlan(
        nodes=[
            _node(
                'teleport',
                ReplayAct(
                    kind=ActKind.TELEPORT,
                    metadata={'latitude': 1.5, 'longitude': 2.5, 'timezone': 'UTC', 'locale': 'en-GB'},
                ),
            )
        ]
    )
    tab = FakeTab()
    await execute_plan(tab, plan)
    assert ('geo', 1.5, 2.5) in tab.calls
    assert ('tz', 'UTC') in tab.calls
    assert ('locale', 'en-GB') in tab.calls


async def test_text_and_dom_stable_conditions():
    plan = ReplayPlan(
        nodes=[
            _node(
                'verify',
                ReplayAct(kind=ActKind.WAIT, dwell_ms=0),
                assess=ReplayCondition(kind=AssertKind.TEXT, value='hello'),
                expect=ReplayCondition(kind=AssertKind.DOM_STABLE, timeout_ms=1000),
            )
        ]
    )
    tab = FakeTab(content='hello world')
    report = await execute_plan(tab, plan)
    assert report.passed == 1
    assert ('idle', 1.0) in tab.calls


async def test_ax_target_condition_matches_role_and_name():
    ax = [{'role': 'button', 'name': {'value': 'Accept all cookies'}}]
    plan = ReplayPlan(
        nodes=[
            _node(
                'cookies',
                ReplayAct(kind=ActKind.WAIT, dwell_ms=0),
                expect=ReplayCondition(kind=AssertKind.AX_TARGET, selector=role('button', 'accept')),
            )
        ]
    )
    report = await execute_plan(FakeTab(ax_nodes=ax), plan)
    assert report.passed == 1


async def test_repeat_scroll_stops_once_expect_holds():
    plan = ReplayPlan(
        nodes=[
            _node(
                'scroll until loaded',
                ReplayAct(kind=ActKind.SCROLL, repeat=True, max_repeats=10, metadata={'pixels': 500}),
                expect=ReplayCondition(kind=AssertKind.SELECTOR, selector=css('.loaded')),
            )
        ]
    )
    tab = FakeTab(present=True)  # expect holds after the first scroll
    await execute_plan(tab, plan)
    assert sum(1 for c in tab.calls if c[0] == 'eval_js') == 1


async def test_expect_failure_is_fail_fast():
    plan = ReplayPlan(
        nodes=[
            _node(
                'click then require',
                ReplayAct(kind=ActKind.WAIT, dwell_ms=0),
                expect=ReplayCondition(kind=AssertKind.SELECTOR, selector=css('.never')),
            )
        ]
    )
    with pytest.raises(ReplayExecutionError, match='assert failed'):
        await execute_plan(FakeTab(present=False), plan)
