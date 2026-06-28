"""Tests for DOM page-state probes (yosoi.core.fetcher.dom.probes)."""

import pytest

from yosoi.core.fetcher.dom.ax import AxTarget
from yosoi.core.fetcher.dom.probes import (
    DetectedTrigger,
    TriggerKind,
    detected_trigger_to_selector_entry,
    probe_cookie,
    probe_infinite_scroll,
    selector_entry_to_detected_trigger,
)


class _ScrollTab:
    """Minimal fake tab whose eval_js returns a fixed scrollability verdict."""

    def __init__(self, scrollable: bool) -> None:
        self._scrollable = scrollable
        self.evals: list[str] = []

    async def eval_js(self, script: str):
        self.evals.append(script)
        return self._scrollable


class _NoEvalTab:
    """Fake tab with no eval_js method — probe must degrade to None, not raise."""


class _AxCookieTab:
    async def get_full_ax_tree(self):
        return [
            {'role': {'value': 'button'}, 'name': {'value': 'Accept additional cookies'}, 'ignored': False},
            {'role': {'value': 'link'}, 'name': {'value': 'View cookies'}, 'ignored': False},
        ]

    async def query_selector(self, _selector: str):
        raise AssertionError('AX cookie probe should run before CSS fallbacks')


@pytest.mark.asyncio
async def test_cookie_probe_prefers_ax_accept_button():
    trigger = await probe_cookie(_AxCookieTab())
    assert trigger is not None
    assert trigger.kind == TriggerKind.COOKIE
    assert trigger.ax_target == AxTarget('button', 'Accept additional cookies', 0)


@pytest.mark.asyncio
async def test_infinite_scroll_detected_when_page_is_scrollable():
    trigger = await probe_infinite_scroll(_ScrollTab(scrollable=True), content_count=7)
    assert trigger is not None
    assert trigger.kind == TriggerKind.INFINITE_SCROLL


@pytest.mark.asyncio
async def test_no_infinite_scroll_when_page_not_scrollable():
    assert await probe_infinite_scroll(_ScrollTab(scrollable=False), content_count=20) is None


@pytest.mark.asyncio
async def test_round_count_alone_does_not_trigger():
    """Regression: content_count % 10 == 0 must NOT fire on a non-scrollable page."""
    tab = _ScrollTab(scrollable=False)
    assert await probe_infinite_scroll(tab, content_count=10) is None
    # The verdict came from a real DOM probe, not from the count.
    assert tab.evals


@pytest.mark.asyncio
async def test_no_content_skips_probe_entirely():
    """With zero counted items there is nothing to grow, so don't even eval."""
    tab = _ScrollTab(scrollable=True)
    assert await probe_infinite_scroll(tab, content_count=0) is None
    assert not tab.evals


@pytest.mark.asyncio
async def test_missing_eval_js_degrades_to_none():
    assert await probe_infinite_scroll(_NoEvalTab(), content_count=12) is None


# --- DetectedTrigger <-> SelectorEntry conversion (selector-level recipes, CAS-94) ----


def test_ax_trigger_becomes_role_selector_entry():
    trigger = DetectedTrigger(
        TriggerKind.LOAD_MORE, 'ax:button', 'Load more', ax_target=AxTarget('button', 'Load more', 0)
    )
    entry = detected_trigger_to_selector_entry(trigger)
    assert entry is not None
    assert (entry.type, entry.value, entry.name, entry.nth) == ('role', 'button', 'Load more', 0)


def test_css_selector_trigger_becomes_css_entry():
    entry = detected_trigger_to_selector_entry(DetectedTrigger(TriggerKind.PAGINATION, 'a.next', 'next'))
    assert entry is not None
    assert (entry.type, entry.value) == ('css', 'a.next')


def test_text_match_trigger_has_no_stable_target():
    """A text-match load-more (selector='button') carries no replayable selector."""
    assert detected_trigger_to_selector_entry(DetectedTrigger(TriggerKind.LOAD_MORE, 'button', 'load more')) is None
    assert detected_trigger_to_selector_entry(DetectedTrigger(TriggerKind.PAGINATION, 'a[href]', 'next')) is None


def test_role_entry_round_trips_to_clickable_trigger():
    original = DetectedTrigger(TriggerKind.PAGINATION, 'ax:link', 'Next', ax_target=AxTarget('link', 'Next', 2))
    entry = detected_trigger_to_selector_entry(original)
    rebuilt = selector_entry_to_detected_trigger(TriggerKind.PAGINATION, entry)
    assert rebuilt.ax_target == AxTarget('link', 'Next', 2)
    assert rebuilt.kind == TriggerKind.PAGINATION


def test_css_entry_round_trips_to_clickable_trigger():
    entry = detected_trigger_to_selector_entry(DetectedTrigger(TriggerKind.ACCORDION, 'details:not([open])', ''))
    rebuilt = selector_entry_to_detected_trigger(TriggerKind.ACCORDION, entry)
    assert rebuilt.ax_target is None
    assert rebuilt.selector == 'details:not([open])'
