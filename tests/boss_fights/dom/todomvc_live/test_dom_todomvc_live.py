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
