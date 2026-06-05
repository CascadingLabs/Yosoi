"""Stable hashing for field/contract metadata used as bus lookup keys."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.models.contract import Contract


# Bump whenever the bytes that feed ``contract_signature`` change shape so a
# load-miss caused by the scheme change is distinguishable from a genuine new
# contract. ``v1`` hashed field metadata only; ``v2`` folds in the class name +
# docstring so two same-shape contracts differing only by NL intent (AdLink vs
# OrganicLink) no longer collide. The prefix rides on the returned signature, so
# every cache key (persistence, lesson storage_key, discovery-strategy) rotates
# together — stale lessons surface via ``LessonKey.sig_version`` rather than a
# silent re-discovery.
SIGNATURE_SCHEME_VERSION = 'v2'


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

    The identity is the sorted list of per-field signatures **plus** the class
    name and normalized docstring. The class docstring is a load-bearing
    disambiguator: two contracts with identical fields but different NL intent
    (``AdLink`` vs ``OrganicLink``, both ``{url, title}``) MUST get distinct cache
    slots, not clobber each other (see nimbal ``serp_contracts.py`` lesson). The
    class name is folded in too so two identically-documented-but-differently-named
    contracts also split — matching the ``_CONTRACT_REGISTRY`` ``__name__`` key.

    The returned digest is prefixed with :data:`SIGNATURE_SCHEME_VERSION` so a
    cache load-miss caused by a scheme change is observable rather than silent.

    Args:
        contract: Contract subclass to hash.

    Returns:
        ``"<scheme>:<16-hex-char digest>"`` (e.g. ``"v2:4e9f8fa8a1b2c3d4"``).

    """
    field_descs = contract.field_descriptions()

    field_sigs = sorted(
        field_signature(
            field_name=name,
            description=desc,
            yosoi_type=_get_yosoi_type(contract, name),
        )
        for name, desc in field_descs.items()
    )
    payload = json.dumps(
        {
            'name': _normalize(contract.__name__),
            'doc': _normalize(contract.__doc__),
            'fields': field_sigs,
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
