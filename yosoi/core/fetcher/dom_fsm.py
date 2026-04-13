"""Universal DOM finite state machine.

Probes any page and drives it to READY state using heuristic
detect-act cycles — no domain knowledge, no hand-authored scripts.

The FSM works in three phases per cycle:
    1. Probe  — scan the DOM for known "more content" triggers
    2. Act    — fire the best trigger found
    3. Settle — wait for the DOM to stabilise after the action

The loop continues until:
    - No trigger is found (READY — page is fully loaded)
    - Content count stops growing after an act (READY — trigger exhausted)
    - Max cycles reached (READY — best-effort result)
    - An unrecoverable error occurs (ERRORED)

Relationship to a3node.py
--------------------------
DOMProber is the *universal fallback* that works on any site without
prior knowledge. A3Node is the *recorded optimisation* — a cached,
pre-compiled version of what DOMProber would have done.

Typical pipeline:
    First visit  → DOMProber probes → records steps → saves A3Node
    Later visits → A3Node replays recording at zero LLM cost
    Replay fails → DOMProber re-probes → updates A3Node

Integration point: voiddriver._do_fetch calls DOMProber unconditionally.
A3Node auto-recording from ProbeResult is future work.
"""

from __future__ import annotations

import asyncio
import logging
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from rich.console import Console

logger = logging.getLogger(__name__)


# ── FSM states ────────────────────────────────────────────────────────────────


class ProbeState(str, Enum):
    """States of the universal DOM prober FSM.

    Attributes:
        SETTLING:  Waiting for initial page load to stabilise.
        PROBING:   Scanning DOM for triggers that reveal more content.
        ACTING:    Executing a found trigger.
        READY:     No more triggers found; content is fully loaded.
        ERRORED:   Unrecoverable error; content state unknown.
    """

    SETTLING = 'settling'
    PROBING = 'probing'
    ACTING = 'acting'
    READY = 'ready'
    ERRORED = 'errored'


# ── Trigger types ─────────────────────────────────────────────────────────────


class TriggerKind(str, Enum):
    """Category of DOM trigger that reveals additional content.

    Attributes:
        LOAD_MORE:       Button that appends items to the current page.
        PAGINATION:      Link/button that navigates to a next page.
        INFINITE_SCROLL: Page that loads content when scrolled to bottom.
        ACCORDION:       Collapsed section that expands on click.
        TAB:             Tab that reveals hidden content on click.
    """

    LOAD_MORE = 'load_more'
    PAGINATION = 'pagination'
    INFINITE_SCROLL = 'infinite_scroll'
    ACCORDION = 'accordion'
    TAB = 'tab'


@dataclass
class DetectedTrigger:
    """A trigger found during a probe cycle.

    Attributes:
        kind:     Category of the trigger.
        selector: CSS selector that locates the trigger element.
        label:    Human-readable description for logging and recording.
        priority: Higher = tried first when multiple triggers are found.
    """

    kind: TriggerKind
    selector: str
    label: str
    priority: int = 0


@dataclass
class ActRecord:
    """One detect-act cycle recorded during a probe run.

    Used to reconstruct an A3Node from a successful probe session.

    Attributes:
        kind:           The trigger category that was acted on.
        selector:       CSS selector used to find and act on the trigger.
        label:          Human-readable description.
        content_before: Item count before the act.
        content_after:  Item count after the act.
        elapsed_ms:     Time from act to DOM settle in milliseconds.
    """

    kind: TriggerKind
    selector: str
    label: str
    content_before: int
    content_after: int
    elapsed_ms: float


# ── Probe result ──────────────────────────────────────────────────────────────


@dataclass
class ProbeResult:
    """Result of a complete DOMProber run.

    Attributes:
        state:         Final FSM state reached.
        cycles:        Number of detect-act cycles completed.
        content_start: Item count when probing began.
        content_final: Item count when probing ended.
        elapsed_ms:    Total wall-clock time in milliseconds.
        acts:          Ordered list of actions taken, for A3Node recording.
        trigger_kinds: Set of trigger categories encountered.
        html:          Full page HTML captured after probing completed.
    """

    state: ProbeState
    cycles: int
    content_start: int
    content_final: int
    elapsed_ms: float
    acts: list[ActRecord] = field(default_factory=list)
    trigger_kinds: set[TriggerKind] = field(default_factory=set)
    html: str | None = None

    @property
    def succeeded(self) -> bool:
        """True if the prober reached READY state."""
        return self.state == ProbeState.READY

    @property
    def content_gained(self) -> int:
        """Net new items revealed by the prober."""
        return self.content_final - self.content_start


