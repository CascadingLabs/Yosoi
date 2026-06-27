"""Atom-backed reads (P3): resolve a contract as a JOIN over the field-atom index.

P2 builds the atom corpus (gated dual-write). P3 lets it SERVE reads — behind a flag,
fail closed. A contract is a query: for each field we look up its atom by
``(page_shape, field_fingerprint)`` and reuse the cached selector instead of
re-discovering. Misses fall through to the normal discovery path, so a contract that
GROWS by one field discovers exactly that one atom and replays the rest.

Fail-closed safety:
  * EXACT page-shape only — a field is never served from a different (even similar) shape
    bucket. Near-shape reuse (the cas-85 ALLOW/REFUSE/ABSTAIN recommender) is a deliberate
    follow-up; until then any non-identical shape is REFUSED by construction.
  * UNAMBIGUOUS only — if a field fingerprint has atoms in more than one region on this shape
    (e.g. ``url`` exists for both an ad region and an organic region), the read ABSTAINS
    and the field is discovered, because we cannot know which region this contract means
    without the discrimination step. Reusing the wrong region is the exact silent-
    corruption failure the whole redesign exists to prevent.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from pydantic import BaseModel, Field

from yosoi.storage.atoms import AtomStore, FieldAtom
from yosoi.utils.signatures import field_signature

RequestedAtomField = tuple[str, str | None] | tuple[str, str | None, str]


class AtomResolution(BaseModel):
    """Outcome of resolving a contract's fields against the atom index."""

    hits: dict[str, FieldAtom] = Field(default_factory=dict)
    misses: list[str] = Field(default_factory=list)  # no atom on this shape → discover
    ambiguous: list[str] = Field(default_factory=list)  # >1 region → fail-closed → discover

    @property
    def fully_resolved(self) -> bool:
        """True when every requested field was served from the index (zero discovery)."""
        return not self.misses and not self.ambiguous

    @property
    def to_discover(self) -> list[str]:
        """Fields the index could not safely serve — misses plus ambiguous."""
        return sorted([*self.misses, *self.ambiguous])


def resolve_via_atoms(
    page_shape: str,
    requested: Sequence[RequestedAtomField],
    store: AtomStore,
    allowed: frozenset[str] | None = None,
) -> AtomResolution:
    """Resolve requested fields against the atom index.

    ``requested`` entries may be legacy ``(field_name, yosoi_type)`` pairs or
    ``(field_name, yosoi_type, field_fingerprint)`` triples.

    Exact ``page_shape`` only; a field served only when exactly one region on this shape
    holds it (fail closed on 0 and on >1). ``allowed`` restricts which provenance ``source``
    tiers are eligible — a quarantined atom (e.g. ``fingerprint`` under strict mode) is
    invisible, so its field misses and falls through to discovery. ``None`` allows all tiers.
    """
    from yosoi.generalization.fingerprint import is_degenerate_shape

    res = AtomResolution()
    if is_degenerate_shape(page_shape):
        # a too-thin page collapses to a shared degenerate bucket — never reuse across it
        res.misses.extend(field[0] for field in requested)
        return res

    by_field: dict[str, list[FieldAtom]] = {}
    for atom in store.all():
        if atom.page_shape != page_shape:
            continue
        if allowed is not None and atom.source not in allowed:
            continue  # quarantined source under the active trust mode → not eligible
        atom_fp = atom.field_fingerprint or field_signature(atom.field_name, '', atom.yosoi_type)
        by_field.setdefault(atom_fp, []).append(atom)

    for field in requested:
        field_name, yosoi_type = field[0], field[1]
        field_fp = field[2] if len(field) == 3 else field_signature(field_name, '', yosoi_type)
        candidates = by_field.get(field_fp, [])
        if len(candidates) == 1:
            res.hits[field_name] = candidates[0]
        elif not candidates:
            res.misses.append(field_name)
        else:
            res.ambiguous.append(field_name)
    return res


def selector_map_from_atoms(hits: dict[str, FieldAtom]) -> dict[str, dict[str, Any]]:
    """Rebuild a discovery-shaped selector map ``{field: {primary, root?}}`` from atoms.

    The region role doubles as the (case-preserved) root CSS selector; a ``name:``-scoped
    rootless atom contributes no root.
    """
    out: dict[str, dict[str, Any]] = {}
    for field_name, atom in hits.items():
        entry: dict[str, Any] = {'primary': atom.selector}
        if not atom.region_role.startswith('name:'):
            entry['root'] = {'type': 'css', 'value': atom.region_role}
        out[field_name] = entry
    return out
