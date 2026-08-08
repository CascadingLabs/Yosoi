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

        Mapping goes through the production resolver rather than through string comparison of
        locators. When addresses were root-absolute getpaths, comparing strings happened to
        work; it stopped working the moment addresses could be anchored, which is the point —
        a harness that knows the locator grammar is a harness that has to be rewritten every
        time the grammar earns a new form. This one only knows that an address resolves.
        """
        from lxml import html as lxml_html

        from yosoi.observations.index.inspect import _region_members, _resolve_segments

        root = lxml_html.fromstring(self.data)
        tree = root.getroottree()
        expected = {tree.getpath(element) for element in tree.xpath(oracle_xpath)}
        if not expected:
            raise AssertionError(f'ground-truth oracle {oracle_xpath!r} matches nothing in the artifact')
        reached = []
        for entry in self.index.entries:
            address = parse_address(entry.ref.locator)
            resolved = _resolve_segments(tree, address)
            # A region is reached when the oracle's elements are the members it collapsed;
            # an element entry is reached when it addresses one of them directly.
            if address.is_region:
                members = _region_members(resolved, address.segments[-1].shape or '')
                if any(tree.getpath(member) in expected for member in members):
                    reached.append(entry.ordinal)
            elif tree.getpath(resolved) in expected:
                reached.append(entry.ordinal)
        return reached

    def regions_reaching(self, oracle_xpath: str) -> list[int]:
        """Return ordinals of REGION entries that collapsed the oracle's elements.

        Separate from `entries_reaching` because a collapsed run legitimately produces two
        entries that both reach the oracle — the region and its exemplar member. Counting them
        together cannot express "20 records cost 2 entries, and exactly one of them is the
        region".
        """
        regions = {entry.ordinal for entry in self.index.entries if entry.coverage is not None}
        return [ordinal for ordinal in self.entries_reaching(oracle_xpath) if ordinal in regions]


def _build(workload_dir: Path, artifact_name: str) -> HtmlWorkload:
    """Assemble a frozen HTML workload from its manifest, ground truth, and artifact."""
    data = (workload_dir / 'artifacts' / artifact_name).read_bytes()
    return _assemble(workload_dir, data)


def _build_generated(workload_dir: Path, data: bytes, snapshot_id: str | None = None) -> HtmlWorkload:
    """Assemble a workload whose artifact is generated rather than frozen on disk.

    A megabyte artifact is not committable, so a scale workload states its generator in the
    manifest and reproduces the bytes here. Everything downstream is identical to the frozen
    path — the pruners cannot tell where the bytes came from.

    `snapshot_id` overrides the manifest's, so the same bytes can be captured twice as two
    distinct snapshots. Without that, "capture the same page again" produces a byte-identical
    snapshot and every cross-capture claim is vacuous.
    """
    return _assemble(workload_dir, data, snapshot_id=snapshot_id)


def _assemble(workload_dir: Path, data: bytes, snapshot_id: str | None = None) -> HtmlWorkload:
    """Prune, compile, and bind one workload's bytes into a walkable address space."""
    manifest = tomllib.loads((workload_dir / 'manifest.toml').read_text())
    ground_truth = tomllib.loads((workload_dir / 'ground_truth.toml').read_text())
    identity = snapshot_id or manifest['id']

    store = MemoryArtifactStore()
    artifact = store.put(
        snapshot_id=identity,
        kind=EvidenceKind.SOURCE_HTML,
        media_type='text/html',
        data=data,
    )
    snapshot = ObservationSnapshot(
        run_id=manifest['id'],
        episode_id=manifest['id'],
        snapshot_id=identity,
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


@pytest.fixture(scope='session')
def generated_html_workload() -> Callable[..., HtmlWorkload]:
    """Return a factory that assembles a source-HTML workload from generated bytes."""
    return _build_generated
