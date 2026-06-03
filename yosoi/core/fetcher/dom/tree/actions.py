"""Action nodes — interact with the page, never just read it.

Each action returns SUCCESS if the interaction worked and produced
a meaningful result, FAILURE otherwise. Actions that exhaust a trigger
call exhaust() on the paired HasTrigger condition so the tree skips
it on subsequent restarts.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Any

from voidcrawl.actions import Flow, ScrollTo

from yosoi.core.fetcher.dom.flows import WaitForDOMStable, build_flow
from yosoi.core.fetcher.dom.probes import count_content, detected_trigger_to_selector_entry
from yosoi.core.fetcher.dom.tree.conditions import HasTrigger
from yosoi.core.fetcher.dom.tree.nodes import Node, Status
from yosoi.models.selectors import SelectorEntry

logger = logging.getLogger(__name__)


@dataclass
class ActionLog:
    """Record of what a single action node did during a tree run.

    Used after the tree completes to build a domain stability recipe.

    Attributes:
        kind: What type of action was taken.
        cycles: How many times the action was repeated.
        target: The concrete winning selector for this action (for selector-level
            replay), or None for scroll / text-match actions that carry no stable target.
    """

    kind: str
    cycles: int = 0
    target: SelectorEntry | None = None


class ClickClose(Node):
    """Find and click a close/dismiss button on an overlay."""

    async def tick(self, tab: Any) -> Status:
        """Click the first close button found."""
        try:
            # FUTURE: generalize these close/dismiss selectors into a configurable
            # overlay catalogue instead of keeping site-shape guesses inline.
            for sel in (
                '[role="dialog"] [aria-label*="close" i]',
                '[role="dialog"] button[class*="close"]',
                '.modal [class*="close"]',
                '[class*="popup"] [class*="close"]',
                '[class*="overlay"] [class*="close"]',
                'button[aria-label*="dismiss" i]',
            ):
                if await tab.query_selector(sel):
                    await tab.click_element(sel)
                    logger.debug('ClickClose: clicked %s', sel)
                    return Status.SUCCESS
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('ClickClose failed: %s', exc)
        return Status.FAILURE


class ClickTrigger(Node):
    """Click a content trigger until exhausted or content stops growing.

    Paired with a HasTrigger condition — calls exhaust() on it when
    the trigger is done so the tree skips it on subsequent restarts.

    A final WaitForDOMStable runs after the last cycle completes so
    all newly rendered content is present before the caller reads HTML.

    Attributes:
        log: ActionLog recording how many cycles were completed.
    """

    def __init__(
        self,
        condition: HasTrigger,
        stable: WaitForDOMStable,
        max_cycles: int = 50,
    ) -> None:
        """Initialise paired with a HasTrigger condition.

        Args:
            condition: The paired HasTrigger that detected this trigger.
            stable: Shared WaitForDOMStable instance for this session.
            max_cycles: Maximum clicks before giving up.
        """
        self._condition = condition
        self._stable = stable
        self._max_cycles = max_cycles
        self.log = ActionLog(kind=condition._kind.value)

    async def tick(self, tab: Any) -> Status:
        """Click the trigger in a loop until exhausted."""
        trigger = self._condition.last_trigger
        if trigger is None:
            return Status.FAILURE

        # Record the concrete winning target once, so replay can click it directly
        # instead of re-running the discovery catalogues (CAS-94).
        if self.log.target is None:
            self.log.target = detected_trigger_to_selector_entry(trigger)

        content_selector = self._condition._content_selector

        # FUTURE: add a contract/config-level max-items primitive. Count-growth
        # alone can over-click near-infinite feeds such as X or Yahoo Finance.
        for _ in range(self._max_cycles):
            prev = await count_content(tab, content_selector)
            flow = build_flow(trigger, self._stable)
            if flow is None:
                self._condition.exhaust()
                await Flow([self._stable]).run(tab)
                return Status.FAILURE

            await flow.run(tab)
            self.log.cycles += 1
            new = await count_content(tab, content_selector)

            logger.debug('ClickTrigger [%s]: %d → %d items', trigger.kind.value, prev, new)

            if new <= prev:
                self._condition.exhaust()
                # Final settle — content stopped growing, wait for last render
                await Flow([self._stable]).run(tab)
                return Status.SUCCESS

            # Check if trigger is still present
            from yosoi.core.fetcher.dom.probes import probe

            next_trigger = await probe(tab, trigger.kind, content_count=new)
            if next_trigger is None:
                self._condition.exhaust()
                # Final settle — trigger gone, wait for last render
                await Flow([self._stable]).run(tab)
                return Status.SUCCESS
            trigger = next_trigger

        self._condition.exhaust()
        # Final settle — max cycles reached, wait for last render
        await Flow([self._stable]).run(tab)
        return Status.SUCCESS


class Scroll(Node):
    """Scroll to the bottom of the page to trigger infinite scroll loading.

    Paired with a HasTrigger(INFINITE_SCROLL) condition.

    Attributes:
        log: ActionLog recording how many scroll cycles were completed.
    """

    def __init__(
        self,
        condition: HasTrigger,
        stable: WaitForDOMStable,
        max_cycles: int = 10,
    ) -> None:
        """Initialise paired with a HasTrigger condition.

        Args:
            condition: The paired HasTrigger(INFINITE_SCROLL) condition.
            stable: Shared WaitForDOMStable instance for this session.
            max_cycles: Maximum scroll iterations before giving up.
        """
        self._condition = condition
        self._stable = stable
        self._max_cycles = max_cycles
        self.log = ActionLog(kind='infinite_scroll')

    async def tick(self, tab: Any) -> Status:
        """Scroll to bottom in a loop until content stops growing."""
        content_selector = self._condition._content_selector

        for _ in range(self._max_cycles):
            prev = await count_content(tab, content_selector)
            await Flow([ScrollTo(x=0, y=999_999), self._stable]).run(tab)
            self.log.cycles += 1
            new = await count_content(tab, content_selector)

            logger.debug('Scroll: %d → %d items', prev, new)

            if new <= prev:
                self._condition.exhaust()
                # Final settle — content stopped growing, wait for last render
                await Flow([ScrollTo(x=0, y=999_999), self._stable]).run(tab)
                return Status.SUCCESS

        self._condition.exhaust()
        # Final settle — max cycles reached, wait for last render
        await Flow([ScrollTo(x=0, y=999_999), self._stable]).run(tab)
        return Status.SUCCESS


class Skip(Node):
    """Always succeeds — used as a fallback when no other action is possible."""

    async def tick(self, _tab: Any) -> Status:
        """Return SUCCESS immediately."""
        return Status.SUCCESS
