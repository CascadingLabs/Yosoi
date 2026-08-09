"""Bounded canonical-detail inspection and region expansion.

Two verbs, both one hop and both bounded:

    inspect(ref)                    detail for one addressed thing
    expand(region, offset, limit)   a page of members of a repeat region

`expand` exists because `inspect` on a collapsed 10,000-member region can only return one row
or forty megabytes, and neither is a zoom. Both re-derive detail from canonical bytes rather
than from a summary — which is what keeps a finding re-checkable against exact bytes instead
of an opinion about a reduction.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import TYPE_CHECKING

from pydantic import BaseModel, ConfigDict, Field

from yosoi.observations.artifacts.protocol import ArtifactStore
from yosoi.observations.dom_tree import (
    assign_dom_member_keys,
    dom_candidate_keys,
    dom_label,
    dom_member_summary,
    dom_region_coverage,
    dom_skeleton_signature,
    node_id_from_locator,
)
from yosoi.observations.html_tree import (
    SignatureCache,
    assign_member_keys,
    content_children,
    matches_key,
    node_label,
    parse,
    skeleton_signature,
    subtree_text,
)
from yosoi.observations.index.addressing import (
    ObservationAddress,
    ObservationAddressError,
    format_address,
    parse_address,
)
from yosoi.observations.models.artifact import ArtifactRef, EvidenceKind, Sensitivity
from yosoi.observations.models.dom import DomNode, DomSnapshot, parse_dom_snapshot
from yosoi.observations.models.snapshot import ObservationSnapshot
from yosoi.observations.models.view import RegionCoverage, RegionRef

if TYPE_CHECKING:
    from lxml.etree import _Element, _ElementTree


class InspectionBudget(BaseModel):
    """Hard limits for one direct retrieval from canonical evidence."""

    model_config = ConfigDict(frozen=True)

    max_bytes: int = Field(default=32_000, gt=0)
    max_items: int = Field(default=500, gt=0)
    max_summary_chars: int = Field(default=400, gt=0)
    """Per-member summary bound for `expand`, declared separately from `max_bytes`.

    `max_bytes` bounds one retrieval of canonical evidence. Reusing it as a summary limit made a
    page of members cost `max_items × max_bytes` — 500 members of 32 KB each — so the two
    budgets that look alike are stated apart. Bounding the whole page rather than each member is
    a further step, and it changes what an already-gated sweep returns, so it is not taken here.
    """

    allow_restricted: bool = False


class InspectionResult(BaseModel):
    """Bounded detail returned for one exact observation reference."""

    model_config = ConfigDict(frozen=True)

    ref: RegionRef
    media_type: str = Field(min_length=1)
    content: bytes
    returned_bytes: int = Field(ge=0)
    returned_items: int = Field(ge=0)
    truncated: bool = False


class RegionMember(BaseModel):
    """One member of an expanded region, addressed durably where the page allows it."""

    model_config = ConfigDict(frozen=True)

    ref: RegionRef
    ordinal: int = Field(ge=0)
    label: str = Field(min_length=1)
    summary: str
    stable: bool


class RegionPage(BaseModel):
    """One bounded page of members drawn from a repeat region."""

    model_config = ConfigDict(frozen=True)

    region: RegionRef
    members: tuple[RegionMember, ...] = ()
    offset: int = Field(ge=0)
    coverage: RegionCoverage
    truncated: bool = False


def _resolve_segments(tree: _ElementTree, address: ObservationAddress) -> _Element:
    """Walk an address segment by segment, failing closed at the first ambiguity."""
    from lxml import etree

    current: _Element | _ElementTree = tree
    for segment in address.segments:
        try:
            matches = current.xpath(segment.path)
        except etree.XPathError as exc:
            raise ObservationAddressError(f'address segment {segment.path!r} is not a valid path') from exc
        if not isinstance(matches, list) or len(matches) != 1:
            count = len(matches) if isinstance(matches, list) else 1
            raise ObservationAddressError(f'address segment {segment.path!r} resolved to {count} nodes')
        current = matches[0]
        if segment.selects_member:
            current = _select_member(current, segment.shape or '', key=segment.key, ordinal=segment.ordinal)
    return current


def _region_members(container: _Element, shape: str) -> list[_Element]:
    """Return the container's children whose shape matches, preserving document order."""
    cache: SignatureCache = {}
    members = [child for child in content_children(container) if skeleton_signature(child, cache) == shape]
    if not members:
        raise ObservationAddressError(f'no members of shape {shape!r} remain in this region')
    return members


def _select_member(container: _Element, shape: str, *, key: str | None, ordinal: int | None) -> _Element:
    """Select one member of a region by durable key, or by declared-unstable position."""
    members = _region_members(container, shape)
    if key is not None:
        matched = [member for member in members if matches_key(member, key)]
        if len(matched) != 1:
            raise ObservationAddressError(f'region key {key!r} resolved to {len(matched)} members')
        return matched[0]
    position = ordinal or 0
    if position >= len(members):
        raise ObservationAddressError(f'region member ordinal {position} is past the {len(members)} members present')
    return members[position]


