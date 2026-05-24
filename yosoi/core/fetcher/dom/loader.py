"""DOM content loader — orchestration and stabilization.

Drives a page to fully-loaded state using a behavior tree. The tree
restarts after any SUCCESS (something happened) and stops when every
node returns FAILURE (nothing left to do).

Stabilization is defined as DOM silence for quiet_ms milliseconds,
detected by an injected MutationObserver.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

from rich.console import Console

from yosoi.core.fetcher.dom.catalogues import CONTENT_SELECTOR
from yosoi.core.fetcher.dom.probes import count_content
from yosoi.core.fetcher.dom.tree.default import build_default_tree
from yosoi.core.fetcher.dom.tree.nodes import Status
from yosoi.storage.a3node import ActRecord

logger = logging.getLogger(__name__)


@dataclass
class LoadResult:
    """Result of a DOMLoader run.

    Attributes:
        success: Whether the page reached a stable, loaded state.
        content_start: Number of content items detected before any actions.
        content_final: Number of content items detected after stabilization.
        elapsed_ms: Total wall-clock time in milliseconds.
        action_log: Ordered list of dicts describing what was done (legacy format).
        html: Full page HTML captured after stabilization, or None on failure.
        acts: Ordered list of ActRecord objects — structured form of action_log,
              suitable for direct storage in A3NodeStorage.

    """

    success: bool
    content_start: int
    content_final: int
    elapsed_ms: float
    action_log: list[dict[str, Any]] = field(default_factory=list)
    html: str | None = None
    acts: list[ActRecord] = field(default_factory=list)

    @property
    def content_gained(self) -> int:
        """Net new items revealed during loading."""
        return self.content_final - self.content_start


class DOMLoader:
    """Loads all content from a page using a behavior tree.

    The tree clears obstacles first, then exhausts content triggers in
    priority order. It restarts after any action succeeds and stops when
    everything returns FAILURE.

    The caller (voiddriver.py) owns A3Node storage — DOMLoader receives
    the tree result and returns ``acts`` for the caller to persist.

    Args:
        max_cycles: Maximum tree restarts before giving up.
        quiet_ms: Milliseconds of DOM silence that counts as stable.
        max_click_cycles: Maximum clicks per trigger before giving up.
        max_scroll_cycles: Maximum scroll iterations before giving up.
        content_selector: CSS selector for counting loaded items.
        console: Optional Rich console for progress output.
    """

    def __init__(
        self,
        max_cycles: int = 20,
        quiet_ms: int = 800,
        max_click_cycles: int = 50,
        max_scroll_cycles: int = 10,
        content_selector: str = CONTENT_SELECTOR,
        console: Console | None = None,
    ) -> None:
        """Initialise the DOMLoader with tuning parameters."""
        self._max_cycles = max_cycles
        self._quiet_ms = quiet_ms
        self._max_click_cycles = max_click_cycles
        self._max_scroll_cycles = max_scroll_cycles
        self._content_selector = content_selector
        self._console = console or Console()

    async def run(self, tab: Any) -> LoadResult:
        """Drive the page to fully-loaded state.

        Builds a fresh behavior tree per run (nodes are stateful).
        Ticks the tree repeatedly until it returns FAILURE.

        Returns a LoadResult with ``acts`` populated from the action log —
        the caller should persist these via A3NodeStorage if the run succeeded.
        """
        start = time.perf_counter()

        tree, logs = build_default_tree(
            quiet_ms=self._quiet_ms,
            content_selector=self._content_selector,
            max_click_cycles=self._max_click_cycles,
            max_scroll_cycles=self._max_scroll_cycles,
        )

        # Initial stabilization before probing
        await tab.wait_for_network_idle(timeout=5.0)
        content_start = await count_content(tab, self._content_selector)
        self._log(f'{content_start} items found initially')

        for _ in range(self._max_cycles):
            result = await tree.tick(tab)
            if result == Status.FAILURE:
                self._log('Nothing left to do — done')
                break
            current = await count_content(tab, self._content_selector)
            self._log(f'{current} items after action')

        html = await self._capture_html(tab)
        content_final = await count_content(tab, self._content_selector)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._log(f'{content_start} → {content_final} items in {elapsed_ms:.0f}ms')

        # Build both legacy action_log and structured acts list from the same source
        action_log = [{'kind': log.kind, 'cycles': log.cycles} for log in logs if log.cycles > 0]
        acts = [ActRecord(kind=log.kind, cycles=log.cycles) for log in logs if log.cycles > 0]

        return LoadResult(
            success=True,
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            action_log=action_log,
            html=html,
            acts=acts,
        )

    async def _capture_html(self, tab: Any) -> str | None:
        """Capture full page HTML after loading is complete."""
        try:
            return str(await tab.content())
        except (RuntimeError, OSError, ValueError) as exc:
            logger.warning('failed to capture HTML: %s', exc)
            return None

    def _log(self, message: str) -> None:
        """Print a progress message."""
        self._console.print(f'[dim]  ↻ DOMLoader: {message}[/dim]')
        logger.info('DOMLoader: %s', message)