# ── Trigger catalogue ─────────────────────────────────────────────────────────

_LOAD_MORE_TEXTS = (
    'load more',
    'show more',
    'view more',
    'see more',
    'more results',
    'more articles',
    'more posts',
    'more items',
    'load additional',
    'show additional',
    'expand',
    'remaining',
)

_NEXT_PAGE_TEXTS = (
    'next',
    'next page',
    'older posts',
    'older entries',
    '\u00bb',
    '\u203a',
    'forward',
)

_PAGINATION_SELECTORS = (
    'a[rel="next"]',
    'a[aria-label="Next"]',
    'a[aria-label="next"]',
    'a.next',
    'a.pagination-next',
    '.pagination a[href]:last-child',
    'nav[aria-label="pagination"] a:last-child',
    '[data-testid="next-page"]',
    '[data-cy="next-page"]',
    'button[aria-label="next page"]',
    'button[aria-label="Next page"]',
)


# ── Universal DOM prober ──────────────────────────────────────────────────────


class DOMProber:
    """Universal DOM finite state machine for any website.

    Drives a page from initial load to fully-expanded READY state
    using heuristic detect-act cycles. Works without any domain
    knowledge — suitable as a universal fallback when no A3Node exists.

    The prober is stateless — one instance can run concurrently
    across multiple tabs without any locking.

    Args:
        max_cycles: Maximum detect-act loops before declaring READY.
            Prevents infinite loops on pathological sites. Default 10.
        settle_timeout: Seconds to wait for DOM stability after each act.
            Default 8.0.
        scroll_pause: Seconds to wait after a scroll act before
            checking whether new content appeared. Default 2.0.
        content_selector: CSS selector for counting extractable items.
            Defaults to a broad heuristic covering most listing patterns.
    """

    _DEFAULT_CONTENT_SELECTOR = (
        'article, [data-article-id], [data-item], [data-product-id], .card, .item, .result, .listing, .post, .entry'
    )

    def __init__(
        self,
        max_cycles: int = 10,
        settle_timeout: float = 8.0,
        scroll_pause: float = 2.0,
        content_selector: str | None = None,
        console: Console | None = None,
    ) -> None:
        """Initialise the prober with tuning parameters."""
        self._max_cycles = max_cycles
        self._settle_timeout = settle_timeout
        self._scroll_pause = scroll_pause
        self._content_selector = content_selector or self._DEFAULT_CONTENT_SELECTOR
        self._console = console or Console()

    async def run(self, tab: Any) -> ProbeResult:
        """Drive a page to READY state using heuristic detect-act cycles.

        Args:
            tab: A live voidcrawl PooledTab or Page instance.

        Returns:
            ProbeResult describing what was done and the final state.
            ProbeResult.html contains the full page HTML captured after
            all cycles complete, ready for the pipeline to process.
        """
        start = time.perf_counter()
        acts: list[ActRecord] = []
        trigger_kinds: set[TriggerKind] = set()

        # ── Phase 1: initial settle ───────────────────────────────────────
        logger.debug('DOMProber: initial settle')
        self._console.print('[dim]  ↻ DOM prober: initial settle...[/dim]')
        try:
            await tab.wait_for_stable_dom(
                timeout=self._settle_timeout,
                min_length=1000,
                stable_checks=3,
            )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('DOMProber: initial settle timed out: %s', exc)

        content_start = await self._count_content(tab)
        logger.info('DOMProber: starting content count = %d', content_start)
        self._console.print(f'[dim]  ↻ DOM prober: {content_start} items found initially[/dim]')

        # ── Phase 2: detect-act loop ──────────────────────────────────────
        prev_count = content_start
        for cycle in range(self._max_cycles):
            logger.debug('DOMProber: cycle %d/%d, content=%d', cycle + 1, self._max_cycles, prev_count)

            trigger = await self._probe(tab)

            if trigger is None:
                logger.info('DOMProber: no trigger found — READY after %d cycles', cycle)
                break

            logger.info('DOMProber: found trigger %r (%s)', trigger.label, trigger.kind.value)
            self._console.print(
                f'[dim]  ↻ DOM prober: cycle {cycle + 1} — found trigger [{trigger.kind.value}] {trigger.label!r}[/dim]'
            )
            trigger_kinds.add(trigger.kind)

            act_start = time.perf_counter()
            acted = await self._act(tab, trigger)
            if not acted:
                logger.debug('DOMProber: act failed — stopping')
                break

            await self._settle(tab, trigger.kind)
            act_elapsed = (time.perf_counter() - act_start) * 1000

            new_count = await self._count_content(tab)
            logger.info(
                'DOMProber: cycle %d complete — content %d \u2192 %d (+%d) in %.0fms',
                cycle + 1,
                prev_count,
                new_count,
                new_count - prev_count,
                act_elapsed,
            )
            self._console.print(
                f'[dim]  ↻ DOM prober: cycle {cycle + 1} complete — {prev_count} → {new_count} items (+{new_count - prev_count})[/dim]'
            )

            acts.append(
                ActRecord(
                    kind=trigger.kind,
                    selector=trigger.selector,
                    label=trigger.label,
                    content_before=prev_count,
                    content_after=new_count,
                    elapsed_ms=act_elapsed,
                )
            )

            if new_count <= prev_count:
                logger.info('DOMProber: content did not grow — READY')
                break

            prev_count = new_count

        content_final = await self._count_content(tab)
        elapsed_ms = (time.perf_counter() - start) * 1000

        # Capture HTML while tab is still live
        captured_html: str | None = None
        try:
            captured_html = await tab.content()
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning('DOMProber: failed to capture HTML: %s', exc)

        logger.info(
            'DOMProber: complete — %d\u2192%d items, %d acts, %.0fms',
            content_start,
            content_final,
            len(acts),
            elapsed_ms,
        )
        self._console.print(
            f'[success]  ↻ DOM prober: READY — {content_start} → {content_final} items in {elapsed_ms:.0f}ms[/success]'
        )

        return ProbeResult(
            state=ProbeState.READY,
            cycles=len(acts),
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            acts=acts,
            trigger_kinds=trigger_kinds,
            html=captured_html,
        )

    # ── Probe ─────────────────────────────────────────────────────────────────

    async def _probe(self, tab: Any) -> DetectedTrigger | None:
        """Scan the DOM for the highest-priority available trigger.

        Args:
            tab: Live browser tab.

        Returns:
            The best DetectedTrigger found, or None if none present.
        """
        candidates: list[DetectedTrigger] = []

        load_more = await self._find_load_more(tab)
        if load_more:
            candidates.append(load_more)

        pagination = await self._find_pagination(tab)
        if pagination:
            candidates.append(pagination)

        if not candidates:
            scroll = await self._detect_infinite_scroll(tab)
            if scroll:
                candidates.append(scroll)

        if not candidates:
            return None

        return max(candidates, key=lambda t: t.priority)

    async def _find_load_more(self, tab: Any) -> DetectedTrigger | None:
        """Find a load-more / show-more button by text content.

        Args:
            tab: Live browser tab.

        Returns:
            DetectedTrigger if a matching button is found, else None.
        """
        try:
            buttons = await tab.query_selector_all('button, a[role="button"], [type="button"]')
            for html in buttons:
                if not html:
                    continue
                lower = html.lower()
                for text in _LOAD_MORE_TEXTS:
                    if text in lower:
                        return DetectedTrigger(
                            kind=TriggerKind.LOAD_MORE,
                            selector='button, a[role="button"], [type="button"]',
                            label=text,
                            priority=10,
                        )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('DOMProber: load-more probe failed: %s', exc)
        return None

    async def _find_pagination(self, tab: Any) -> DetectedTrigger | None:
        """Find a next-page link using known CSS selector patterns.

        Args:
            tab: Live browser tab.

        Returns:
            DetectedTrigger if a pagination element is found, else None.
        """
        try:
            for sel in _PAGINATION_SELECTORS:
                result = await tab.query_selector(sel)
                if result is not None:
                    return DetectedTrigger(
                        kind=TriggerKind.PAGINATION,
                        selector=sel,
                        label='next page',
                        priority=8,
                    )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('DOMProber: pagination selector probe failed: %s', exc)

        try:
            links = await tab.query_selector_all('a[href]')
            for html in links:
                if not html:
                    continue
                lower = html.lower()
                for text in _NEXT_PAGE_TEXTS:
                    if lower.strip() == text or f'>{text}<' in lower:
                        return DetectedTrigger(
                            kind=TriggerKind.PAGINATION,
                            selector='a[href]',
                            label=text,
                            priority=7,
                        )
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('DOMProber: pagination probe failed: %s', exc)

        return None

    async def _detect_infinite_scroll(self, tab: Any) -> DetectedTrigger | None:
        """Detect pages that load content when scrolled to the bottom.

        Heuristic: if content count is a round number (multiple of common
        page sizes like 10, 20, 25), the page likely has more content
        below the fold loaded via infinite scroll.

        Args:
            tab: Live browser tab.

        Returns:
            DetectedTrigger for scroll if infinite scroll is likely, else None.
        """
        count = await self._count_content(tab)
        if count > 0 and count % 10 == 0:
            logger.debug('DOMProber: content count %d is round — trying infinite scroll', count)
            return DetectedTrigger(
                kind=TriggerKind.INFINITE_SCROLL,
                selector='body',
                label='scroll to bottom',
                priority=3,
            )
        return None

    # ── Act ───────────────────────────────────────────────────────────────────

    async def _act(self, tab: Any, trigger: DetectedTrigger) -> bool:
        """Execute a detected trigger.

        Args:
            tab: Live browser tab.
            trigger: The trigger to act on.

        Returns:
            True if the action was executed, False if it could not be found.
        """
        try:
            if trigger.kind == TriggerKind.INFINITE_SCROLL:
                await tab.evaluate_js('window.scrollTo(0, document.body.scrollHeight)')
                await asyncio.sleep(self._scroll_pause)
                return True

            if trigger.kind == TriggerKind.LOAD_MORE:
                needle = trigger.label
                clicked = await tab.evaluate_js(
                    f"""(() => {{
                        const els = [...document.querySelectorAll(
                            'button, a[role="button"], [type="button"]'
                        )];
                        const el = els.find(e =>
                            e.textContent.toLowerCase().includes({needle!r})
                        );
                        if (el) {{ el.click(); return true; }}
                        return false;
                    }})()"""
                )
                return bool(clicked)

            if trigger.kind == TriggerKind.PAGINATION:
                el = await tab.query_selector(trigger.selector)
                if el is not None:
                    await tab.click_element(trigger.selector)
                    return True
                needle = trigger.label
                clicked = await tab.evaluate_js(
                    f"""(() => {{
                        const els = [...document.querySelectorAll('a[href]')];
                        const el = els.find(e =>
                            e.textContent.trim().toLowerCase() === {needle!r}
                        );
                        if (el) {{ el.click(); return true; }}
                        return false;
                    }})()"""
                )
                return bool(clicked)

        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('DOMProber: act failed for %r: %s', trigger.label, exc)

        return False

    # ── Settle ────────────────────────────────────────────────────────────────

    async def _settle(self, tab: Any, kind: TriggerKind) -> None:
        """Wait for the DOM to stabilise after an act.

        Uses wait_for_stable_dom for load-more/pagination and a fixed
        pause for scroll acts.

        Args:
            tab: Live browser tab.
            kind: The kind of trigger that was just acted on.
        """
        if kind == TriggerKind.INFINITE_SCROLL:
            await asyncio.sleep(self._scroll_pause)
            return
        try:
            await tab.wait_for_stable_dom(
                timeout=self._settle_timeout,
                min_length=1000,
                stable_checks=3,
            )
        except (RuntimeError, OSError, ValueError):
            await asyncio.sleep(1.0)

    # ── Content count ─────────────────────────────────────────────────────────

    async def _count_content(self, tab: Any) -> int:
        """Count extractable items currently in the DOM.

        Args:
            tab: Live browser tab.

        Returns:
            Number of elements matching the content selector.
        """
        try:
            results = await tab.query_selector_all(self._content_selector)
            return len(results)
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('DOMProber: content count failed: %s', exc)
            return 0