def _dom_nodes(snapshot: DomSnapshot) -> dict[str, DomNode]:
    """Index light-DOM and shadow-root nodes by their exact snapshot-local IDs."""
    nodes: dict[str, DomNode] = {}

    def visit(node: DomNode) -> None:
        nodes[node.node_id] = node
        for child in node.children:
            visit(child)
        if node.shadow_root is not None:
            visit(node.shadow_root)

    visit(snapshot.root)
    return nodes


def _dom_region_members(container: DomNode, shape: str) -> list[DomNode]:
    """Return direct DOM children matching one state-aware repeat shape."""
    members = [child for child in container.children if dom_skeleton_signature(child) == shape]
    if not members:
        raise ObservationAddressError(f'no DOM members of shape {shape!r} remain in this region')
    return members


def _parse_dom_artifact(artifact: ArtifactRef, data: bytes) -> DomSnapshot:
    """Parse DOM bytes and bind their self-described snapshot identity to the artifact."""
    snapshot = parse_dom_snapshot(data)
    if snapshot.snapshot_id != artifact.snapshot_id:
        raise ObservationAddressError('rendered-DOM payload snapshot disagrees with its artifact')
    return snapshot


def _resolve_dom_address(snapshot: DomSnapshot, address: ObservationAddress) -> DomNode:
    """Resolve one DOM address using node IDs and the shared repeat signature/key rules."""
    if len(address.segments) != 1:
        raise ObservationAddressError('rendered-DOM addresses currently support one segment')
    segment = address.segments[0]
    try:
        node_id = node_id_from_locator(segment.path)
    except ValueError as exc:
        raise ObservationAddressError(str(exc)) from exc
    node = _dom_nodes(snapshot).get(node_id)
    if node is None:
        raise ObservationAddressError(f'DOM node {node_id!r} is absent from this snapshot')
    if not segment.selects_member:
        return node

    members = _dom_region_members(node, segment.shape or '')
    if segment.key is not None:
        matched = [member for member in members if segment.key in dom_candidate_keys(member)]
        if len(matched) != 1:
            raise ObservationAddressError(f'DOM region key {segment.key!r} resolved to {len(matched)} members')
        return matched[0]
    position = segment.ordinal or 0
    if position >= len(members):
        raise ObservationAddressError(
            f'DOM region member ordinal {position} is past the {len(members)} members present'
        )
    return members[position]


