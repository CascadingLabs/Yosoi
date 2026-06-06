"""Stable hashing for field/contract metadata used as bus lookup keys."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.models.contract import Contract


# Bump whenever the bytes that feed ``contract_signature`` change shape so a
# load-miss caused by the scheme change is distinguishable from a genuine new
# contract. ``v1`` hashed field metadata only; ``v2`` folded in the class name +
# docstring so two same-shape contracts differing only by NL intent (AdLink vs
# OrganicLink) no longer collide. ``v3`` DROPS per-field ``description`` from the
# contract identity — field prose is advisory and stochastic (it has "no teeth";
# the discrimination gate, not the description, separates regions), and rewording a
# field's description must not bust the selector cache. This aligns
# ``contract_signature`` with ``ContractSpec.fingerprint`` (cas-96), which already
# excludes per-field description. Contract ``name`` + ``doc`` are KEPT — they remain
# the deliberate intent disambiguator (AdLink vs OrganicLink split on the docstring).
# The prefix rides on the returned signature, so every cache key (persistence, lesson
# storage_key, discovery-strategy) rotates together — stale v2 lessons surface via
# ``LessonKey.sig_version`` (→ lazy re-discovery), never a silent collision.
SIGNATURE_SCHEME_VERSION = 'v3'


def _normalize(s: str | None) -> str:
    """Lowercase and collapse whitespace for stable hashing."""
    return ' '.join(s.lower().split()) if s else ''


def field_signature(
    field_name: str,
    description: str,
    yosoi_type: str | None,
) -> str:
    """Return a stable 16-hex-char hash for a field's discovery identity.

    Normalises all string inputs before hashing so trivial formatting
    differences (extra spaces, mixed case) do not cause cache misses.

    Args:
        field_name: Field name as it appears in the contract.
        description: Field description from the contract.
        yosoi_type: Optional semantic type string (e.g. ``'price'``).

    Returns:
        16-character hex digest.

    """
    payload = json.dumps(
        {
            'name': _normalize(field_name),
            'desc': _normalize(description),
            'type': _normalize(yosoi_type),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def contract_signature(contract: type[Contract]) -> str:
    """Return a stable, scheme-versioned hash of a contract's discovery identity.

    The identity is the class name, the normalized class docstring, and the sorted set of
    per-field ``(name, yosoi_type)`` tokens. Per-field ``description`` is DELIBERATELY EXCLUDED
    (``v3``): field prose is advisory/stochastic and has no teeth — rewording a description must
    not bust the selector cache, and regions are separated by the discrimination gate, not prose.
    This mirrors :meth:`ContractSpec.fingerprint`.

    The class docstring + name remain the load-bearing intent disambiguator: two contracts with
    identical fields but different NL intent (``AdLink`` vs ``OrganicLink``, both ``{url, title}``)
    MUST get distinct cache slots, and they still do — they differ by docstring (and/or name).

    The returned digest is prefixed with :data:`SIGNATURE_SCHEME_VERSION` so a cache load-miss
    caused by a scheme change is observable (→ lazy re-discovery) rather than a silent collision.

    Args:
        contract: Contract subclass to hash.

    Returns:
        ``"<scheme>:<16-hex-char digest>"`` (e.g. ``"v3:4e9f8fa8a1b2c3d4"``).

    """
    # Field identity = (name, yosoi_type) only — description excluded by design (see docstring).
    field_ids = sorted(
        json.dumps(
            {'name': _normalize(name), 'type': _normalize(_get_yosoi_type(contract, name))},
            sort_keys=True,
        )
        for name in contract.field_descriptions()
    )
    payload = json.dumps(
        {
            'name': _normalize(contract.__name__),
            'doc': _normalize(contract.__doc__),
            'fields': field_ids,
        },
        sort_keys=True,
    )
    digest = hashlib.sha256(payload.encode()).hexdigest()[:16]
    return f'{SIGNATURE_SCHEME_VERSION}:{digest}'


def signature_scheme_of(contract_sig: str) -> str:
    """Extract the scheme-version prefix from a contract signature.

    Returns the substring before the first ``':'`` (e.g. ``'v2'``). A bare,
    un-prefixed legacy signature (no ``':'``) is reported as ``'v1'``.
    """
    scheme, sep, _ = contract_sig.partition(':')
    return scheme if sep else 'v1'


def _get_yosoi_type(contract: type[Contract], field_name: str) -> str | None:
    """Extract yosoi_type for a (potentially nested) field name."""
    fi = contract.model_fields.get(field_name)
    if fi is not None:
        extra = fi.json_schema_extra
        if isinstance(extra, dict):
            val = extra.get('yosoi_type')
            return str(val) if val is not None else None
        return None

    # Try nested: field_name may be "{parent}_{child}"
    for parent_name, parent_fi in contract.model_fields.items():
        ann = parent_fi.annotation
        from yosoi.models.contract import Contract as _Contract

        if isinstance(ann, type) and issubclass(ann, _Contract):
            prefix = f'{parent_name}_'
            if field_name.startswith(prefix):
                child_name = field_name[len(prefix) :]
                child_fi = ann.model_fields.get(child_name)
                if child_fi is not None:
                    child_extra = child_fi.json_schema_extra
                    if isinstance(child_extra, dict):
                        val = child_extra.get('yosoi_type')
                        return str(val) if val is not None else None
    return None
