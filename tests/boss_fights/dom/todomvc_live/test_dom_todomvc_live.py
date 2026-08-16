"""Offline regression tests for the frozen live TodoMVC rendered-DOM episode."""

from __future__ import annotations

import hashlib
from pathlib import Path

import tomllib

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.dom import DomNode, DomSnapshot, parse_dom_snapshot
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.pruning import DomPruner, PruningInput, PruningPolicy

ROOT = Path(__file__).parent
ARTIFACTS = ROOT / 'artifacts'
MANIFEST = tomllib.loads((ROOT / 'manifest.toml').read_text())
GROUND_TRUTH = tomllib.loads((ROOT / 'ground_truth.toml').read_text())


def _nodes(root: DomNode) -> list[DomNode]:
    result: list[DomNode] = []

    def visit(node: DomNode) -> None:
        result.append(node)
        for child in node.children:
            visit(child)
        if node.shadow_root is not None:
            visit(node.shadow_root)

    visit(root)
    return result


def _attrs(node: DomNode) -> dict[str, str]:
    return {attribute.name: attribute.value for attribute in node.attributes}


def _load(name: str) -> tuple[bytes, DomSnapshot]:
    data = (ARTIFACTS / f'{name}.json').read_bytes()
    return data, parse_dom_snapshot(data)


def _todo_list(snapshot: DomSnapshot) -> DomNode:
    return next(node for node in _nodes(snapshot.root) if _attrs(node).get('class') == 'todo-list')


def test_frozen_live_artifacts_match_manifest_digests() -> None:
    for name, digest in MANIFEST['artifacts'].items():
        assert hashlib.sha256((ARTIFACTS / f'{name}.json').read_bytes()).hexdigest() == digest


def test_todomvc_episode_matches_independent_ground_truth() -> None:
    for name, expected in GROUND_TRUTH.items():
        _, snapshot = _load(name)
        todos = _todo_list(snapshot).children
        completed = sum('completed' in _attrs(todo).get('class', '').split() for todo in todos)
        selected = next(
            node for node in _nodes(snapshot.root) if node.tag == 'a' and _attrs(node).get('class') == 'selected'
        )

        expected_href = '#/' if expected['route'] == 'all' else f'#/{expected["route"]}'
        assert len(todos) == expected['todo_count']
        assert completed == expected['completed_count']
        assert _attrs(selected).get('href') == expected_href


def test_live_todomvc_repeat_region_is_expandable_offline() -> None:
    data, snapshot = _load('s1_three_active')
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id=snapshot.snapshot_id,
        kind=EvidenceKind.RENDERED_DOM,
        media_type='application/json',
        data=data,
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    region = next(
        fragment for fragment in view.fragments if fragment.coverage is not None and 'todo-list' in fragment.label
    )
    manifest = ObservationSnapshot(
        run_id='todomvc-live',
        episode_id='todomvc-live',
        snapshot_id=snapshot.snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )

    inspector = ObservationInspector(store, manifest)
    page = inspector.expand(region.ref, InspectionBudget(max_items=10))
    detail = inspector.inspect(page.members[0].ref, InspectionBudget())

    assert len(page.members) == 3
    assert page.coverage.observed == 3
    assert page.coverage.complete is False  # the live page declared no total count
    assert DomNode.model_validate_json(detail.content).tag == 'li'
    assert page.members[0].stable is True  # data-id is available in this capture


def _episode_index(name: str, snapshot_id: str):
    """Compile one state of the frozen live episode into an index."""
    from yosoi.observations.index.compiler import ObservationIndexCompiler
    from yosoi.observations.models.dom import serialize_dom_snapshot

    _, parsed = _load(name)
    snapshot = parsed.model_copy(update={'snapshot_id': snapshot_id})
    data = serialize_dom_snapshot(snapshot)
    store = MemoryArtifactStore()
    ref = store.put(snapshot_id=snapshot_id, kind=EvidenceKind.RENDERED_DOM, media_type='application/json', data=data)
    manifest = ObservationSnapshot(
        run_id='todomvc-live',
        episode_id=name,
        snapshot_id=snapshot_id,
        requested_profile=CaptureProfile.BROWSER_HEADLESS,
        artifacts=(ref,),
    )
    view = DomPruner().prune(PruningInput(source=ref, data=data), PruningPolicy())
    return ObservationIndexCompiler().compile(manifest, (view,))


def test_checking_one_todo_diffs_to_a_handful_of_changes_not_a_new_page() -> None:
    """The action-episode claim: one committed action produces a bounded, readable diff.

    Against a real live capture, not a synthetic one. Checking the second todo touches the item's
    state, the remaining-count, and the footer — and must leave the rest of the page alone. A diff
    that reports dozens of changes for one click is useless for QA even when every change is real.
    """
    from yosoi.observations.index.diff import ChangeKind, diff_indexes

    diff = diff_indexes(_episode_index('s1_three_active', 's1'), _episode_index('s2_one_completed', 's2'))

    assert not diff.of_kind(ChangeKind.ADDED), 'checking a todo adds no addressable thing'
    assert not diff.of_kind(ChangeKind.REMOVED), 'and removes none'
    assert 0 < len(diff.of_kind(ChangeKind.CHANGED)) <= 8, diff.describe()
    assert diff.unchanged > len(diff.changes), 'most of the page must be reported as holding still'

    # The remaining-count is the page's own statement of what the click did.
    assert any('"3"' in change.summary and '"2"' in change.summary for change in diff.changes), diff.describe()
    # And the todo list region must report the state move rather than being re-identified.
    assert any('todo-list' in change.label for change in diff.of_kind(ChangeKind.CHANGED))


def test_adding_todos_to_an_empty_list_is_reported_as_additions() -> None:
    from yosoi.observations.index.diff import ChangeKind, diff_indexes

    diff = diff_indexes(_episode_index('s0_empty', 's0'), _episode_index('s1_three_active', 's1'))

    assert diff.of_kind(ChangeKind.ADDED), 'three todos and their list are new addressable things'
    assert not diff.of_kind(ChangeKind.REMOVED)
    assert any('todo-list' in change.label for change in diff.of_kind(ChangeKind.ADDED))
