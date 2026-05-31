"""Tests for AX-tree trigger helpers."""

from __future__ import annotations

from typing import Any

import pytest

from yosoi.core.fetcher.dom.ax import AxTarget, find_target, snapshot, snapshot_for_render_tier
from yosoi.core.fetcher.dom.flows import ClickByRole
from yosoi.core.fetcher.dom.probes import TriggerKind, capture_ax_snapshot, probe


def _node(
    role: str,
    name: str,
    *,
    ignored: bool = False,
) -> dict[str, Any]:
    return {
        'ignored': ignored,
        'role': {'type': 'role', 'value': role},
        'name': {'type': 'computedString', 'value': name},
    }


class _AxTab:
    def __init__(self, nodes: list[dict[str, Any]]) -> None:
        self.nodes = nodes
        self.css_queries: list[str] = []

    async def get_full_ax_tree(self, depth: int | None = None) -> list[dict[str, Any]]:
        return self.nodes

    async def query_selector_all(self, selector: str) -> list[str]:
        self.css_queries.append(selector)
        return []

    async def query_selector(self, selector: str) -> str | None:
        self.css_queries.append(selector)
        return None


class _CssOnlyTab:
    async def query_selector_all(self, selector: str) -> list[str]:
        if selector == 'button, a[role="button"], [type="button"]':
            return ['Load more']
        return []


class _BrokenAxTab:
    async def get_full_ax_tree(self) -> list[dict[str, Any]]:
        raise RuntimeError('cdp unavailable')

    async def query_selector_all(self, selector: str) -> list[str]:
        if selector == 'button, a[role="button"], [type="button"]':
            return ['Load more']
        return []


def test_snapshot_collects_named_targets_without_role_allowlist() -> None:
    snap = snapshot(
        [
            _node('RootWebArea', 'Example'),
            _node('button', 'Load more'),
            _node('StaticText', 'Load more'),
            _node('link', 'Next'),
            _node('button', 'Hidden', ignored=True),
        ]
    )

    assert snap.node_count == 5
    assert snap.named_count == 4
    assert snap.targets == (
        AxTarget(role='RootWebArea', name='Example', nth=0),
        AxTarget(role='button', name='Load more', nth=0),
        AxTarget(role='StaticText', name='Load more', nth=0),
        AxTarget(role='link', name='Next', nth=0),
    )
    assert snap.richness == pytest.approx(0.8)


def test_snapshot_for_render_tier_skips_static_l0_l1_captures() -> None:
    nodes = [_node('button', 'Load more')]

    assert snapshot_for_render_tier(nodes, 0) is None
    assert snapshot_for_render_tier(nodes, 1) is None
    assert snapshot_for_render_tier(nodes, 2) == snapshot(nodes)
    assert snapshot_for_render_tier(nodes, 3) == snapshot(nodes)


def test_snapshot_assigns_nth_for_duplicate_role_names() -> None:
    snap = snapshot([_node('button', 'Go'), _node('button', 'Go'), _node('button', 'Go')])

    assert snap.targets == (
        AxTarget(role='button', name='Go', nth=0),
        AxTarget(role='button', name='Go', nth=1),
        AxTarget(role='button', name='Go', nth=2),
    )


def test_find_target_matches_by_role_and_substring_name() -> None:
    snap = snapshot([_node('button', 'Show more results')])

    assert find_target(snap, roles={'button'}, names=('show more',)) == AxTarget(
        role='button',
        name='Show more results',
        nth=0,
    )


def test_find_target_exact_mode_requires_exact_name() -> None:
    snap = snapshot([_node('link', 'Next article'), _node('link', 'Next')])

    assert find_target(snap, roles={'link'}, names=('next',), exact=True) == AxTarget(
        role='link',
        name='Next',
        nth=0,
    )


@pytest.mark.asyncio
async def test_ax_snapshot_uses_voidcrawl_032_get_full_ax_tree() -> None:
    tab = _AxTab([_node('button', 'Load more')])

    snap = await capture_ax_snapshot(tab)

    assert snap is not None
    assert snap.node_count == 1
    assert snap.targets == (AxTarget(role='button', name='Load more', nth=0),)


@pytest.mark.asyncio
async def test_ax_snapshot_returns_none_when_voidcrawl_ax_api_fails() -> None:
    assert await capture_ax_snapshot(_BrokenAxTab()) is None


@pytest.mark.asyncio
async def test_probe_load_more_prefers_ax_target() -> None:
    tab = _AxTab([_node('button', 'Load more')])

    trigger = await probe(tab, TriggerKind.LOAD_MORE)

    assert trigger is not None
    assert trigger.kind == TriggerKind.LOAD_MORE
    assert trigger.ax_target == AxTarget(role='button', name='Load more', nth=0)
    assert tab.css_queries == []


@pytest.mark.asyncio
async def test_probe_falls_back_to_css_when_ax_unavailable() -> None:
    trigger = await probe(_CssOnlyTab(), TriggerKind.LOAD_MORE)

    assert trigger is not None
    assert trigger.kind == TriggerKind.LOAD_MORE
    assert trigger.ax_target is None
    assert trigger.label == 'load more'


@pytest.mark.asyncio
async def test_probe_pagination_prefers_exact_ax_link_target() -> None:
    tab = _AxTab([_node('link', 'Next article'), _node('link', 'Next')])

    trigger = await probe(tab, TriggerKind.PAGINATION)

    assert trigger is not None
    assert trigger.kind == TriggerKind.PAGINATION
    assert trigger.ax_target == AxTarget(role='link', name='Next', nth=0)
    assert tab.css_queries == []


@pytest.mark.asyncio
async def test_probe_falls_back_to_css_when_voidcrawl_ax_probe_fails() -> None:
    trigger = await probe(_BrokenAxTab(), TriggerKind.LOAD_MORE)

    assert trigger is not None
    assert trigger.ax_target is None
    assert trigger.label == 'load more'


@pytest.mark.asyncio
async def test_click_by_role_action_uses_tab_api(mocker) -> None:
    tab = mocker.MagicMock()
    tab.click_by_role = mocker.AsyncMock(return_value=None)

    await ClickByRole('button', 'Load more', 2).run(tab)

    tab.click_by_role.assert_awaited_once_with('button', 'Load more', 2)
