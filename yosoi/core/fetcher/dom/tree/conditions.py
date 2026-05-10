"""Condition nodes — read page state, never act on it.

Each condition returns SUCCESS if the thing it checks is present,
FAILURE otherwise. Conditions that track exhaustion flip permanently
to FAILURE once they determine there is nothing left to do.
"""

from __future__ import annotations

import logging
from typing import Any

from yosoi.core.fetcher.dom.probes import (
    TriggerKind,
    count_content,
    probe,
)
from yosoi.core.fetcher.dom.tree.nodes import Node, Status

logger = logging.getLogger(__name__)


class HasOverlay(Node):
    """Detect a visible modal, dialog, or overlay blocking the page."""

    async def tick(self, tab: Any) -> Status:
        """Return SUCCESS if an overlay is currently visible."""
        try:
            for sel in (
                '[role="dialog"]',
                '.modal:not([hidden])',
                '[class*="overlay"]:not([hidden])',
                '[class*="popup"]:not([hidden])',
            ):
                if await tab.query_selector(sel):
                    return Status.SUCCESS
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('HasOverlay failed: %s', exc)
        return Status.FAILURE


class HasCloseButton(Node):
    """Detect a close/dismiss button that does not have form inputs nearby.

    Returns FAILURE if the overlay contains form inputs — those overlays
    should be left alone rather than dismissed blindly.
    """

    async def tick(self, tab: Any) -> Status:
        """Return SUCCESS if a safe close button is present."""
        try:
            # Bail out if there are form inputs — don't dismiss forms
            if await tab.query_selector('input[type="email"], input[type="password"], input[type="text"]'):
                return Status.FAILURE

            for sel in (
                '[role="dialog"] [aria-label*="close" i]',
                '[role="dialog"] button[class*="close"]',
                '.modal [class*="close"]',
                '[class*="popup"] [class*="close"]',
                '[class*="overlay"] [class*="close"]',
                'button[aria-label*="dismiss" i]',
            ):
                if await tab.query_selector(sel):
                    return Status.SUCCESS
        except (RuntimeError, OSError, ValueError) as exc:
            logger.debug('HasCloseButton failed: %s', exc)
        return Status.FAILURE


class HasTrigger(Node):
    """Detect a content trigger of the given kind.

    Tracks exhaustion — once a trigger has been acted on and produced
    no content growth, this condition permanently returns FAILURE so
    the tree does not retry it on subsequent restarts.
    """

    def __init__(self, kind: TriggerKind, content_selector: str) -> None:
        """Initialise for a specific trigger kind.

        Args:
            kind: The trigger kind to detect.
            content_selector: CSS selector for counting content items.
        """
        self._kind = kind
        self._content_selector = content_selector
        self._exhausted = False
        self.last_trigger = None

    async def tick(self, tab: Any) -> Status:
        """Return SUCCESS if the trigger is present and not exhausted."""
        if self._exhausted:
            return Status.FAILURE
        count = await count_content(tab, self._content_selector)
        trigger = await probe(tab, self._kind, content_count=count)
        if trigger is None:
            return Status.FAILURE
        self.last_trigger = trigger
        return Status.SUCCESS

    def exhaust(self) -> None:
        """Mark this trigger as permanently exhausted."""
        self._exhausted = True
        self.last_trigger = None
