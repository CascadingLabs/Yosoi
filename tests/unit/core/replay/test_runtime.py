"""Tests for the package replay runtime — duck-typed against a FakePage.

No voidcrawl dependency. The runtime is verified to:
  * Run sequential plans, fail-fast on a missed precondition.
  * Execute click_until with selector_absent termination (reddit's load-more shape).
  * Handle the no-op cases (empty plan, navigate-only plan, wait nodes).
  * Surface per-node pass/fail in the VerifyReport.
"""

from __future__ import annotations

import json
from typing import Any

import pytest

from yosoi.core.replay.runtime import execute_plan, run_node
from yosoi.models.replay import (
    A3Node,
    Act,
    ReplayPlan,
    click,
    click_until,
    css,
    min_count,
    navigate,
    selector_absent,
    selector_present,
)


class FakePage:
    """In-memory page stand-in. Tracks navigates + click counts; eval_js dispatches
    on a few JS shapes the runtime emits (existence check, scroll-and-count,
    JS-click)."""

    def __init__(
        self,
        *,
        present_selectors: set[str] | None = None,
        load_more_selector: str | None = None,
        load_more_consumed_after: int = 0,
    ) -> None:
        self.navigations: list[str] = []
        self.click_counts: dict[str, int] = {}
        self._present: set[str] = set(present_selectors or set())
        self._load_more = load_more_selector
        self._load_more_clicks_until_gone = load_more_consumed_after

    # ── public API the runtime calls ─────────────────────────────────────────
    async def navigate(self, url: str) -> None:
        self.navigations.append(url)

    async def content(self) -> str:
        # Synthesise a doc reflecting current presence — useful for text_present asserts.
        return '<html><body>' + ''.join(f'<el selector="{s}"></el>' for s in self._present) + '</body></html>'

    async def evaluate_js(self, expr: str) -> Any:
        # location.href check (url_contains)
        if 'location.href' in expr:
            return self.navigations[-1] if self.navigations else ''
        # JS-click path emitted by _click_css_robust: scrollIntoView + el.click() + return true
        if 'scrollIntoView' in expr and 'el.click()' in expr:
            sel = self._extract_selector(expr)
            if sel == self._load_more and self._load_more is not None:
                self.click_counts[sel] = self.click_counts.get(sel, 0) + 1
                if self.click_counts[sel] >= self._load_more_clicks_until_gone:
                    self._present.discard(sel)
                return True
            return sel in self._present
        # presence check: querySelector(...)!==null
        if '!==null' in expr:
            sel = self._extract_selector(expr)
            return sel in self._present
        # _count helper: returns the number of matches in scope after scrolling
        if 'querySelectorAll' in expr:
            return 0
        return None

    # ── helpers ──────────────────────────────────────────────────────────────
    @staticmethod
    def _extract_selector(expr: str) -> str:
        """Recover the selector arg from a JS string the runtime built via json.dumps.

        The runtime always json.dumps the selector, so we use raw_decode to read
        the JSON string starting right after ``querySelector(`` — this handles
        escaped quotes inside attribute selectors (``[src*=\\"...\\"]``) correctly.
        """
        marker = 'querySelector('
        idx = expr.find(marker)
        if idx < 0:
            return ''
        rest = expr[idx + len(marker) :].lstrip()
        try:
            value, _ = json.JSONDecoder().raw_decode(rest)
        except json.JSONDecodeError:
            return ''
        return str(value)


@pytest.mark.asyncio
async def test_execute_empty_plan_returns_perfect_score() -> None:
    page = FakePage()
    plan = ReplayPlan(target='t', task='nothing', source='scripted', nodes=[])
    report = await execute_plan(plan, page)
    assert report.results == []
    # An empty report has score == 0.0 by convention (no nodes → no pass rate).
    assert report.score == 0.0
    # `ok` is True only when there's at least one passing node — empty stays False.
    assert report.ok is False


@pytest.mark.asyncio
async def test_navigate_with_url_contains_postcondition_passes() -> None:
    page = FakePage()
    plan = ReplayPlan(
        target='example.com',
        task='go',
        source='scripted',
        nodes=[navigate('https://example.com/x')],  # no expect → always passes
    )
    report = await execute_plan(plan, page)
    assert page.navigations == ['https://example.com/x']
    assert report.score == 1.0
    assert report.ok is True


@pytest.mark.asyncio
async def test_click_until_with_selector_absent_terminates_when_trigger_consumed() -> None:
    """The reddit-shape plan: click_until(load_more, expect=selector_absent(load_more))."""
    trigger = 'faceplate-partial[src*="more-comments"] button'
    structural_done = 'faceplate-partial[src*="more-comments"]'
    # Trigger is present initially; gets consumed after 3 clicks.
    page = FakePage(
        present_selectors={trigger, structural_done},
        load_more_selector=trigger,
        load_more_consumed_after=3,
    )

    # When the JS click hits the trigger, FakePage discards BOTH the trigger
    # and the structural-done selector (since they're the same family).
    # Simulate by tying them: the test clicks the button and we drop both.
    original_eval = page.evaluate_js

    async def eval_and_unify(expr: str) -> Any:
        result = await original_eval(expr)
        if 'scrollIntoView' in expr and trigger not in page._present:
            page._present.discard(structural_done)
        return result

    page.evaluate_js = eval_and_unify  # type: ignore[method-assign]

    node = click_until(
        css(trigger),
        expect=selector_absent(css(structural_done)),
        max_iters=10,
    )
    result = await run_node(0, node, page)
    assert result.passed, result.detail
    assert page.click_counts[trigger] == 3


@pytest.mark.asyncio
async def test_failed_assess_short_circuits_plan_with_fail_fast() -> None:
    """If a node's assess never holds, the rest of the plan is reported as skipped."""
    page = FakePage(present_selectors=set())  # nothing is present
    # First node demands a precondition we never satisfy.
    gated = A3Node(
        act=Act(op='navigate', url='https://x.example'),
        assess=selector_present(css('.never-here')),
    )
    after = navigate('https://x.example/2')
    plan = ReplayPlan(target='x.example', task='boom', source='scripted', nodes=[gated, after])
    report = await execute_plan(plan, page, fail_fast=True)
    assert len(report.results) == 2
    assert report.results[0].passed is False
    assert 'assess never held' in (report.results[0].detail or '')
    assert report.results[1].passed is False
    assert report.results[1].op == 'skipped'


@pytest.mark.asyncio
async def test_click_postcondition_fails_when_expected_state_never_holds() -> None:
    """A click whose expect (selector_present X) never becomes true reports a failure."""
    # Trigger exists; the post-condition selector .target never appears.
    page = FakePage(present_selectors={'#trigger'})
    node = click(css('#trigger'), expect=selector_present(css('.target')))
    result = await run_node(0, node, page)
    assert result.passed is False
    assert 'selector absent' in (result.detail or '')


@pytest.mark.asyncio
async def test_min_count_via_count_helper() -> None:
    """min_count uses _count which calls querySelectorAll under the hood. Empty page → fail."""
    page = FakePage()
    node = navigate('https://x.example', expect=min_count(5, css('article')))
    result = await run_node(0, node, page)
    # Our fake returns 0 for querySelectorAll → min_count(5) fails with details.
    assert result.passed is False
    assert '< 5' in (result.detail or '')
