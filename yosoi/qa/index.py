"""Typed, read-only async surface over an existing observation index."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.observations.artifacts.protocol import ArtifactStore
from yosoi.observations.index.addressing import resolve_index_entry
from yosoi.observations.index.diff import ObservationDiff, diff_indexes
from yosoi.observations.index.inspect import (
    InspectionBudget,
    InspectionResult,
    ObservationInspector,
    RegionPage,
)
from yosoi.observations.index.paging import PageRequest
from yosoi.observations.index.render import ObservationIndexRenderer, RenderPolicy
from yosoi.observations.models.artifact import ArtifactRef, Sensitivity
from yosoi.observations.models.index import ObservationIndex
from yosoi.observations.models.snapshot import CaptureCapability, ObservationSnapshot
from yosoi.observations.models.view import RegionRef, RenderedView

if TYPE_CHECKING:
    from yosoi.qa.tools import DiffArgs, InspectArgs, OverviewArgs


class QAIndexLimits(BaseModel):
    """Hard ceilings shared by direct QA callers and the MCP transport.

    The overview ceiling is the top of the 1,000-3,000-token boss-fight band. Inspection
    retains the kernel's existing 32 KiB and 400-character defaults. Expansion lowers the
    item count so one response cannot multiply 400-character summaries across 500 members.
    """

    model_config = ConfigDict(frozen=True)

    overview_tokens: int = 3_000
    inspect_bytes: int = 32_000
    inspect_items: int = 500
    inspect_summary_chars: int = 400
    expand_items: int = 100
    expand_bytes: int = 32_000
    expand_summary_chars: int = 400
    diff_page_items: int = 100


QA_INDEX_LIMITS = QAIndexLimits()
DEFAULT_QA_OVERVIEW_TOKENS = 1_000
DEFAULT_QA_TOKENIZER_ID = 'estimate/chars-per-token-4'


class SnapshotIndexCapabilities(BaseModel):
    """Indexed and capture-declared evidence for one exact snapshot."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    indexed_modalities: tuple[str, ...] = ()
    capture_capabilities: tuple[CaptureCapability, ...] = ()
    index_complete: bool


class IndexCapabilities(BaseModel):
    """Truthful capability declaration for one read-only index session."""

    model_config = ConfigDict(frozen=True)

    modalities: tuple[str, ...] = ()
    snapshots: tuple[SnapshotIndexCapabilities, ...] = ()
    operations: tuple[str, ...] = ('capabilities', 'status')
    read_only: bool = True
    capture_wired: bool = False
    provider_wired: bool = False


class IndexStatus(BaseModel):
    """Machine-readable readiness and snapshot inventory."""

    model_config = ConfigDict(frozen=True)

    ready: bool
    snapshot_ids: tuple[str, ...]
    message: str
    capabilities: IndexCapabilities


def _validate_budget(budget: InspectionBudget, limits: QAIndexLimits, *, expand: bool) -> None:
    """Reject oversized budgets instead of treating positive values as ceilings."""
    prefix = 'expand' if expand else 'inspect'
    checks = {
        'max_bytes': limits.expand_bytes if expand else limits.inspect_bytes,
        'max_items': limits.expand_items if expand else limits.inspect_items,
        'max_summary_chars': limits.expand_summary_chars if expand else limits.inspect_summary_chars,
    }
    if budget.allow_restricted:
        raise ValueError(f'{prefix} cannot request restricted evidence')
    for name, ceiling in checks.items():
        if getattr(budget, name) > ceiling:
            raise ValueError(f'{prefix} {name} exceeds QA ceiling of {ceiling}')


class ExpandArgs(BaseModel):
    """Bounded expansion request; ordinal is resolved against the overview index."""

    model_config = ConfigDict(frozen=True)

    snapshot_id: str = Field(min_length=1)
    ordinal: int | None = Field(default=None, ge=0)
    ref: RegionRef | None = None
    budget: InspectionBudget = Field(
        default_factory=lambda: InspectionBudget(
            max_bytes=QA_INDEX_LIMITS.expand_bytes,
            max_items=QA_INDEX_LIMITS.expand_items,
            max_summary_chars=QA_INDEX_LIMITS.expand_summary_chars,
        )
    )
    offset: int = Field(default=0, ge=0)

    @model_validator(mode='after')
    def _bounded(self) -> ExpandArgs:
        _validate_budget(self.budget, QA_INDEX_LIMITS, expand=True)
        return self


