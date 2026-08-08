"""Shared paths and workload assembly for deterministic observation boss fights."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path

import pytest
import tomllib

from yosoi.observations.artifacts.memory import MemoryArtifactStore
from yosoi.observations.index.addressing import parse_address
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector, RegionPage
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.models.view import PrunedView
from yosoi.observations.pruning.html import BodyPruner, DeclarationPruner
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


@pytest.fixture(scope='session')
def boss_fights_root() -> Path:
    """Return the root containing modality workloads and frozen artifacts."""
    return Path(__file__).parent


@dataclass(frozen=True)
class HtmlWorkload:
    """One frozen source-HTML workload assembled into a walkable address space.

    Everything here is derived from bytes on disk, so a workload is reproducible without a
    network, a browser, or a provider.
    """

    manifest: dict
    ground_truth: dict
    data: bytes
    store: MemoryArtifactStore
    snapshot: ObservationSnapshot
    views: tuple[PrunedView, ...]
    index: ObservationIndex
    inspector: ObservationInspector

    def view(self, pruner_name: str) -> PrunedView:
        """Return one reduction by pruner name."""
        return next(view for view in self.views if view.pruner_name == pruner_name)

    def inspect_bytes(self, ordinal: int, budget: InspectionBudget | None = None) -> bytes:
        """Return the canonical bytes one index entry addresses."""
        entry = self.index.entries[ordinal]
        return self.inspector.inspect(entry.ref, budget or InspectionBudget()).content

    def expand(self, ordinal: int, budget: InspectionBudget | None = None, *, offset: int = 0) -> RegionPage:
        """Return one page of members of the region an index entry addresses."""
        entry = self.index.entries[ordinal]
        return self.inspector.expand(entry.ref, budget or InspectionBudget(), offset=offset)

    def regions(self) -> list[int]:
        """Return ordinals of every repeat region in the index."""
        return [entry.ordinal for entry in self.index.entries if entry.coverage is not None]

    def entries_reaching(self, oracle_xpath: str) -> list[int]:
        """Return ordinals whose emitted address resolves to the oracle's element.

        Ground truth names evidence by an independent XPath oracle; the implementation names
        it by whatever locator it chose. This maps one to the other so fixture authors never
        prescribe — or accidentally copy — an emitted reference.
        """
        from lxml import html as lxml_html

        root = lxml_html.fromstring(self.data)
        tree = root.getroottree()
        expected = {tree.getpath(element) for element in tree.xpath(oracle_xpath)}
        if not expected:
            raise AssertionError(f'ground-truth oracle {oracle_xpath!r} matches nothing in the frozen artifact')
        reached = []
        for entry in self.index.entries:
            address = parse_address(entry.ref.locator)
            # A region is reached when the oracle's elements are the members it collapsed;
            # an element entry is reached when it addresses one of them directly.
            if address.is_region:
                container = address.segments[-1].path
                if any(path.rsplit('/', 1)[0] == container for path in expected):
                    reached.append(entry.ordinal)
            elif len(address.segments) == 1 and address.segments[0].path in expected:
                reached.append(entry.ordinal)
        return reached


def _build(workload_dir: Path, artifact_name: str) -> HtmlWorkload:
    """Assemble a frozen HTML workload from its manifest, ground truth, and artifact."""
    manifest = tomllib.loads((workload_dir / 'manifest.toml').read_text())
    ground_truth = tomllib.loads((workload_dir / 'ground_truth.toml').read_text())
    data = (workload_dir / 'artifacts' / artifact_name).read_bytes()

    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id=manifest['id'],
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=data,
    )
    snapshot = ObservationSnapshot(
        run_id=manifest['id'],
        episode_id=manifest['id'],
        snapshot_id=manifest['id'],
        requested_profile=CaptureProfile(manifest['capture_profile']),
        artifacts=(artifact,),
    )
    source = PruningInput(source=artifact, data=data)
    policy = PruningPolicy()
    views = (DeclarationPruner().prune(source, policy), BodyPruner().prune(source, policy))
    index = ObservationIndexCompiler().compile(snapshot, views)
    return HtmlWorkload(
        manifest=manifest,
        ground_truth=ground_truth,
        data=data,
        store=store,
        snapshot=snapshot,
        views=views,
        index=index,
        inspector=ObservationInspector(store, snapshot),
    )


@pytest.fixture(scope='session')
def html_workload() -> Callable[[Path, str], HtmlWorkload]:
    """Return a factory that assembles a frozen source-HTML workload directory."""
    return _build
