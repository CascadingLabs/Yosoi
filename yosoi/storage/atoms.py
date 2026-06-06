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
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

# Unit separator — safe inside a content-addressed key (never appears in selectors).
_SEP = '\x1f'

# Default on-disk field-atom corpus (gitignored like the rest of .yosoi/).
DEFAULT_STORE_PATH = '.yosoi/atoms.jsonl'

# Provenance / trust tiers — HOW an atom's selector was obtained (never lost). Most-truthy first:
#   'verified'    — LLM-discovered AND passed discrimination/verification on the real DOM.
#   'llm'         — LLM-discovered on the actual page, not independently verified.
#   'manual'      — hand-coded / pinned (yosoi_selector); human-asserted.
#   'fingerprint' — reused via similarity/generality fingerprint match (NOT discovered on this
#                   page) → lowest trust, DEFAULT-QUARANTINED. The fingerprint proposes; the
#                   trust policy (see yosoi.core.atom_read) decides what is actually served.
AtomSource = Literal['verified', 'llm', 'manual', 'fingerprint']
SOURCE_TRUST: dict[str, int] = {'verified': 3, 'manual': 2, 'llm': 2, 'fingerprint': 1}

# Atom-corpus identity scheme (P4). Bump when the atom KEY or the fingerprint that feeds it
# changes shape (e.g. the P5 waterfall fingerprint), so a post-bump load-miss is reported
# STALE (→ lazy re-mint) instead of silently re-discovering — mirrors the lesson store's
# SIGNATURE_SCHEME_VERSION discipline. NOTE: in the atom model the monolithic
# ``contract_signature`` and the literal domain are NOT identity — atoms key on
# (page_shape, region, field, type); domain lives in ``domains_seen`` provenance only.
ATOM_SCHEME_VERSION = 'a1'


def _normalize_region(root_selector: str | None, contract_name: str) -> str:
    """The durable region identity: the field's root selector, or a name-scoped fallback.

    A rooted field lives in a structural region (``.MjjYud``) that persists across every
    same-shape page, so the root selector is the cross-contract, cross-page region key —
    this is what lets two contracts SHARE an atom. A rootless field has no structural
    region anchor, so it falls back to a contract-scoped role (less generalizable, but it
    never collides with another contract's rootless field).

    Only whitespace is collapsed — case is PRESERVED, because the region role doubles as
    the root CSS selector at replay time and CSS class names are case-sensitive
    (``.MjjYud`` != ``.mjjyud``).
    """
    if root_selector:
        return ' '.join(root_selector.split())
    return f'name:{contract_name}'


class FieldAtom(BaseModel):
    """One ``(field -> selector)`` fact in a verified region of a page shape.

    Attributes:
        page_shape: The ``page_shape_fp`` bucket the field was observed in (URL-independent).
        region_role: The verified disjoint region (root selector, or ``name:<contract>``).
        field_name: The contract field this selector fills.
        yosoi_type: The field's semantic type (``url``/``title``/…), or None.
        selector: The field's primary selector entry (``{type, value}``), root-relative.
        source: Provenance trust tier — how this selector was obtained (see ``SOURCE_TRUST``).
        scheme: Atom identity-scheme version it was minted under (see ``ATOM_SCHEME_VERSION``);
            empty means a pre-versioning atom. Drives ``list_stale_by_scheme`` migration.
        domains_seen: Provenance — the literal domains this atom has been confirmed on.
        contracts: Provenance — the contract names that have minted/used this atom.
    """

    page_shape: str = Field(min_length=1)
    region_role: str = Field(min_length=1)
    field_name: str = Field(min_length=1)
    yosoi_type: str | None = None
    selector: dict[str, Any]
    source: AtomSource = 'llm'
    scheme: str = ''
    domains_seen: list[str] = Field(default_factory=list)
    contracts: list[str] = Field(default_factory=list)

    @field_validator('selector')
    @classmethod
    def _selector_has_value(cls, v: dict[str, Any]) -> dict[str, Any]:
        """An atom selector must carry a non-empty ``value`` — an empty selector is unservable."""
        if not (isinstance(v, dict) and v.get('value')):
            raise ValueError('atom selector must carry a non-empty "value"')
        return v

    @property
    def key(self) -> str:
        """The content-addressed identity (domain-independent)."""
        return _SEP.join([self.page_shape, self.region_role, self.field_name, self.yosoi_type or ''])


def derive_atoms(
    page_shape: str,
    contract_name: str,
    domain: str | None,
    fields: list[tuple[str, dict[str, Any], str | None, str | None]],
    source: AtomSource = 'llm',
) -> list[FieldAtom]:
    """Build the atoms a single (accepted) contract contributes on a page.

    Args:
        page_shape: The page's ``page_shape_fp`` bucket.
        contract_name: The contract being internalized (provenance + rootless region role).
        domain: The literal domain (provenance only), or None.
        fields: ``(field_name, primary_selector, root_selector, yosoi_type)`` per content
            field — ``primary_selector`` is the stored ``{type, value}`` dict.
        source: Provenance trust tier for these selectors (see ``SOURCE_TRUST``). Gate-accepted
            discovery passes ``'verified'``; default ``'llm'``.

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
                source=source,
                scheme=ATOM_SCHEME_VERSION,
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
        # Trust is monotonic on merge: keep the most-truthy source seen (a later 'verified'
        # upgrades an earlier 'fingerprint'; a 'fingerprint' never downgrades a 'verified').
        best_source = max(existing.source, atom.source, key=lambda s: SOURCE_TRUST.get(s, 0))
        merged = existing.model_copy(
            update={
                'domains_seen': sorted(set(existing.domains_seen) | set(atom.domains_seen)),
                'contracts': sorted(set(existing.contracts) | set(atom.contracts)),
                'source': best_source,
            }
        )
        self._atoms[atom.key] = merged
        self._flush()
        return False

    def upsert_all(self, atoms: list[FieldAtom]) -> int:
        """Upsert many atoms; return how many were NEW (minted, not merged)."""
        return sum(1 for a in atoms if self.upsert(a))

    def list_stale_by_scheme(self, current: str = ATOM_SCHEME_VERSION) -> list[str]:
        """Return the keys of atoms minted under an OLDER identity scheme (P4 migration).

        After an atom-scheme bump (e.g. the P5 fingerprint change), atoms whose ``schema``
        differs from ``current`` are reported STALE so the caller can lazily re-mint them
        under the new scheme — non-destructive: the old atoms remain until overwritten, and
        a stale atom simply isn't trusted for reuse. Mirrors the lesson store's
        ``list_stale_by_scheme``.
        """
        return [atom.key for atom in self._atoms.values() if atom.scheme != current]

    def get(self, key: str) -> FieldAtom | None:
        """Return the atom with this content-addressed key, or None."""
        return self._atoms.get(key)

    def all(self) -> list[FieldAtom]:
        """Return every stored atom."""
        return list(self._atoms.values())

    def __len__(self) -> int:
        """Number of distinct atoms held."""
        return len(self._atoms)
