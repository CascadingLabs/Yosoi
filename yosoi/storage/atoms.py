"""Field-atom store (P2): the materialized index over the web (the SSoT).

A :class:`FieldAtom` is the durable cache unit of the field-granular redesign — one
``(field -> selector)`` fact, keyed by the **page shape** and the **verified disjoint
region** it lives in, NOT by the literal domain. A Contract is a query that resolves
to a *bundle* of atoms; many contracts over the same shape + region SHARE atoms (the
organic ``url``/``title`` is discovered once and replayed by every contract that asks
for it, on every mirror/locale of the same template).

Atom key (content-addressed): ``(page_shape, region_role, field_name, yosoi_type)``.
The literal domain is demoted to *provenance* (``domains_seen``), not identity.

P2 scope (this module + its gated dual-write):
  - define the atom and the content-addressed store with idempotent, provenance-merging
    upsert;
  - DUAL-WRITE only a discrimination-gate-ACCEPTED contract set (never internalize a
    conflation — fail closed).
Reads still come from the legacy per-contract lesson cache; atom-backed reads (and the
fail-closed cross-shape reuse gate) arrive in P3.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

# Unit separator — safe inside a content-addressed key (never appears in selectors).
_SEP = '\x1f'


def _normalize_region(root_selector: str | None, contract_name: str) -> str:
    """The durable region identity: the field's root selector, or a name-scoped fallback.

    A rooted field lives in a structural region (``.MjjYud``) that persists across every
    same-shape page, so the root selector is the cross-contract, cross-page region key —
    this is what lets two contracts SHARE an atom. A rootless field has no structural
    region anchor, so it falls back to a contract-scoped role (less generalizable, but it
    never collides with another contract's rootless field).
    """
    if root_selector:
        return ' '.join(root_selector.lower().split())
    return f'name:{contract_name}'


class FieldAtom(BaseModel):
    """One ``(field -> selector)`` fact in a verified region of a page shape.

    Attributes:
        page_shape: The ``page_shape_fp`` bucket the field was observed in (URL-independent).
        region_role: The verified disjoint region (root selector, or ``name:<contract>``).
        field_name: The contract field this selector fills.
        yosoi_type: The field's semantic type (``url``/``title``/…), or None.
        selector: The field's primary selector entry (``{type, value}``), root-relative.
        domains_seen: Provenance — the literal domains this atom has been confirmed on.
        contracts: Provenance — the contract names that have minted/used this atom.
    """

    page_shape: str
    region_role: str
    field_name: str
    yosoi_type: str | None = None
    selector: dict[str, Any]
    domains_seen: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)

    @property
    def key(self) -> str:
        """The content-addressed identity (domain-independent)."""
        return _SEP.join([self.page_shape, self.region_role, self.field_name, self.yosoi_type or ''])


def derive_atoms(
    page_shape: str,
    contract_name: str,
    domain: str | None,
    fields: list[tuple[str, dict[str, Any], str | None, str | None]],
) -> list[FieldAtom]:
    """Build the atoms a single (accepted) contract contributes on a page.

    Args:
        page_shape: The page's ``page_shape_fp`` bucket.
        contract_name: The contract being internalized (provenance + rootless region role).
        domain: The literal domain (provenance only), or None.
        fields: ``(field_name, primary_selector, root_selector, yosoi_type)`` per content
            field — ``primary_selector`` is the stored ``{type, value}`` dict.

    Returns:
        One :class:`FieldAtom` per field, region keyed by that field's root.
    """
    atoms: list[FieldAtom] = []
    for field_name, primary, root_selector, yosoi_type in fields:
        atoms.append(
            FieldAtom(
                page_shape=page_shape,
                region_role=_normalize_region(root_selector, contract_name),
                field_name=field_name,
                yosoi_type=yosoi_type,
                selector=primary,
                domains_seen=[domain] if domain else [],
                contracts=[contract_name],
            )
        )
    return atoms


class AtomStore:
    """Content-addressed :class:`FieldAtom` store with idempotent, provenance-merging upsert.

    Same key + same selector → provenance merges (``domains_seen``/``contracts`` union),
    so the organic ``url`` learned on ``google.com`` simply gains ``google.co.uk`` rather
    than spawning a second atom. Same key + a DIFFERENT selector is a conflict that
    should never occur for a gate-accepted set (disjoint regions ⇒ distinct keys); it is
    surfaced via :attr:`conflicts` rather than silently overwriting.

    ``path=None`` keeps the store in-memory (tests); a path JSONL-persists every upsert.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        """Open an atom store; ``path`` JSONL-persists upserts, ``None`` stays in-memory."""
        self._path = Path(path) if path else None
        self._atoms: dict[str, FieldAtom] = {}
        self.conflicts: list[tuple[str, dict[str, Any], dict[str, Any]]] = []
        if self._path is not None and self._path.exists():
            self._load()

    def _load(self) -> None:
        assert self._path is not None
        for line in self._path.read_text(encoding='utf-8').splitlines():
            line = line.strip()
            if line:
                atom = FieldAtom.model_validate_json(line)
                self._atoms[atom.key] = atom

    def _flush(self) -> None:
        if self._path is None:
            return
        self._path.parent.mkdir(parents=True, exist_ok=True)
        payload = '\n'.join(a.model_dump_json() for a in self._atoms.values())
        self._path.write_text(payload + ('\n' if payload else ''), encoding='utf-8')

    def upsert(self, atom: FieldAtom) -> bool:
        """Insert ``atom`` or merge its provenance into an existing one.

        Returns:
            True if this minted a NEW atom (a genuine discovery), False if it merged
            into an existing atom (a reuse — the headline win).
        """
        existing = self._atoms.get(atom.key)
        if existing is None:
            self._atoms[atom.key] = atom
            self._flush()
            return True
        if existing.selector != atom.selector:
            # Should not happen for a gate-accepted set; record, keep first-writer-wins.
            self.conflicts.append((atom.key, existing.selector, atom.selector))
        merged = existing.model_copy(
            update={
                'domains_seen': sorted(set(existing.domains_seen) | set(atom.domains_seen)),
                'contracts': sorted(set(existing.contracts) | set(atom.contracts)),
            }
        )
        self._atoms[atom.key] = merged
        self._flush()
        return False

    def upsert_all(self, atoms: list[FieldAtom]) -> int:
        """Upsert many atoms; return how many were NEW (minted, not merged)."""
        return sum(1 for a in atoms if self.upsert(a))

    def get(self, key: str) -> FieldAtom | None:
        """Return the atom with this content-addressed key, or None."""
        return self._atoms.get(key)

    def all(self) -> list[FieldAtom]:
        """Return every stored atom."""
        return list(self._atoms.values())

    def __len__(self) -> int:
        """Number of distinct atoms held."""
        return len(self._atoms)
