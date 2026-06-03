"""Tests for reuse-scope classification."""

import pytest

from yosoi.generalization.fingerprint import PageObservation
from yosoi.generalization.recommend import recommend
from yosoi.generalization.scope import ReuseScope, classify_scope

pytestmark = pytest.mark.unit

_HIST = {'div': 10, 'a': 5, 'span': 8}


def _panel(seed_url: str, replay_url: str):
    seed = PageObservation(url=seed_url, rows=10, tag_hist=_HIST)
    replay = PageObservation(url=replay_url, rows=10, tag_hist=_HIST)
    return recommend(seed, replay)


def test_same_route_template_same_host_is_same_domain() -> None:
    """Paths sharing a template (numeric segment collapses) are domain-wide."""
    assert classify_scope(_panel('https://x.com/page/2', 'https://x.com/page/7')) is ReuseScope.SAME_DOMAIN


def test_different_route_same_host_is_sub_page() -> None:
    """Same host, different page kind = sub-page."""
    assert classify_scope(_panel('https://x.com/catalog', 'https://x.com/product/1')) is ReuseScope.SUB_PAGE


def test_different_host_is_cross_domain() -> None:
    """Different host = cross-domain regardless of path."""
    assert classify_scope(_panel('https://x.com/a/1', 'https://y.com/a/1')) is ReuseScope.CROSS_DOMAIN


def test_bare_root_path_is_structural() -> None:
    """A root path carries no class signal, so the match is structural."""
    assert classify_scope(_panel('https://x.com/', 'https://x.com/')) is ReuseScope.STRUCTURAL


def test_all_placeholder_route_is_structural() -> None:
    """A route of only opaque ids carries no class signal -> structural, not same-domain."""
    assert classify_scope(_panel('https://x.com/123', 'https://x.com/456')) is ReuseScope.STRUCTURAL
