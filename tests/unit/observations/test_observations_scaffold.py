"""Contract and fail-closed tests for the unwired observation scaffold."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from yosoi.observations.artifacts import MemoryArtifactStore, manifest_bytes
from yosoi.observations.index import ObservationAddressError, resolve_index_entry
from yosoi.observations.models import (
    CaptureCapability,
    CaptureProfile,
    EvidenceKind,
    IndexEntry,
    ObservationIndex,
    ObservationSnapshot,
    Pagination,
    PrunedFragment,
    PrunedView,
    PruningStats,
    RegionRef,
)
from yosoi.observations.pruning import (
    AxPruner,
    DeclarationPruner,
    NetworkPruner,
    PruningInput,
    PruningPolicy,
)


def test_memory_store_returns_exact_immutable_reference() -> None:
    store = MemoryArtifactStore()
    payload = b'<html><body>hello</body></html>'

    ref = store.put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=payload,
    )

    assert ref.sha256 == hashlib.sha256(payload).hexdigest()
    assert store.read(ref) == payload
    assert store.contains(ref)


def test_snapshot_rejects_foreign_artifact() -> None:
    ref = MemoryArtifactStore().put(
        snapshot_id='snapshot-other',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=b'<html></html>',
    )

    with pytest.raises(ValidationError, match='every artifact must belong'):
        ObservationSnapshot(
            run_id='run-1',
            episode_id='episode-1',
            snapshot_id='snapshot-1',
            requested_profile=CaptureProfile.HTTP_STATIC,
            artifacts=(ref,),
        )


def test_manifest_serialization_is_deterministic() -> None:
    snapshot = ObservationSnapshot(
        run_id='run-1',
        episode_id='episode-1',
        snapshot_id='snapshot-1',
        captured_at=datetime(2026, 8, 8, tzinfo=timezone.utc),
        requested_profile=CaptureProfile.HTTP_STATIC,
        capabilities=(CaptureCapability(kind=EvidenceKind.SOURCE_HTML, available=True),),
    )

    assert manifest_bytes(snapshot) == manifest_bytes(snapshot)


def test_pruned_view_and_index_keep_exact_reference_chain() -> None:
    ref = MemoryArtifactStore().put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=b'<html></html>',
    )
    region = RegionRef(
        snapshot_id='snapshot-1',
        artifact_sha256=ref.sha256,
        modality=EvidenceKind.SOURCE_HTML,
        locator='/html',
    )
    fragment = PrunedFragment(ref=region, ordinal=0, label='document', summary='html document')
    view = PrunedView(
        page=Pagination(offset=0, limit=1_000, returned=1, total=1),
        source=ref,
        pruner_name='html',
        pruner_version='test',
        policy_hash='policy-1',
        fragments=(fragment,),
        stats=PruningStats(
            source_items=1,
            retained_items=1,
            omitted_items=0,
            source_bytes=13,
            output_bytes=13,
        ),
    )
    entry = IndexEntry(ordinal=0, ref=region, label='document', summary='html document')
    index = ObservationIndex(
        snapshot_id='snapshot-1',
        sources=(ref,),
        modalities=(EvidenceKind.SOURCE_HTML,),
        entries=(entry,),
    )

    assert view.fragments == (fragment,)
    assert resolve_index_entry(index, region) == entry

    foreign = region.model_copy(update={'snapshot_id': 'snapshot-other'})
    with pytest.raises(ObservationAddressError, match='different snapshot'):
        resolve_index_entry(index, foreign)


def test_no_modality_pruner_is_a_scaffold_any_more() -> None:
    """The retired guarantee, kept as a statement rather than an empty parametrization.

    This file used to assert that not-yet-implemented pruners fail closed instead of returning
    empty evidence — the rule that "missing capabilities never become empty evidence" depends on.
    Every declared modality now has a real reduction, so that test had no subjects left. Deleting
    it silently would leave no record that the guarantee was ever load-bearing, so what replaces
    it is the fact that made it vacuous.
    """
    assert AxPruner().version != 'scaffold'
    assert NetworkPruner().version != 'scaffold'


def test_declaration_pruner_rejects_evidence_from_another_modality() -> None:
    payload = b'{}'
    ref = MemoryArtifactStore().put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.NETWORK,
        media_type='application/json',
        data=payload,
    )

    with pytest.raises(ValueError, match='cannot consume'):
        DeclarationPruner().prune(PruningInput(source=ref, data=payload), PruningPolicy())
