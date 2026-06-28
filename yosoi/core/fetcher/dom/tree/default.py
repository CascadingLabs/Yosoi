"""Default behavior tree for DOM content loading.

Builds the tree that works for most websites. The tree clears obstacles
first (cookies, popups), then exhausts content triggers in priority order
(load more, accordion, tab, pagination, infinite scroll).

The tree restarts from the top after any SUCCESS. It stops when every
node returns FAILURE — meaning nothing left to do.
"""

from __future__ import annotations

from yosoi.core.fetcher.dom.catalogues import CONTENT_SELECTOR
from yosoi.core.fetcher.dom.flows import WaitForDOMStable
from yosoi.core.fetcher.dom.probes import TriggerKind
from yosoi.core.fetcher.dom.tree.actions import (
    ActionLog,
    ClickClose,
    ClickTrigger,
    Scroll,
    Skip,
)
from yosoi.core.fetcher.dom.tree.conditions import HasCloseButton, HasOverlay, HasTrigger
from yosoi.core.fetcher.dom.tree.nodes import Node, Selector, Sequence


def build_default_tree(
    quiet_ms: int = 800,
    content_selector: str = CONTENT_SELECTOR,
    max_click_cycles: int = 50,
    max_scroll_cycles: int = 10,
) -> tuple[Node, list[ActionLog]]:
    """Build the default behavior tree and return it with its action logs.

    The action logs are populated as the tree runs and can be collected
    after completion to build a domain stability recipe.

    Args:
        quiet_ms: Milliseconds of DOM silence that counts as stable.
        content_selector: CSS selector for counting loaded items.
        max_click_cycles: Maximum clicks per trigger before giving up.
        max_scroll_cycles: Maximum scroll iterations before giving up.

    Returns:
        Tuple of (root node, list of ActionLog instances).
    """
    stable = WaitForDOMStable(quiet_ms=quiet_ms)

    # --- Conditions (stateful — track exhaustion) ---
    has_cookie = HasTrigger(TriggerKind.COOKIE, content_selector)
    has_popup = HasTrigger(TriggerKind.POPUP, content_selector)
    has_age_gate = HasTrigger(TriggerKind.AGE_GATE, content_selector)
    has_load_more = HasTrigger(TriggerKind.LOAD_MORE, content_selector)
    has_accordion = HasTrigger(TriggerKind.ACCORDION, content_selector)
    has_tab = HasTrigger(TriggerKind.TAB, content_selector)
    has_pagination = HasTrigger(TriggerKind.PAGINATION, content_selector)
    has_scroll = HasTrigger(TriggerKind.INFINITE_SCROLL, content_selector)

    # --- Actions (paired with their conditions) ---
    click_cookie = ClickTrigger(has_cookie, stable, max_click_cycles)
    click_popup = ClickTrigger(has_popup, stable, max_click_cycles)
    click_age_gate = ClickTrigger(has_age_gate, stable, max_click_cycles)
    click_load_more = ClickTrigger(has_load_more, stable, max_click_cycles)
    click_accordion = ClickTrigger(has_accordion, stable, max_click_cycles)
    click_tab = ClickTrigger(has_tab, stable, max_click_cycles)
    click_pagination = ClickTrigger(has_pagination, stable, max_click_cycles)
    scroll = Scroll(has_scroll, stable, max_scroll_cycles)

    logs = [
        click_cookie.log,
        click_popup.log,
        click_age_gate.log,
        click_load_more.log,
        click_accordion.log,
        click_tab.log,
        click_pagination.log,
        scroll.log,
    ]

    # --- Tree ---
    tree = Selector(
        # 1. Clear overlays first
        Sequence(
            HasOverlay(),
            Selector(
                Sequence(HasCloseButton(), ClickClose()),
                Skip(),  # overlay has form inputs — leave it
            ),
        ),
        # 2. Clear known consent/interstitial triggers and record concrete targets
        Sequence(has_cookie, click_cookie),
        Sequence(has_popup, click_popup),
        Sequence(has_age_gate, click_age_gate),
        # 3. Exhaust load more
        Sequence(has_load_more, click_load_more),
        # 4. Expand accordions
        Sequence(has_accordion, click_accordion),
        # 5. Activate tabs
        Sequence(has_tab, click_tab),
        # 6. Paginate
        Sequence(has_pagination, click_pagination),
        # 7. Infinite scroll (last — least specific signal)
        Sequence(has_scroll, scroll),
    )

    return tree, logs
