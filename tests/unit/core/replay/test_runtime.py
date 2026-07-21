"""Tests for the fail-fast replay runtime."""

from __future__ import annotations

import pytest

from yosoi.core.replay.runtime import ReplayExecutionError, execute_plan, verify_plan
from yosoi.models.replay import ActKind, AssertKind, ReplayAct, ReplayCondition, ReplayNode, ReplayPlan
from yosoi.models.selectors import css, role, visual


class FakeTab:
    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[object, ...]]] = []
        self.selectors: dict[str, list[object]] = {}
        self.html = '<main><button>More</button></main>'
        self.url = 'https://example.com/start'
        self.ax_nodes: list[dict[str, object]] = []

    async def goto(self, url: str) -> None:
        self.calls.append(('goto', (url,)))
        self.url = url

    async def click_element(self, selector: str) -> None:
        if selector == 'button.missing':
            raise RuntimeError('no element')
        self.calls.append(('click_element', (selector,)))

    async def click_by_role(self, role_name: str, name: str, nth: int) -> None:
        self.calls.append(('click_by_role', (role_name, name, nth)))

    async def click_visual_coords(self, x: float, y: float) -> None:
        self.calls.append(('click_visual_coords', (x, y)))

    async def query_selector(self, selector: str) -> object | None:
        values = self.selectors.get(selector, [])
        return values[0] if values else None

    async def query_selector_all(self, selector: str) -> list[object]:
        return self.selectors.get(selector, [])

    async def content(self) -> str:
        return self.html

    async def evaluate(self, script: str) -> object:
        self.calls.append(('evaluate', (script,)))
        if script == 'location.href':
            return self.url
        return None

    async def get_full_ax_tree(self) -> list[dict[str, object]]:
        return self.ax_nodes


def _plan(node: ReplayNode) -> ReplayPlan:
    return ReplayPlan(nodes=[node])


async def test_execute_plan_navigate_and_assert_url():
    tab = FakeTab()
    plan = _plan(
        ReplayNode(
            id='nav',
            intent='open page',
            act=ReplayAct(kind=ActKind.NAVIGATE, url='https://example.com/items'),
            expect=ReplayCondition(kind=AssertKind.URL, value='/items'),
        )
    )

    report = await execute_plan(tab, plan)

    assert report.score == 1.0
    assert tab.calls == [('goto', ('https://example.com/items',))]


async def test_execute_plan_clicks_first_working_target():
    tab = FakeTab()
    plan = _plan(
        ReplayNode(
            id='more',
            intent='click more',
            act=ReplayAct(kind=ActKind.CLICK, targets=[role('button', 'More'), css('button.more')]),
        )
    )

    await execute_plan(tab, plan)

    assert tab.calls == [('click_by_role', ('button', 'More', 0))]


async def test_execute_plan_resolves_role_substring_to_exact_ax_name_before_click():
    tab = FakeTab()
    tab.ax_nodes = [{'role': {'value': 'tab'}, 'name': {'value': 'Reviews for Example Place'}}]
    plan = _plan(
        ReplayNode(
            id='reviews',
            intent='open reviews',
            act=ReplayAct(kind=ActKind.CLICK, targets=[role('tab', 'Reviews')]),
        )
    )

    await execute_plan(tab, plan)

    assert tab.calls == [('click_by_role', ('tab', 'Reviews for Example Place', 0))]


async def test_execute_plan_supports_visual_click_target():
    tab = FakeTab()
    plan = _plan(
        ReplayNode(
            id='visual',
            intent='click coords',
            act=ReplayAct(kind=ActKind.CLICK, targets=[visual(10, 20)]),
        )
    )

    await execute_plan(tab, plan)

    assert tab.calls == [('click_visual_coords', (10.0, 20.0))]


async def test_execute_plan_fails_fast_on_missing_assess_selector():
    tab = FakeTab()
    plan = _plan(
        ReplayNode(
            id='guard',
            intent='requires main',
            assess=ReplayCondition(kind=AssertKind.SELECTOR, selector=css('main')),
            act=ReplayAct(kind=ActKind.CLICK, targets=[css('button')]),
        )
    )

    with pytest.raises(ReplayExecutionError, match='assess failed for guard') as exc:
        await execute_plan(tab, plan)

    assert exc.value.report.failed == 1


async def test_execute_plan_count_assertion():
    tab = FakeTab()
    tab.selectors['article'] = [object(), object()]
    plan = _plan(
        ReplayNode(
            id='count',
            intent='enough records',
            act=ReplayAct(kind=ActKind.WAIT),
            expect=ReplayCondition(kind=AssertKind.COUNT, selector=css('article'), value=2),
        )
    )

    report = await execute_plan(tab, plan)

    assert report.passed == 1


async def test_verify_plan_converts_failure_to_report():
    tab = FakeTab()
    plan = _plan(
        ReplayNode(
            id='missing',
            intent='missing target',
            act=ReplayAct(kind=ActKind.CLICK, targets=[css('button.missing')]),
        )
    )

    report = await verify_plan(tab, plan)

    assert report.failed == 1
    assert 'click failed for all targets' in report.failures[0]
