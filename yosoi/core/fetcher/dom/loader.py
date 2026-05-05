"""DOM content loader — orchestration and stabilization.

Drives a page to fully-loaded state by working through trigger types in
priority order. For each trigger found, an inner loop exhausts it before
the outer loop restarts from the top. When a full pass finds nothing, the
page is done.

Stabilization is defined here: the page is stable when the MutationObserver
reports DOM silence for quiet_ms milliseconds, or when a hard timeout is
reached.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console

from yosoi.core.fetcher.dom.actions import WaitForDOMStable, build_flow
from yosoi.core.fetcher.dom.catalogues import CONTENT_SELECTOR
from yosoi.core.fetcher.dom.probes import (
    TRIGGER_PRIORITY,
    TriggerKind,
    count_content,
    probe,
)

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """Result of a DOMLoader run."""

    success: bool
    content_start: int
    content_final: int
    elapsed_ms: float
    trigger_kinds: set[TriggerKind] = field(default_factory=set)
    html: str | None = None

    @property
    def content_gained(self) -> int:
        """Net new items revealed during loading."""
        return self.content_final - self.content_start


class DOMLoader:
    """Loads all content from a page using a priority-ordered trigger loop.

    The page is considered stable when no meaningful DOM mutations have
    occurred for quiet_ms milliseconds. Obstacles (cookies, popups) are
    cleared first, then content triggers (load more, pagination, scroll)
    are exhausted in priority order.

    Args:
        max_outer_cycles: Maximum outer loop restarts before giving up.
        quiet_ms: Milliseconds of DOM silence that counts as stable.
        max_inner_cycles: Maximum acts per trigger type before moving on.
        max_scroll_cycles: Hard cap on infinite scroll iterations.
        content_selector: CSS selector for counting loaded items.
        console: Optional Rich console for progress output.
    """

    def __init__(
        self,
        max_outer_cycles: int = 10,
        quiet_ms: int = 800,
        max_inner_cycles: int = 50,
        max_scroll_cycles: int = 10,
        content_selector: str | None = None,
        console: Console | None = None,
    ) -> None:
        """Initialise the DOMLoader with tuning parameters."""
        self._max_outer = max_outer_cycles
        self._max_inner = max_inner_cycles
        self._max_scroll = max_scroll_cycles
        self._content_selector = content_selector or CONTENT_SELECTOR
        self._console = console or Console()
        self._stable = WaitForDOMStable(quiet_ms=quiet_ms)

    async def run(self, tab: Any) -> LoadResult:
        """Drive the page to fully-loaded state.

        Outer loop iterates trigger types in priority order. When a trigger
        is found, the inner loop exhausts it, then the outer loop restarts
        from the top. Stops when a full pass finds no triggers.
        """
        start = time.perf_counter()
        trigger_kinds: set[TriggerKind] = set()

        # Wait for initial page load before doing anything
        await self._wait_stable(tab)
        content_start = await count_content(tab, self._content_selector)
        self._log(f'{content_start} items found initially')

        exhausted: set[TriggerKind] = set()

        for outer in range(self._max_outer):
            found_any = False
            current_count = await count_content(tab, self._content_selector)

            for kind in TRIGGER_PRIORITY:
                if kind in exhausted:
                    continue

                trigger = await probe(tab, kind, content_count=current_count)
                if trigger is None:
                    continue

                found_any = True
                trigger_kinds.add(kind)
                self._log(f'[{kind.value}] found: {trigger.label!r}')

                inner_limit = self._max_scroll if kind == TriggerKind.INFINITE_SCROLL else self._max_inner

                for _ in range(inner_limit):
                    prev = await count_content(tab, self._content_selector)
                    flow = build_flow(trigger, self._stable)
                    if flow is None:
                        exhausted.add(kind)
                        break
                    await flow.run(tab)
                    new = await count_content(tab, self._content_selector)
                    self._log(f'  [{kind.value}] {prev} → {new} items')
                    if new <= prev:
                        self._log(f'  [{kind.value}] no growth — exhausted')
                        exhausted.add(kind)
                        break
                    next_trigger = await probe(tab, kind, content_count=new)
                    if next_trigger is None:
                        self._log(f'  [{kind.value}] trigger gone — exhausted')
                        exhausted.add(kind)
                        break

                break

            if not found_any:
                self._log(f'No triggers found in pass {outer + 1} — done')
                break

        html = await self._capture_html(tab)
        content_final = await count_content(tab, self._content_selector)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._log(f'{content_start} → {content_final} items in {elapsed_ms:.0f}ms')

        return LoadResult(
            success=True,
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            trigger_kinds=trigger_kinds,
            html=html,
        )

    async def _wait_stable(self, tab: Any) -> None:
        """Run the DOM stability check synchronously via Flow."""
        from voidcrawl.actions import Flow

        await Flow([self._stable]).run(tab)

    async def _capture_html(self, tab: Any) -> str | None:
        try:
            return await tab.content()
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning('failed to capture HTML: %s', exc)
            return None

    def _log(self, message: str) -> None:
        self._console.print(f'[dim]  ↻ DOMLoader: {message}[/dim]')
        logger.info('DOMLoader: %s', message)
