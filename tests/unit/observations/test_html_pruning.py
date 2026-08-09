"""Focused source-HTML pruning regressions."""

from __future__ import annotations

import pytest

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.html_tree import HtmlParseError
from yosoi.observations.index.addressing import parse_address
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector
from yosoi.observations.models import CaptureProfile, ObservationSnapshot
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.pruning import BodyPruner, PruningInput, PruningPolicy


def test_separated_same_shape_runs_remain_individual() -> None:
    payload = b"""<html><body><table><tbody>
        <tr><td>alpha</td></tr>
        <tr><td>beta</td></tr>
        <tr><th>divider</th></tr>
        <tr><td>gamma</td></tr>
        <tr><td>delta</td></tr>
    </tbody></table></body></html>"""
    ref = MemoryArtifactStore().put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=payload,
    )

    view = BodyPruner().prune(PruningInput(source=ref, data=payload), PruningPolicy())
    locators = [fragment.ref.locator for fragment in view.fragments]
    tbody_regions = [
        address
        for locator in locators
        if (address := parse_address(locator)).is_region and address.segments[-1].path.endswith('/tbody')
    ]

    assert len(locators) == len(set(locators))
    assert not tbody_regions, 'non-contiguous runs must not be merged or mint duplicate region addresses'


def test_xpath_sensitive_attribute_names_never_mint_dead_anchors() -> None:
    payload = b'<html><body><div xml:lang="x">content</div></body></html>'
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=payload,
    )
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id='snapshot-1',
        requested_profile=CaptureProfile.HTTP_STATIC,
        artifacts=(ref,),
    )
    view = BodyPruner().prune(PruningInput(source=ref, data=payload), PruningPolicy())
    inspector = ObservationInspector(store, manifest)

    assert view.fragments
    for fragment in view.fragments:
        assert inspector.inspect(fragment.ref, InspectionBudget()).returned_bytes > 0


def test_hostile_depth_fails_closed_instead_of_returning_a_truncated_tree() -> None:
    payload = ('<html><body>' + '<div>' * 300 + 'BOTTOM_MARKER' + '</div>' * 300 + '</body></html>').encode()
    ref = MemoryArtifactStore().put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=payload,
    )

    with pytest.raises(HtmlParseError, match='depth limit'):
        BodyPruner().prune(PruningInput(source=ref, data=payload), PruningPolicy())


def test_a_collapsed_run_cannot_expand_into_a_separated_singleton() -> None:
    payload = b"""<html><body><table><tbody>
        <tr><td>alpha</td></tr>
        <tr><td>beta</td></tr>
        <tr><th>divider</th></tr>
        <tr><td>gamma</td></tr>
    </tbody></table></body></html>"""
    store = MemoryArtifactStore()
    ref = store.put(
        snapshot_id='snapshot-1',
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=payload,
    )
    view = BodyPruner().prune(PruningInput(source=ref, data=payload), PruningPolicy())
    manifest = ObservationSnapshot(
        run_id='run',
        episode_id='episode',
        snapshot_id='snapshot-1',
        requested_profile=CaptureProfile.HTTP_STATIC,
        artifacts=(ref,),
    )

    assert not [fragment for fragment in view.fragments if fragment.coverage is not None]
    for fragment in view.fragments:
        assert ObservationInspector(store, manifest).inspect(fragment.ref, InspectionBudget()).returned_bytes > 0
