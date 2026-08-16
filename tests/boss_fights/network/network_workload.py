"""Assembly for a network boss-fight workload: bytes → view → index → walkable address space.

Deliberately local to `tests/boss_fights/network/` rather than added to the shared
`tests/boss_fights/conftest.py`. That conftest's `HtmlWorkload` is HTML-shaped down to its oracle
mapping (it resolves lxml XPaths), and every modality author would be editing the same file at the
same time. Keeping this here makes the shared fixture file untouched and a hand merge trivial.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import tomllib

from tests.boss_fights.generators.network_trace import render_network_trace
from yosoi.observations.artifacts.memory import MemoryArtifactStore
from yosoi.observations.index.addressing import parse_address
from yosoi.observations.index.compiler import ObservationIndexCompiler
from yosoi.observations.index.inspect import InspectionBudget, ObservationInspector, RegionPage
from yosoi.observations.index.render import CharacterEstimator, ObservationIndexRenderer, RenderPolicy
from yosoi.observations.models.artifact import EvidenceKind
from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.network import NetworkRequest, NetworkTrace, parse_network_trace
from yosoi.observations.models.snapshot import CaptureProfile, ObservationSnapshot
from yosoi.observations.models.view import PrunedView, RenderedView
from yosoi.observations.network_tree import EndpointGroup, resolve_network_address
from yosoi.observations.pruning.network import NetworkPruner
from yosoi.observations.pruning.protocol import PruningInput, PruningPolicy


@dataclass(frozen=True)
class NetworkWorkload:
    """One seeded network workload assembled into an addressable index."""

    manifest: dict
    ground_truth: dict
    data: bytes
    trace: NetworkTrace
    store: MemoryArtifactStore
    snapshot: ObservationSnapshot
    view: PrunedView
    index: ObservationIndex
    inspector: ObservationInspector

    def entries_reaching(self, request_id: str) -> list[int]:
        """Return the ordinals whose emitted address reaches one request named by ground truth.

        Ground truth names evidence by `request_id` — a property of the artifact, like an XPath
        oracle is a property of a document — and this maps it to whatever address the pruner chose.
        Mapping goes through the production resolver, so the harness knows only that an address
        resolves, never how the locator grammar spells it.

        Trace-root and origin entries are excluded even though every request is technically "under"
        them. Reaching a request has to mean the reader can address that request, not that they
        could address the whole capture.
        """
        reached: list[int] = []
        for entry in self.index.entries:
            target = resolve_network_address(self.trace, parse_address(entry.ref.locator))
            if (isinstance(target, NetworkRequest) and target.request_id == request_id) or (
                isinstance(target, EndpointGroup) and any(r.request_id == request_id for r in target.requests)
            ):
                reached.append(entry.ordinal)
        return reached

    def regions(self) -> list[int]:
        """Return the ordinals of every endpoint region in the index."""
        return [entry.ordinal for entry in self.index.entries if entry.coverage is not None]

    def members(self) -> list[int]:
        """Return the ordinals of every entry that addresses one individual request."""
        return [
            entry.ordinal
            for entry in self.index.entries
            if parse_address(entry.ref.locator).segments[-1].selects_member
        ]

    def inspect_bytes(self, ordinal: int, budget: InspectionBudget | None = None) -> bytes:
        """Return the canonical detail one index entry addresses."""
        entry = self.index.entries[ordinal]
        return self.inspector.inspect(entry.ref, budget or InspectionBudget()).content

    def expand(self, ordinal: int, budget: InspectionBudget | None = None, *, offset: int = 0) -> RegionPage:
        """Return one bounded page of the requests an endpoint region collapsed."""
        entry = self.index.entries[ordinal]
        return self.inspector.expand(entry.ref, budget or InspectionBudget(), offset=offset)

    def render(self, token_budget: int, *, max_entry_tokens: int = 48) -> RenderedView:
        """Return a budgeted overview of the whole index, measured by the character estimator."""
        estimator = CharacterEstimator()
        policy = RenderPolicy(tokenizer_id=estimator.id, token_budget=token_budget, max_entry_tokens=max_entry_tokens)
        return ObservationIndexRenderer().render(self.index, policy, estimator)


def build_network_workload(workload_dir: Path, snapshot_id: str | None = None) -> NetworkWorkload:
    """Assemble a seeded network workload from its manifest, ground truth, and generator."""
    manifest = tomllib.loads((workload_dir / 'manifest.toml').read_text())
    ground_truth = tomllib.loads((workload_dir / 'ground_truth.toml').read_text())
    identity = snapshot_id or manifest['id']
    data = render_network_trace(identity)

    store = MemoryArtifactStore()
    artifact = store.put(snapshot_id=identity, kind=EvidenceKind.NETWORK, media_type='application/json', data=data)
    snapshot = ObservationSnapshot(
        run_id=manifest['id'],
        episode_id=manifest['id'],
        snapshot_id=identity,
        requested_profile=CaptureProfile(manifest['capture_profile']),
        artifacts=(artifact,),
    )
    view = NetworkPruner().prune(PruningInput(source=artifact, data=data), PruningPolicy())
    return NetworkWorkload(
        manifest=manifest,
        ground_truth=ground_truth,
        data=data,
        trace=parse_network_trace(data),
        store=store,
        snapshot=snapshot,
        view=view,
        index=ObservationIndexCompiler().compile(snapshot, (view,)),
        inspector=ObservationInspector(store, snapshot),
    )


__all__ = ['NetworkWorkload', 'build_network_workload']