def _validated_sources(
    store: ArtifactStore, snapshot: ObservationSnapshot, observation_index: ObservationIndex
) -> dict[str, ArtifactRef]:
    """Validate the index-to-artifact boundary and return sources keyed by digest."""
    sources_by_digest = {source.sha256: source for source in observation_index.sources}
    if len(sources_by_digest) != len(observation_index.sources):
        raise ValueError('index sources must not repeat an artifact digest')
    for source in observation_index.sources:
        if source not in snapshot.artifacts:
            raise ValueError('every index source must be an artifact declared by its snapshot')
        if source.sensitivity is not Sensitivity.MODEL_SAFE:
            raise PermissionError('QA index sessions cannot expose restricted evidence')
    source_modalities = {source.kind for source in observation_index.sources}
    if set(observation_index.modalities) != source_modalities:
        raise ValueError('index modalities must exactly describe its source artifact kinds')
    for artifact in snapshot.artifacts:
        if not store.contains(artifact):
            raise ValueError(f'artifact {artifact.sha256!r} is missing or failed integrity verification')
    return sources_by_digest


def _validate_entry_modalities(
    observation_index: ObservationIndex, sources_by_digest: Mapping[str, ArtifactRef]
) -> None:
    """Refuse an index whose entry claims a modality different from its source."""
    for entry in observation_index.entries:
        source = sources_by_digest[entry.ref.artifact_sha256]
        if entry.ref.modality is not source.kind:
            raise ValueError('index entry modality must agree with its source artifact')


