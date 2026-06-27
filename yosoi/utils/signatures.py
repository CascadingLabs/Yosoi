"""Stable hashing for field/contract metadata used as bus lookup keys."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.models.contract import Contract


# Alpha reset: this is the first supported signature scheme for the normalized
# field-entity runtime. We do not carry pre-alpha cache compatibility forward.
SIGNATURE_SCHEME_VERSION = 'v1'


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

    The identity is delegated to :class:`yosoi.models.spec.ContractSpec`: contract
    name, contract docstring, root/config, and field entities. Field descriptions
    are intentionally included via each field's fingerprint.
    """
    return f'{SIGNATURE_SCHEME_VERSION}:{contract.to_spec().fingerprint}'


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
