"""Reuse-scope tagging — which generalization mechanism a decision rode on.

Every reuse decision is labelled with the *scope* it generalized across, so the
ledger, the review queue, and the risk policy can all see — and gate on — how far
a recipe was stretched:

* :attr:`ReuseScope.SAME_DOMAIN` — same host, same route template (domain-wide,
  the strongest/cheapest reuse: ``/quote/AAPL`` → ``/quote/MSFT``).
* :attr:`ReuseScope.SUB_PAGE` — same host, *different* route template (a page-kind
  change on one site: ``/catalog`` → ``/product/123``).
* :attr:`ReuseScope.CROSS_DOMAIN` — different host entirely.
* :attr:`ReuseScope.STRUCTURAL` — same host but the URL carried no class signal
  (root path), so the match rests on the structural fingerprint, not the route.

The classification is derived from the already-computed
:class:`~yosoi.generalization.signals.ReuseSignalPanel`, so tagging costs nothing
beyond a couple of string comparisons.
"""

from __future__ import annotations

from enum import Enum

from yosoi.generalization.signals import ReuseSignalPanel


class ReuseScope(str, Enum):
    """The generalization distance a reuse decision spanned.

    Attributes:
        SAME_DOMAIN: Same host and route template (domain-wide reuse).
        SUB_PAGE: Same host, different route template (page-kind change).
        CROSS_DOMAIN: Different host.
        STRUCTURAL: Same host but a route template with no class signal (root),
            so the decision rests on the structural fingerprint.
    """

    SAME_DOMAIN = 'same_domain'
    SUB_PAGE = 'sub_page'
    CROSS_DOMAIN = 'cross_domain'
    STRUCTURAL = 'structural'


def _is_low_information(route: str) -> bool:
    """Whether a route template carries no page-class signal.

    True for the bare root and for templates whose every segment is an opaque
    placeholder (``{id}``/``{num}``) — i.e. the URL tells us nothing about which
    kind of page this is, so a same-template match really rests on structure.
    """
    segments = [s for s in route.split('/') if s]
    if not segments:
        return True
    return all(s.startswith('{') and s.endswith('}') for s in segments)


def classify_scope(panel: ReuseSignalPanel) -> ReuseScope:
    """Tag a signal panel with the reuse scope it represents.

    Args:
        panel: The recommender's panel (carries host + route templates).

    Returns:
        The :class:`ReuseScope` the (seed, replay) pair spans.
    """
    if not panel.same_domain:
        return ReuseScope.CROSS_DOMAIN
    if panel.seed_route == panel.replay_route:
        # Same host + same template; a route with no class signal (root, or all
        # opaque ids) means the match rests on structure, not the URL.
        return ReuseScope.STRUCTURAL if _is_low_information(panel.seed_route) else ReuseScope.SAME_DOMAIN
    return ReuseScope.SUB_PAGE
