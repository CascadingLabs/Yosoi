"""Expanded fingerprint generalization helpers.

Page fingerprints answer "does this candidate resemble that reference page?". For
selector reuse we also need the smaller scope: route template, field type/name,
and root region. This module composes those signals into an auditable field/root
score without changing the selector-serving path.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from yosoi.fingerprints.models import (
    FieldGeneralizationSimilarity,
    FingerprintFieldReferenceRecord,
    RootKind,
    RootScopeRecord,
)
from yosoi.generalization.fingerprint import PageFingerprint
from yosoi.models.selectors import SelectorEntry, coerce_selector_entry

_ID_SEG_RE = re.compile(r'^(?:[0-9]+|[0-9a-f]{8,}|[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12})$', re.IGNORECASE)
_DOM_ROOT_TYPES = {'css', 'xpath'}
_AX_ROOT_TYPES = {'role'}
_VISUAL_ROOT_TYPES = {'visual'}
_ACTION_ROOT_TYPES = {'attr', 'global_id', 'jsonld', 'regex'}


def route_template(url: str) -> str:
    """Return a content-insensitive route template for a URL.

    Query/fragment are intentionally ignored. Numeric, uuid-like, hex-like, and
    digit-dominant path segments collapse to ``{id}``, so item/detail routes do
    not fragment by content identity.
    """
    parts = urlsplit(url)
    path = parts.path or '/'
    segments = [_normalize_route_segment(seg) for seg in path.split('/') if seg]
    template = '/' + '/'.join(segments)
    if path.endswith('/') and template != '/':
        template += '/'
    host = parts.netloc.lower()
    return f'{host}{template}' if host else template


def root_scope(
    root: SelectorEntry | dict[str, object] | str | None, *, contract_name: str | None = None
) -> RootScopeRecord:
    """Return a typed root-scope record from any selector-ish root value."""
    entry = coerce_selector_entry(root)
    if entry is None:
        return RootScopeRecord(kind='rootless', signature=f'name:{contract_name}' if contract_name else 'rootless')
    kind: RootKind
    if entry.type in _DOM_ROOT_TYPES:
        kind = 'dom'
    elif entry.type in _AX_ROOT_TYPES:
        kind = 'accessibility'
    elif entry.type in _VISUAL_ROOT_TYPES:
        kind = 'visual'
    elif entry.type in _ACTION_ROOT_TYPES:
        kind = 'action'
    else:
        kind = 'action'
    return RootScopeRecord(kind=kind, signature=_selector_signature(entry), selector=entry)


def root_signature(root: SelectorEntry | dict[str, object] | str | None, *, contract_name: str | None = None) -> str:
    """Return the durable root-region signature used for field-scope comparison."""
    return root_scope(root, contract_name=contract_name).signature


def compare_field_reference(
    *,
    candidate_fingerprint: PageFingerprint,
    candidate_url: str,
    candidate_field_name: str,
    candidate_yosoi_type: str | None,
    candidate_root: SelectorEntry | dict[str, object] | str | None,
    reference: FingerprintFieldReferenceRecord,
    candidate_contract_name: str | None = None,
    candidate_contract_fingerprint: str | None = None,
) -> FieldGeneralizationSimilarity:
    """Compare one candidate field/root against one stored field reference.

    The result is explicit enough for matrix printing and audit JSONL: page layers,
    route match, field type/name, root match, and contract match are all preserved.
    """
    page = candidate_fingerprint.similarity(reference.fingerprint)
    candidate_route = route_template(candidate_url)
    scope = root_scope(candidate_root, contract_name=candidate_contract_name)
    route = _bool_score(candidate_route == reference.route_template)
    field_name = _bool_score(candidate_field_name == reference.field_name)
    field_type = _bool_score((candidate_yosoi_type or '') == (reference.yosoi_type or ''))
    root = _bool_score(scope.kind == reference.root.kind and scope.signature == reference.root.signature)
    contract = _contract_score(candidate_contract_name, candidate_contract_fingerprint, reference)
    return FieldGeneralizationSimilarity.from_page_similarity(
        page=page,
        route=route,
        field_name=field_name,
        field_type=field_type,
        root=root,
        contract=contract,
    )


def _selector_signature(entry: SelectorEntry) -> str:
    parts = [entry.type, ' '.join(entry.value.split())]
    if entry.name is not None:
        parts.append(entry.name)
    if entry.nth is not None:
        parts.append(str(entry.nth))
    if entry.regex is not None:
        parts.append(entry.regex)
    if entry.x is not None or entry.y is not None:
        parts.extend((str(entry.x), str(entry.y)))
    return '\x1f'.join(parts)


def _normalize_route_segment(segment: str) -> str:
    if _ID_SEG_RE.match(segment):
        return '{id}'
    digits = sum(ch.isdigit() for ch in segment)
    if len(segment) >= 4 and digits >= 4 and digits * 5 >= len(segment) * 2:
        return '{id}'
    return segment.lower()


def _bool_score(value: bool) -> float:
    return 1.0 if value else 0.0


def _contract_score(
    contract_name: str | None,
    contract_fingerprint: str | None,
    reference: FingerprintFieldReferenceRecord,
) -> float:
    if contract_fingerprint and reference.contract_fingerprint:
        return _bool_score(contract_fingerprint == reference.contract_fingerprint)
    if contract_name and reference.contract_name:
        return _bool_score(contract_name == reference.contract_name)
    return 0.0


__all__ = ['compare_field_reference', 'root_scope', 'root_signature', 'route_template']
