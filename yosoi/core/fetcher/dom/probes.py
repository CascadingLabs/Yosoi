"""Page state probing — obstacles and content triggers.

Both obstacle detection (popups, banners) and trigger detection (load more,
pagination) live here because they share the same job: reading current page
state to decide what needs doing next.

All functions take a tab and return what they found, or None. No actions
are taken here — probing is read-only.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum
from typing import Any

from yosoi.core.fetcher.dom.ax import AxSnapshot, AxTarget, find_target, snapshot
from yosoi.core.fetcher.dom.catalogues import (
    ACCORDION_SELECTORS,
    AGE_GATE_SELECTORS,
    CONTENT_SELECTOR,
    COOKIE_SELECTORS,
    LOAD_MORE_TEXTS,
    NEXT_PAGE_TEXTS,
    PAGINATION_SELECTORS,
    POPUP_SELECTORS,
    TAB_SELECTOR,
)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Trigger kinds
# ---------------------------------------------------------------------------


class TriggerKind(str, Enum):
    """What kind of thing was found on the page.

    Ordered in TRIGGER_PRIORITY so content-appending actions (LOAD_MORE)
    are exhausted before page-navigating ones (PAGINATION).
    """

    COOKIE = 'cookie'
    POPUP = 'popup'
    AGE_GATE = 'age_gate'
    LOAD_MORE = 'load_more'
    ACCORDION = 'accordion'
    TAB = 'tab'
    PAGINATION = 'pagination'
    INFINITE_SCROLL = 'infinite_scroll'


# Obstacles first, then content triggers in priority order.
TRIGGER_PRIORITY = [
    TriggerKind.COOKIE,
    TriggerKind.POPUP,
    TriggerKind.AGE_GATE,
    TriggerKind.LOAD_MORE,
    TriggerKind.ACCORDION,
    TriggerKind.TAB,
    TriggerKind.PAGINATION,
    TriggerKind.INFINITE_SCROLL,
]


@dataclass
class DetectedTrigger:
    """Something found on the page that requires an action."""

    kind: TriggerKind
    selector: str
    label: str
    ax_target: AxTarget | None = None


async def capture_ax_snapshot(tab: Any) -> AxSnapshot | None:
    """Return a compact AX snapshot when the tab exposes browser CDP access."""
    try:
        get_full_ax_tree = tab.get_full_ax_tree
    except AttributeError:
        return None

    try:
        nodes = await get_full_ax_tree()
    except (RuntimeError, OSError, ValueError, TypeError) as exc:
        logger.debug('AX tree probe failed: %s', exc)
        return None
    return snapshot(nodes)


def _snippet_text(snippet: object) -> str:
    """Extract comparable text from a query result without assuming a handle shape."""
    if isinstance(snippet, str):
        return snippet
    for attr in ('text', 'text_content', 'inner_text'):
        value = getattr(snippet, attr, None)
        if isinstance(value, str):
            return value
    return str(snippet) if snippet is not None else ''


# ---------------------------------------------------------------------------
# Obstacle probes
# ---------------------------------------------------------------------------


async def probe_cookie(tab: Any) -> DetectedTrigger | None:
    """Detect a cookie consent banner with an actionable button."""
    try:
        for sel in COOKIE_SELECTORS:
            if await tab.query_selector(sel):
                return DetectedTrigger(TriggerKind.COOKIE, sel, 'accept cookies')
    except (RuntimeError, OSError, ValueError):
        pass
    return None


async def probe_popup(tab: Any) -> DetectedTrigger | None:
    """Detect a modal or popup with a close button."""
    try:
        for sel in POPUP_SELECTORS:
            if await tab.query_selector(sel):
                return DetectedTrigger(TriggerKind.POPUP, sel, 'close popup')
    except (RuntimeError, OSError, ValueError):
        pass
    return None


async def probe_age_gate(tab: Any) -> DetectedTrigger | None:
    """Detect an age verification gate."""
    try:
        for sel in AGE_GATE_SELECTORS:
            if await tab.query_selector(sel):
                return DetectedTrigger(TriggerKind.AGE_GATE, sel, 'pass age gate')
    except (RuntimeError, OSError, ValueError):
        pass
    return None


# ---------------------------------------------------------------------------
# Content trigger probes
# ---------------------------------------------------------------------------


async def probe_load_more(tab: Any) -> DetectedTrigger | None:
    """Detect a load-more / show-more button by text content."""
    snap = await capture_ax_snapshot(tab)
    if snap is not None:
        target = find_target(snap, roles={'button'}, names=tuple(LOAD_MORE_TEXTS))
        if target is not None:
            return DetectedTrigger(TriggerKind.LOAD_MORE, 'ax:button', target.name, ax_target=target)

    try:
        snippets = await tab.query_selector_all('button, a[role="button"], [type="button"]')
        for snippet in snippets:
            lower = _snippet_text(snippet).lower()
            for text in LOAD_MORE_TEXTS:
                if text in lower:
                    return DetectedTrigger(TriggerKind.LOAD_MORE, 'button', text)
    except (RuntimeError, OSError, ValueError) as exc:
        logger.debug('probe_load_more failed: %s', exc)
    return None


async def probe_accordion(tab: Any) -> DetectedTrigger | None:
    """Detect a collapsed accordion section."""
    try:
        for sel in ACCORDION_SELECTORS:
            if await tab.query_selector(sel):
                return DetectedTrigger(TriggerKind.ACCORDION, sel, 'expand accordion')
    except (RuntimeError, OSError, ValueError):
        pass
    return None


async def probe_tab(tab: Any) -> DetectedTrigger | None:
    """Detect an unselected tab panel hiding content."""
    try:
        if await tab.query_selector(TAB_SELECTOR):
            return DetectedTrigger(TriggerKind.TAB, TAB_SELECTOR, 'activate tab')
    except (RuntimeError, OSError, ValueError) as exc:
        logger.debug('probe_tab failed: %s', exc)
    return None


async def probe_pagination(tab: Any) -> DetectedTrigger | None:
    """Detect a next-page link via known selectors then text matching."""
    snap = await capture_ax_snapshot(tab)
    if snap is not None:
        target = find_target(snap, roles={'link'}, names=tuple(NEXT_PAGE_TEXTS), exact=True)
        if target is not None:
            return DetectedTrigger(TriggerKind.PAGINATION, 'ax:link', target.name, ax_target=target)

    try:
        for sel in PAGINATION_SELECTORS:
            if await tab.query_selector(sel):
                return DetectedTrigger(TriggerKind.PAGINATION, sel, 'next page')
        snippets = await tab.query_selector_all('a[href]')
        for snippet in snippets:
            lower = _snippet_text(snippet).lower().strip()
            if any(lower == t or f'>{t}<' in lower for t in NEXT_PAGE_TEXTS):
                return DetectedTrigger(TriggerKind.PAGINATION, 'a[href]', lower)
    except (RuntimeError, OSError, ValueError) as exc:
        logger.debug('probe_pagination failed: %s', exc)
    return None


async def probe_infinite_scroll(tab: Any, content_count: int) -> DetectedTrigger | None:
    """Detect infinite scroll by checking if content count is a round number."""
    if content_count > 0 and content_count % 10 == 0:
        return DetectedTrigger(TriggerKind.INFINITE_SCROLL, 'body', 'scroll to bottom')
    return None


# ---------------------------------------------------------------------------
# Count helper — shared by loader and infinite scroll probe
# ---------------------------------------------------------------------------


async def count_content(tab: Any, selector: str = CONTENT_SELECTOR) -> int:
    """Count extractable content items currently visible in the DOM."""
    try:
        return len(await tab.query_selector_all(selector))
    except (RuntimeError, OSError, ValueError):
        return 0


# ---------------------------------------------------------------------------
# Dispatch — maps TriggerKind to its probe function
# ---------------------------------------------------------------------------


async def probe(tab: Any, kind: TriggerKind, content_count: int = 0) -> DetectedTrigger | None:
    """Run the probe for a single trigger kind."""
    if kind == TriggerKind.COOKIE:
        return await probe_cookie(tab)
    if kind == TriggerKind.POPUP:
        return await probe_popup(tab)
    if kind == TriggerKind.AGE_GATE:
        return await probe_age_gate(tab)
    if kind == TriggerKind.LOAD_MORE:
        return await probe_load_more(tab)
    if kind == TriggerKind.ACCORDION:
        return await probe_accordion(tab)
    if kind == TriggerKind.TAB:
        return await probe_tab(tab)
    if kind == TriggerKind.PAGINATION:
        return await probe_pagination(tab)
    if kind == TriggerKind.INFINITE_SCROLL:
        return await probe_infinite_scroll(tab, content_count)
    return None
