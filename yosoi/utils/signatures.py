"""Stable hashing for field/contract metadata used as bus lookup keys."""

from __future__ import annotations

import hashlib
import json
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from yosoi.models.contract import Contract


def _normalize(s: str | None) -> str:
    """Lowercase and collapse whitespace for stable hashing."""
    return ' '.join(s.lower().split()) if s else ''


def field_signature(
    field_name: str,
    description: str,
    hint: str | None,
    yosoi_type: str | None,
) -> str:
    """Return a stable 16-hex-char hash for a field's discovery identity.

    Normalises all string inputs before hashing so trivial formatting
    differences (extra spaces, mixed case) do not cause cache misses.

    Args:
        field_name: Field name as it appears in the contract.
        description: Field description from the contract.
        hint: Optional yosoi_hint from the contract field.
        yosoi_type: Optional semantic type string (e.g. ``'price'``).

    Returns:
        16-character hex digest.

    """
    payload = json.dumps(
        {
            'name': _normalize(field_name),
            'desc': _normalize(description),
            'hint': _normalize(hint),
            'type': _normalize(yosoi_type),
        },
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def contract_signature(contract: type[Contract]) -> str:
    """Return a stable 16-hex-char hash of a contract's full field set.

    Computed as SHA-256 over the sorted list of individual field signatures,
    so any change in field metadata produces a distinct contract signature.

    Args:
        contract: Contract subclass to hash.

    Returns:
        16-character hex digest.

    """
    field_descs = contract.field_descriptions()
    hints = contract.field_hints()

    field_sigs = sorted(
        field_signature(
            field_name=name,
            description=desc,
            hint=hints.get(name),
            yosoi_type=_get_yosoi_type(contract, name),
        )
        for name, desc in field_descs.items()
    )
    payload = json.dumps(field_sigs)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


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
