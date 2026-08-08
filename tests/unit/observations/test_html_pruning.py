"""Focused source-HTML pruning regressions."""

from __future__ import annotations

from yosoi.observations.artifacts import MemoryArtifactStore
from yosoi.observations.index.addressing import parse_address
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
