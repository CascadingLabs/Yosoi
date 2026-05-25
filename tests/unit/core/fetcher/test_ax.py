"""Tests for AX-tree trigger helpers."""

from __future__ import annotations

from typing import Any

import pytest

from yosoi.core.fetcher.dom.ax import AxTarget, extract_one, extract_records, find_target, snapshot
from yosoi.core.fetcher.dom.flows import ClickByRole
from yosoi.core.fetcher.dom.probes import TriggerKind, probe
from yosoi.models.selectors import FieldSelectors, role


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


def test_snapshot_collects_interactive_named_targets() -> None:
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
        AxTarget(role='button', name='Load more', nth=0),
        AxTarget(role='link', name='Next', nth=0),
    )
    assert snap.richness == pytest.approx(0.8)


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
async def test_click_by_role_action_uses_tab_api(mocker) -> None:
    tab = mocker.MagicMock()
    tab.click_by_role = mocker.AsyncMock(return_value=None)

    await ClickByRole('button', 'Load more', 2).run(tab)

    tab.click_by_role.assert_awaited_once_with('button', 'Load more', 2)


# ── extract_records (AX read-side) ───────────────────────────────────────────


def _ax(node_id: str, role: str, name: str, *, children: tuple[str, ...] = (), ignored: bool = False) -> dict[str, Any]:
    return {
        'nodeId': node_id,
        'childIds': list(children),
        'ignored': ignored,
        'role': {'type': 'role', 'value': role},
        'name': {'type': 'computedString', 'value': name},
    }


def test_extract_records_groups_fields_per_card_and_skips_prefix() -> None:
    nodes = [
        _ax('1', 'article', "Moe's Guitars", children=('2', '3')),
        _ax('2', 'link', "Moe's Guitars"),
        _ax('3', 'image', '5.0 stars 109 Reviews'),
        _ax('4', 'article', 'Guitar Center', children=('5', '6')),
        _ax('5', 'link', 'Guitar Center'),
        _ax('6', 'image', '4.4 stars 2,980 Reviews'),
        _ax('7', 'article', 'Ad · Sponsored', children=('8',)),  # dropped by skip prefix
        _ax('8', 'image', '4.0 stars 10 Reviews'),
    ]
    # role selector returns the node's raw text; value parsing is the caller's coercion type.
    fields = {'rating': FieldSelectors(primary=role('image'))}
    recs = extract_records(nodes, card_role='article', fields=fields, skip_name_prefixes=('Ad ·',))
    assert recs == [
        {'name': "Moe's Guitars", 'rating': '5.0 stars 109 Reviews'},
        {'name': 'Guitar Center', 'rating': '4.4 stars 2,980 Reviews'},
    ]


def test_extract_records_scopes_fields_to_own_card_via_childids() -> None:
    nodes = [
        _ax('1', 'article', 'A', children=('2',)),
        _ax('2', 'image', '4.9 stars 10 Reviews'),
        _ax('3', 'article', 'B', children=('4',)),
        _ax('4', 'image', '3.1 stars 5 Reviews'),
    ]
    recs = extract_records(nodes, card_role='article', fields={'rating': FieldSelectors(primary=role('image'))})
    assert [r['rating'] for r in recs] == ['4.9 stars 10 Reviews', '3.1 stars 5 Reviews']


def test_extract_records_missing_field_is_none() -> None:
    nodes = [_ax('1', 'article', 'Solo', children=('2',)), _ax('2', 'link', 'Solo')]
    recs = extract_records(nodes, card_role='article', fields={'rating': FieldSelectors(primary=role('image'))})
    assert recs == [{'name': 'Solo', 'rating': None}]


def test_extract_one_resolves_against_whole_tree() -> None:
    # single-record page (e.g. a detail panel): fields resolve anywhere, by role + name.
    nodes = [_ax('1', 'button', 'Phone: (212) 555-1212'), _ax('2', 'link', 'Website: example.com')]
    rec = extract_one(
        nodes,
        fields={
            'phone': FieldSelectors(primary=role('button', 'Phone:')),
            'website': FieldSelectors(primary=role('link', 'Website:')),
        },
    )
    assert rec == {'phone': 'Phone: (212) 555-1212', 'website': 'Website: example.com'}