class ObservationInspector:
    """Resolve observation references to bounded detail from one exact snapshot."""

    def __init__(self, store: ArtifactStore, snapshot: ObservationSnapshot) -> None:
        """Bind an inspector to the immutable store and manifest it may read."""
        self._store = store
        self._snapshot = snapshot
        self._artifacts: dict[str, ArtifactRef] = {artifact.sha256: artifact for artifact in snapshot.artifacts}

    def _artifact_for(self, ref: RegionRef, *, allow_restricted: bool) -> ArtifactRef:
        """Validate a reference against this snapshot and return the artifact it names."""
        if ref.snapshot_id != self._snapshot.snapshot_id:
            raise ObservationAddressError('observation reference belongs to a different snapshot')
        artifact = self._artifacts.get(ref.artifact_sha256)
        if artifact is None:
            raise ObservationAddressError('observation reference targets an artifact this snapshot does not declare')
        if artifact.kind != ref.modality:
            raise ObservationAddressError('observation reference modality disagrees with its artifact')
        if artifact.sensitivity in {Sensitivity.RESTRICTED, Sensitivity.EPHEMERAL_SECRET} and not allow_restricted:
            raise PermissionError('restricted observation evidence requires explicit inspection permission')
        if artifact.kind not in {EvidenceKind.SOURCE_HTML, EvidenceKind.RENDERED_DOM}:
            raise NotImplementedError(
                f'{artifact.kind.value} inspection is not implemented; see observations/ROADMAP.md'
            )
        return artifact

    def inspect(self, ref: RegionRef, budget: InspectionBudget) -> InspectionResult:
        """Return bounded canonical detail, failing closed on stale or foreign references."""
        artifact = self._artifact_for(ref, allow_restricted=budget.allow_restricted)
        address = parse_address(ref.locator)
        data = self._store.read(artifact)

        if artifact.kind is EvidenceKind.RENDERED_DOM:
            node = _resolve_dom_address(_parse_dom_artifact(artifact, data), address)
            serialized = node.model_dump_json().encode('utf-8')
        else:
            from lxml import etree

            _, tree = parse(data)
            serialized = etree.tostring(_resolve_segments(tree, address), encoding='utf-8')

        content = serialized[: budget.max_bytes]
        return InspectionResult(
            ref=ref,
            media_type=artifact.media_type,
            content=content,
            returned_bytes=len(content),
            returned_items=1,
            truncated=len(serialized) > budget.max_bytes,
        )

    def rebind(self, ref: RegionRef, keys: str | Sequence[str], *, at: int = 0) -> RegionRef:
        """Return the same reference pointed at a different branch of its nested regions.

        The index describes the exemplar branch of every nested repeat, so this is how a route
        learned at member 1 gets applied to member N without re-indexing anything or reading the
        subtree back as bytes.

        Member keys below the one being swapped are BRANCH-SPECIFIC — `id=team-1-1` exists only
        inside department 1 — so an address with several member segments needs a key for each
        one from `at` onward. Passing a single key when deeper selections remain is refused with
        the count needed, rather than resolved loosely or silently downgraded to a position.

        The rebound reference is resolved here before it is returned: a key that names no member
        fails now, not later as a reference that looked fine.
        """
        artifact = self._artifact_for(ref, allow_restricted=False)
        address = parse_address(ref.locator)
        replacements = [keys] if isinstance(keys, str) else list(keys)
        remaining = len(address.member_segments()) - at
        if len(replacements) < remaining:
            raise ObservationAddressError(
                f'rebinding from member {at} needs {remaining} key(s) — member selections below the '
                f'first are branch-specific and cannot survive the change; got {len(replacements)}'
            )
        rebound = address
        for offset, key in enumerate(replacements):
            rebound = rebound.rebind_member(key, at=at + offset)

        # Resolve through the modality's own resolver. Reading DOM JSON with the HTML parser
        # produced a tree nothing could match, so a rebind that named a real member failed as
        # "segment resolved to 0 nodes" — a grammar error for what was a modality mistake.
        data = self._store.read(artifact)
        if artifact.kind is EvidenceKind.RENDERED_DOM:
            _resolve_dom_address(_parse_dom_artifact(artifact, data), rebound)
        else:
            _, tree = parse(data)
            _resolve_segments(tree, rebound)
        return RegionRef(
            snapshot_id=ref.snapshot_id,
            artifact_sha256=ref.artifact_sha256,
            modality=ref.modality,
            locator=format_address(rebound),
        )

    def expand(self, ref: RegionRef, budget: InspectionBudget, *, offset: int = 0) -> RegionPage:
        """Return one bounded page of a region's members, addressed durably where possible."""
        artifact = self._artifact_for(ref, allow_restricted=budget.allow_restricted)
        address = parse_address(ref.locator)
        if not address.is_region:
            raise ObservationAddressError('expand requires a region address; inspect addresses one element')
        if offset < 0:
            raise ObservationAddressError('region expansion offset cannot be negative')

        data = self._store.read(artifact)
        if artifact.kind is EvidenceKind.RENDERED_DOM:
            snapshot = _parse_dom_artifact(artifact, data)
            container = _resolve_dom_address(snapshot, address)
            shape = address.segments[-1].shape or ''
            members = _dom_region_members(container, shape)
            keys = assign_dom_member_keys(tuple(members))
            window = list(zip(members, keys, strict=True))[offset : offset + budget.max_items]
            page = tuple(
                RegionMember(
                    ref=RegionRef(
                        snapshot_id=ref.snapshot_id,
                        artifact_sha256=ref.artifact_sha256,
                        modality=ref.modality,
                        locator=format_address(
                            address.member(key=key, ordinal=None if key is not None else offset + position)
                        ),
                    ),
                    ordinal=offset + position,
                    label=dom_label(member),
                    summary=dom_member_summary(member, max_chars=budget.max_summary_chars),
                    stable=key is not None,
                )
                for position, (member, key) in enumerate(window)
            )
            return RegionPage(
                region=ref,
                members=page,
                offset=offset,
                coverage=dom_region_coverage(container, members),
                truncated=offset + len(window) < len(members),
            )

        _, tree = parse(data)
        container = _resolve_segments(tree, address)
        shape = address.segments[-1].shape or ''
        members = _region_members(container, shape)
        keys = assign_member_keys(members)
        window = list(zip(members, keys, strict=True))[offset : offset + budget.max_items]

        page = tuple(
            RegionMember(
                ref=RegionRef(
                    snapshot_id=ref.snapshot_id,
                    artifact_sha256=ref.artifact_sha256,
                    modality=ref.modality,
                    locator=format_address(
                        address.member(key=key, ordinal=None if key is not None else offset + position)
                    ),
                ),
                ordinal=offset + position,
                label=node_label(member),
                summary=subtree_text(member)[: budget.max_summary_chars],
                stable=key is not None,
            )
            for position, (member, key) in enumerate(window)
        )
        return RegionPage(
            region=ref,
            members=page,
            offset=offset,
            # Static HTML holds every member it has. A rendered snapshot of a virtualised
            # list will report a smaller `observed` than the container declares.
            coverage=RegionCoverage(observed=len(members), declared=len(members), complete=True),
            truncated=offset + len(window) < len(members),
        )


__all__ = [
    'InspectionBudget',
    'InspectionResult',
    'ObservationInspector',
    'RegionMember',
    'RegionPage',
]
