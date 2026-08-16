"""Trivial source-HTML control: every declaration is addressable in exactly one hop."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from tests.boss_fights.conftest import HtmlWorkload
from yosoi.observations.index.addressing import ObservationAddressError, resolve_index_entry
from yosoi.observations.index.inspect import InspectionBudget
from yosoi.observations.models.view import RegionRef
from yosoi.observations.pruning.html import DeclarationPruner
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy

WORKLOAD = Path(__file__).parent


@pytest.fixture(scope='module')
def control(html_workload: Callable[[Path, str], HtmlWorkload]) -> HtmlWorkload:
    """Assemble the frozen control workload once per module."""
    return html_workload(WORKLOAD, 'control.html')


def test_frozen_artifact_matches_its_manifest_digest(control: HtmlWorkload) -> None:
    assert control.snapshot.artifacts[0].sha256 == control.manifest['artifact_sha256']


def test_every_required_declaration_is_addressable_in_one_hop(control: HtmlWorkload) -> None:
    unreachable = []
    for evidence in control.ground_truth['required_evidence']:
        ordinals = control.entries_reaching(evidence['oracle_xpath'])
        if not ordinals:
            unreachable.append(evidence['id'])
            continue
        detail = control.inspect_bytes(ordinals[0])
        assert detail, f'{evidence["id"]} resolved to empty canonical bytes'
    assert not unreachable, f'required declarations unreachable from the index: {unreachable}'


def test_malformed_meta_survives_because_nothing_is_enumerated(control: HtmlWorkload) -> None:
    labels = [entry.label for entry in control.index.entries]

    assert 'meta[name=Andrew Berg]' in labels, 'a malformed declaration must be visible in the index itself'


def test_index_stays_inside_its_declared_output_budget(control: HtmlWorkload) -> None:
    total = sum(view.stats.output_bytes for view in control.views)

    assert total <= control.manifest['budget_output_bytes']
    assert not any(view.stats.truncated for view in control.views)


def test_pruning_is_byte_identical_across_runs(control: HtmlWorkload) -> None:
    source = PruningInput(source=control.snapshot.artifacts[0], data=control.data)
    policy = PruningPolicy()

    first = DeclarationPruner().prune(source, policy)
    second = DeclarationPruner().prune(source, policy)

    assert first.model_dump_json() == second.model_dump_json()
    assert first.policy_hash == second.policy_hash


def test_accounting_covers_every_source_element(control: HtmlWorkload) -> None:
    for view in control.views:
        stats = view.stats
        assert stats.retained_items + stats.omitted_items == stats.source_items, view.pruner_name
        assert stats.source_bytes == len(control.data), view.pruner_name


def test_a_foreign_reference_fails_closed(control: HtmlWorkload) -> None:
    foreign = control.index.entries[0].ref.model_copy(update={'snapshot_id': 'some-other-snapshot'})

    with pytest.raises(ObservationAddressError):
        resolve_index_entry(control.index, foreign)
    with pytest.raises(ObservationAddressError):
        control.inspector.inspect(foreign, InspectionBudget())


def test_an_absent_locator_fails_closed(control: HtmlWorkload) -> None:
    known = control.index.entries[0].ref
    absent = RegionRef(
        snapshot_id=known.snapshot_id,
        artifact_sha256=known.artifact_sha256,
        modality=known.modality,
        locator='/html/head/meta[999]',
    )

    with pytest.raises(ObservationAddressError):
        control.inspector.inspect(absent, InspectionBudget())


def test_canonical_bytes_are_never_modified_by_pruning(control: HtmlWorkload) -> None:
    artifact = control.snapshot.artifacts[0]

    assert control.store.read(artifact) == control.data