class IndexSession:
    """Provider-neutral session bound to immutable snapshots, indexes, and bytes."""

    def __init__(
        self, *, store: ArtifactStore, snapshots: Sequence[ObservationSnapshot], indexes: Sequence[ObservationIndex]
    ) -> None:
        """Bind immutable evidence, rejecting ambiguous or incomplete manifests."""
        if len({item.snapshot_id for item in snapshots}) != len(snapshots):
            raise ValueError('duplicate snapshot ids are not allowed')
        if len({item.snapshot_id for item in indexes}) != len(indexes):
            raise ValueError('duplicate index snapshot ids are not allowed')
        self._store = store
        self._snapshots = {item.snapshot_id: item for item in snapshots}
        self._indexes = {item.snapshot_id: item for item in indexes}
        if set(self._snapshots) != set(self._indexes):
            raise ValueError('every snapshot must have exactly one observation index')
        for snapshot_id, observation_index in self._indexes.items():
            if observation_index.snapshot_id != snapshot_id:
                raise ValueError('snapshot and index ids must agree')
            snapshot = self._snapshots[snapshot_id]
            sources_by_digest = _validated_sources(self._store, snapshot, observation_index)
            _validate_entry_modalities(observation_index, sources_by_digest)

    async def capabilities(self) -> IndexCapabilities:
        """Report indexed evidence and explicit unavailable-capture reasons per snapshot."""
        kinds = sorted({kind.value for index in self._indexes.values() for kind in index.modalities})
        operations = ('capabilities', 'status')
        if self._indexes:
            operations += ('overview', 'inspect', 'expand')
        if len(self._indexes) > 1:
            operations += ('diff',)
        snapshots = tuple(
            SnapshotIndexCapabilities(
                snapshot_id=snapshot_id,
                indexed_modalities=tuple(kind.value for kind in observation_index.modalities),
                capture_capabilities=self._snapshots[snapshot_id].capabilities,
                index_complete=observation_index.page is None or observation_index.page.complete,
            )
            for snapshot_id, observation_index in self._indexes.items()
        )
        return IndexCapabilities(modalities=tuple(kinds), snapshots=snapshots, operations=operations)

    async def status(self) -> IndexStatus:
        """Return readiness for the supplied offline evidence."""
        capabilities = await self.capabilities()
        return IndexStatus(
            ready=bool(self._indexes),
            snapshot_ids=tuple(self._indexes),
            message='read-only observation indexes are available' if self._indexes else 'no observation index is wired',
            capabilities=capabilities,
        )

    def _ref(self, snapshot_id: str, ordinal: int | None, ref: RegionRef | None) -> RegionRef:
        if (ordinal is None) == (ref is None):
            raise ValueError('provide exactly one of ordinal or ref')
        index = self._indexes.get(snapshot_id)
        if index is None:
            raise KeyError(f'unknown snapshot {snapshot_id!r}')
        if ref is not None:
            resolve_index_entry(index, ref)
            return ref
        assert ordinal is not None
        matches = [entry for entry in index.entries if entry.ordinal == ordinal]
        if len(matches) != 1:
            raise LookupError(f'ordinal {ordinal} resolved to {len(matches)} index entries')
        return matches[0].ref

    async def overview(self, args: OverviewArgs) -> RenderedView:
        """Render the existing index; semantic pruning is never repeated here."""
        index = self._indexes.get(args.snapshot_id)
        if index is None:
            raise KeyError(f'unknown snapshot {args.snapshot_id!r}')
        if args.token_budget > QA_INDEX_LIMITS.overview_tokens:
            raise ValueError(f'overview token_budget exceeds QA ceiling of {QA_INDEX_LIMITS.overview_tokens}')
        return ObservationIndexRenderer().render(
            index,
            RenderPolicy(tokenizer_id=args.tokenizer_id, token_budget=args.token_budget),
        )

    async def inspect(self, args: InspectArgs) -> InspectionResult:
        """Resolve an exact reference and inspect canonical bytes under a hard budget."""
        if args.ref is not None:
            ref = args.ref
            snapshot_id = ref.snapshot_id
        else:
            if args.snapshot_id is None or args.ordinal is None:
                raise ValueError('inspect requires ref or snapshot_id plus ordinal')
            snapshot_id = args.snapshot_id
            ref = self._ref(snapshot_id, args.ordinal, None)
        snapshot = self._snapshots.get(snapshot_id)
        if snapshot is None:
            raise KeyError(f'unknown snapshot {snapshot_id!r}')
        ref = resolve_index_entry(self._indexes[snapshot_id], ref).ref
        _validate_budget(args.budget, QA_INDEX_LIMITS, expand=False)
        return ObservationInspector(self._store, snapshot).inspect(ref, args.budget)

    async def expand(self, args: ExpandArgs) -> RegionPage:
        """Resolve an overview ordinal, then expand only the addressed region."""
        ref = self._ref(args.snapshot_id, args.ordinal, args.ref)
        snapshot = self._snapshots[args.snapshot_id]
        _validate_budget(args.budget, QA_INDEX_LIMITS, expand=True)
        return ObservationInspector(self._store, snapshot).expand(ref, args.budget, offset=args.offset)

    async def diff(self, args: DiffArgs) -> ObservationDiff:
        """Compare two supplied indexes by durable identity, not ordinal."""
        try:
            before = self._indexes[args.before_snapshot_id]
            after = self._indexes[args.after_snapshot_id]
        except KeyError as exc:
            raise KeyError(f'unknown snapshot {exc.args[0]!r}') from exc
        return diff_indexes(before, after, PageRequest(offset=args.offset, limit=args.limit))


async def index(
    *,
    store: ArtifactStore,
    snapshot: ObservationSnapshot,
    observation_index: ObservationIndex,
    related: Mapping[str, tuple[ObservationSnapshot, ObservationIndex]] | None = None,
) -> IndexSession:
    """Create a read-only session over one index and optional related snapshots."""
    pairs = [(snapshot, observation_index)]
    if related:
        for key, pair in related.items():
            if key != pair[0].snapshot_id:
                raise ValueError('related mapping keys must equal related snapshot ids')
            pairs.append(pair)
    return IndexSession(store=store, snapshots=[pair[0] for pair in pairs], indexes=[pair[1] for pair in pairs])


__all__ = [
    'DEFAULT_QA_OVERVIEW_TOKENS',
    'DEFAULT_QA_TOKENIZER_ID',
    'QA_INDEX_LIMITS',
    'ExpandArgs',
    'IndexCapabilities',
    'IndexSession',
    'IndexStatus',
    'QAIndexLimits',
    'SnapshotIndexCapabilities',
    'index',
]
