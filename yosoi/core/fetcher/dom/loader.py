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
from voidcrawl.actions import Flow

from yosoi.core.fetcher.dom.catalogues import CONTENT_SELECTOR
from yosoi.core.fetcher.dom.flows import WaitForDOMStable, build_flow
from yosoi.core.fetcher.dom.probes import TriggerKind, count_content, selector_entry_to_detected_trigger
from yosoi.core.fetcher.dom.tree.actions import ClickTrigger, Scroll
from yosoi.core.fetcher.dom.tree.conditions import HasTrigger
from yosoi.core.fetcher.dom.tree.default import build_default_tree
from yosoi.core.fetcher.dom.tree.nodes import Status
from yosoi.models.selectors import SelectorEntry
from yosoi.storage.a3node import A3_FRAGMENT_BANK_KINDS, A3Fragment, ActRecord

# Trigger kinds that appear in a stored recipe (the ones that carry an ActionLog).
# Concrete targets are replayed directly; targetless legacy acts still re-probe.
_CLICK_KINDS = {
    TriggerKind.COOKIE.value,
    TriggerKind.POPUP.value,
    TriggerKind.AGE_GATE.value,
    TriggerKind.LOAD_MORE.value,
    TriggerKind.ACCORDION.value,
    TriggerKind.TAB.value,
    TriggerKind.PAGINATION.value,
}
_SCROLL_KIND = TriggerKind.INFINITE_SCROLL.value

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
        acts = [ActRecord(kind=log.kind, cycles=log.cycles, target=log.target) for log in logs if log.cycles > 0]

        return LoadResult(
            success=True,
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            action_log=action_log,
            html=html,
            acts=acts,
        )

    async def replay_fragments(self, tab: Any, fragments: list[A3Fragment]) -> LoadResult:
        """Apply reusable domain-free fragments before scoped probing.

        Fragments are assess/act/assert in miniature: assess is the durable target
        still being present, act is the stored click target, and assert is that the
        click executed without raising. The normal DOMLoader probe runs after this,
        so a fragment miss or stale candidate never becomes the only path to content.
        """
        start = time.perf_counter()
        stable = WaitForDOMStable(quiet_ms=self._quiet_ms)
        content_start = await count_content(tab, self._content_selector)
        executed: list[ActRecord] = []

        for fragment in fragments:
            act = fragment.to_act()
            if act.target is None or act.kind not in A3_FRAGMENT_BANK_KINDS:
                continue
            if not await self._target_present(tab, act.target):
                continue
            try:
                cycles = await self._replay_target(tab, act.kind, act.target, stable)
            except (RuntimeError, OSError, ValueError, TypeError) as exc:
                logger.debug('fragment replay failed for %s: %s', fragment.fragment_key, exc)
                continue
            if cycles > 0:
                executed.append(ActRecord(kind=act.kind, cycles=cycles, target=act.target))
                self._log(f'fragment: {act.kind} ran {cycles} cycle(s) via reusable target')

        html = await self._capture_html(tab)
        content_final = await count_content(tab, self._content_selector)
        elapsed_ms = (time.perf_counter() - start) * 1000
        return LoadResult(
            success=html is not None,
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            action_log=[{'kind': a.kind, 'cycles': a.cycles} for a in executed],
            html=html,
            acts=executed,
        )

    async def replay(self, tab: Any, acts: list[ActRecord]) -> LoadResult:
        """Re-execute a stored act sequence directly, skipping trigger discovery.

        This is the "action replay" tier of an A3 node (CAS-75): the recorded
        triggers are run in order using the same action primitives the probe
        uses — each action still loops to exhaustion and settles the DOM — but
        without searching the full behavior tree over trigger kinds the page does
        not use, and with no LLM in the loop. That makes a repeat visit faster
        and deterministic.

        ``success`` is False when replay reached no content, so the caller can
        fall back to a full :meth:`run` probe.

        Args:
            tab: The browser tab to drive.
            acts: The stored ordered recipe to replay.

        Returns:
            A LoadResult whose ``acts`` reflect what actually executed (cycle
            counts may differ from the recipe, since each action re-derives its
            own stopping point from live content growth).
        """
        start = time.perf_counter()
        stable = WaitForDOMStable(quiet_ms=self._quiet_ms)

        await tab.wait_for_network_idle(timeout=5.0)
        content_start = await count_content(tab, self._content_selector)
        self._log(f'replay: {content_start} items initially, replaying {len(acts)} act(s)')

        executed: list[ActRecord] = []
        for act in acts:
            # Selector-level replay: a stored concrete target is clicked directly, so the
            # hand-maintained discovery catalogues never run on the replay hot path (CAS-94).
            if act.target is not None and act.kind in _CLICK_KINDS:
                if not await self._target_present(tab, act.target):
                    self._log(f'replay: {act.kind} stored target absent — skipping')
                    continue
                try:
                    cycles = await self._replay_target(tab, act.kind, act.target, stable)
                except (RuntimeError, OSError, ValueError, TypeError) as exc:
                    logger.debug('stored-target replay failed for %s: %s', act.kind, exc)
                    continue
                if cycles > 0:
                    executed.append(ActRecord(kind=act.kind, cycles=cycles, target=act.target))
                    self._log(f'replay: {act.kind} ran {cycles} cycle(s) via stored target')
                continue

            # Fallback path: scroll acts, or a click act with no stored target (a format-1
            # recipe or a text-match act) — re-probe via the catalogues seed.
            built = self._build_replay_action(act.kind, stable)
            if built is None:
                self._log(f'replay: skipping unsupported act kind {act.kind!r}')
                continue
            if act.target is None and act.kind in _CLICK_KINDS:
                self._log(f'replay: {act.kind} has no stored target — falling back to probe')
            condition, action = built
            # Populate last_trigger for ClickTrigger; Scroll ignores it. A missing
            # trigger makes ClickTrigger a no-op (cycles stays 0), which we skip.
            await condition.tick(tab)
            await action.tick(tab)
            if action.log.cycles > 0:
                executed.append(ActRecord(kind=act.kind, cycles=action.log.cycles, target=act.target))
                self._log(f'replay: {act.kind} ran {action.log.cycles} cycle(s)')

        html = await self._capture_html(tab)
        content_final = await count_content(tab, self._content_selector)
        elapsed_ms = (time.perf_counter() - start) * 1000
        self._log(f'replay: {content_start} → {content_final} items in {elapsed_ms:.0f}ms')

        return LoadResult(
            success=html is not None and content_final > 0,
            content_start=content_start,
            content_final=content_final,
            elapsed_ms=elapsed_ms,
            action_log=[{'kind': a.kind, 'cycles': a.cycles} for a in executed],
            html=html,
            acts=executed,
        )

    def _build_replay_action(
        self, kind: str, stable: WaitForDOMStable
    ) -> tuple[HasTrigger, ClickTrigger | Scroll] | None:
        """Build the (condition, action) pair that re-executes one stored act kind.

        Returns None for kinds that are not replayable triggers.
        """
        if kind == _SCROLL_KIND:
            condition = HasTrigger(TriggerKind.INFINITE_SCROLL, self._content_selector)
            return condition, Scroll(condition, stable, self._max_scroll_cycles)
        if kind in _CLICK_KINDS:
            condition = HasTrigger(TriggerKind(kind), self._content_selector)
            return condition, ClickTrigger(condition, stable, self._max_click_cycles)
        return None

    async def _target_present(self, tab: Any, target: SelectorEntry) -> bool:
        """Return whether a stored fragment target is present before acting."""
        try:
            if target.type == 'css':
                return bool(await tab.query_selector(target.value))
            if target.type == 'role':
                from yosoi.core.fetcher.dom.probes import capture_ax_snapshot

                snap = await capture_ax_snapshot(tab)
                if snap is None:
                    return False
                nth = target.nth or 0
                matches = [t for t in snap.targets if t.role == target.value and t.name == (target.name or '')]
                return len(matches) > nth
        except (RuntimeError, OSError, ValueError, TypeError):
            return False
        return False

    async def _replay_target(self, tab: Any, kind: str, target: SelectorEntry, stable: WaitForDOMStable) -> int:
        """Replay one click act against its stored target — no probe, no catalogues.

        Rebuilds a DetectedTrigger from the stored ``SelectorEntry`` and clicks it in a
        growth loop, stopping once content stops growing. Returns the executed cycle
        count (0 means the target produced no growth, so the caller drops the act and a
        higher layer can fall back to a full probe).
        """
        trigger = selector_entry_to_detected_trigger(TriggerKind(kind), target)
        cycles = 0
        for _ in range(self._max_click_cycles):
            prev = await count_content(tab, self._content_selector)
            flow = build_flow(trigger, stable)
            if flow is None:
                break
            await flow.run(tab)
            cycles += 1
            new = await count_content(tab, self._content_selector)
            self._log(f'replay-target [{kind}]: {prev} → {new} items')
            if new <= prev:
                break
        # Final settle so late-rendered content is present before HTML capture.
        await Flow([stable]).run(tab)
        return cycles

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
