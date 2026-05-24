"""Flow construction for detected triggers.

Given a DetectedTrigger, builds the VoidCrawl Flow that handles it.
No probing happens here — actions only know how to act, not what to look for.

Each flow ends with WaitForDOMStable so stabilization is visible in
DebugSession alongside the action that caused the DOM change.
"""

from __future__ import annotations

import logging
from typing import Any

from voidcrawl.actions import ClickElement, Flow, JsActionNode, ScrollTo, inline_js

from yosoi.core.fetcher.dom.catalogues import (
    CLICK_BY_TEXT_JS,
    CLICK_LINK_BY_TEXT_JS,
)
from yosoi.core.fetcher.dom.probes import DetectedTrigger, TriggerKind

logger = logging.getLogger(__name__)

# How far to scroll for infinite scroll — large enough to reach the bottom
# of any realistic page without being absurd.
_SCROLL_BOTTOM_Y = 999_999

# Fallback wait in milliseconds when MutationObserver cannot be established.
_FALLBACK_WAIT_MS = 800


# ---------------------------------------------------------------------------
# WaitForDOMStable — custom VoidCrawl action
# ---------------------------------------------------------------------------


class WaitForDOMStable(JsActionNode):
    """Wait for DOM child-list mutations to stop for quiet_ms milliseconds.

    Uses MutationObserver so it responds to actual DOM activity rather than
    sleeping for a fixed time. Fits into a Flow like any built-in action
    and is visible to DebugSession.
    """

    js = inline_js("""
        (() => {
            const quietMs = __params.quiet_ms;
            return new Promise((resolve) => {
                let timer = setTimeout(() => {
                    observer.disconnect();
                    resolve('stable');
                }, quietMs);

                const observer = new MutationObserver((mutations) => {
                    const meaningful = mutations.some(m =>
                        m.addedNodes.length > 0 || m.removedNodes.length > 0
                    );
                    if (meaningful) {
                        clearTimeout(timer);
                        timer = setTimeout(() => {
                            observer.disconnect();
                            resolve('stable');
                        }, quietMs);
                    }
                });

                observer.observe(document.body, {
                    childList: true,
                    subtree: true,
                });
            });
        })()
    """)

    def __init__(self, quiet_ms: int = 800) -> None:
        """Initialise with DOM quiet period in milliseconds."""
        self.quiet_ms = quiet_ms


# ---------------------------------------------------------------------------
# Flow builder
# ---------------------------------------------------------------------------


def build_flow(trigger: DetectedTrigger, stable: WaitForDOMStable) -> Flow | None:
    """Build a VoidCrawl Flow for a single trigger action plus stabilization.

    Returns None if no flow can be constructed for the trigger kind.
    The caller should skip this trigger and move on if None is returned.

    Args:
        trigger: The detected trigger to act on.
        stable: Shared WaitForDOMStable instance configured for this session.

    Returns:
        A Flow ready to run, or None.
    """
    try:
        if trigger.kind == TriggerKind.INFINITE_SCROLL:
            return Flow().add(ScrollTo(x=0, y=_SCROLL_BOTTOM_Y)).add(stable)

        if trigger.kind == TriggerKind.LOAD_MORE:
            js = CLICK_BY_TEXT_JS.format(needle=trigger.label)
            return Flow().add(JsAction(js)).add(stable)

        if trigger.kind == TriggerKind.PAGINATION:
            # Use JS text match for generic a[href], direct click for known selectors
            if trigger.selector == 'a[href]':
                js = CLICK_LINK_BY_TEXT_JS.format(needle=trigger.label)
                return Flow().add(JsAction(js)).add(stable)
            return Flow().add(ClickElement(trigger.selector)).add(stable)

        # Cookie, popup, age gate, accordion, tab — all direct selector clicks
        return Flow().add(ClickElement(trigger.selector)).add(stable)

    except (RuntimeError, OSError, ValueError) as exc:
        logger.debug('build_flow failed for %r: %s', trigger.label, exc)
        return None


class JsAction(JsActionNode):
    """One-off JS execution — wraps an arbitrary JS string as an ActionNode."""

    def __init__(self, code: str) -> None:
        """Initialise with raw JavaScript code string."""
        self.code = code
        # FIXME: this mutates the *class* attribute `js`, so every JsAction instance shares
        # it and the last one constructed wins. Under concurrent tabs (pool allows up to
        # max_concurrent) one tab's flow can execute another tab's JS. Store `js` on the
        # instance (self.js = inline_js(code)) instead of on the class.
        type(self).js = inline_js(code)

    def params(self) -> dict[str, Any]:
        """Return only the code string, excluding the non-serialisable JsSource."""
        return {'code': self.code}
