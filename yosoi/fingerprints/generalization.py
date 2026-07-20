"""Expanded fingerprint generalization helpers.

Page fingerprints answer "does this candidate resemble that reference page?". For
selector reuse we also need the smaller scope: route template, field type/name,
and root region. This module composes those signals into an auditable field/root
score without changing the selector-serving path.
"""

from __future__ import annotations

import re
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from yosoi.fingerprints.models import (
    ExtractorStrategyRecord,
    FieldGeneralizationSimilarity,
    FingerprintFieldReferenceRecord,
    RootKind,
    RootScopeRecord,
)
from yosoi.generalization.fingerprint import PageFingerprint
from yosoi.models.extraction import ExtractorFingerprint, RowFingerprint
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


class ExtractorGeneralizationSimilarity(BaseModel):
    """Fail-closed compatibility evidence for one extractor strategy proposal."""

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    compatible: bool
    page_score: float = Field(ge=0.0, le=1.0)
    route_match: bool
    root_match: bool
    output_match: bool
    resolver_match: bool
    operation_match: bool
    row_score: float = Field(ge=0.0, le=1.0)


def compare_extractor_reference(
    *,
    candidate_fingerprint: PageFingerprint,
    candidate_url: str,
    candidate_root: SelectorEntry | dict[str, object] | str | None,
    candidate_output_annotation: str,
    candidate_resolver_id: str,
    candidate_resolver_version: str,
    candidate_operations: tuple[str, ...],
    candidate_row: RowFingerprint,
    reference: FingerprintFieldReferenceRecord,
    candidate_contract_name: str | None = None,
) -> ExtractorGeneralizationSimilarity:
    """Compare a current row with a stored extractor strategy, never a stored value."""
    strategy = reference.extractor
    if strategy is None:
        raise ValueError('compare_extractor_reference requires an extractor strategy reference')
    page = candidate_fingerprint.similarity(reference.fingerprint)
    route_match = route_template(candidate_url) == reference.route_template
    scope = root_scope(candidate_root, contract_name=candidate_contract_name)
    root_match = scope.kind == reference.root.kind and scope.signature == reference.root.signature
    output_match = candidate_output_annotation == strategy.output_annotation
    resolver_match = (
        candidate_resolver_id == strategy.extractor.resolver_id
        and candidate_resolver_version == strategy.extractor.version
    )
    operation_match = candidate_operations == strategy.operations
    row_score = candidate_row.similarity(strategy.row)
    compatible = (
        page.same_shape
        and route_match
        and root_match
        and output_match
        and resolver_match
        and row_score == 1.0
        and operation_match
    )
    operation_score = 0.5 if strategy.opaque and operation_match else float(operation_match)
    parts = [
        page.score,
        float(route_match),
        float(root_match),
        float(output_match),
        float(resolver_match),
        operation_score,
        row_score,
    ]
    return ExtractorGeneralizationSimilarity(
        score=sum(parts) / len(parts),
        compatible=compatible,
        page_score=page.score,
        route_match=route_match,
        root_match=root_match,
        output_match=output_match,
        resolver_match=resolver_match,
        operation_match=operation_match,
        row_score=row_score,
    )


def select_extractor_reference(
    references: list[FingerprintFieldReferenceRecord],
    *,
    candidate_fingerprint: PageFingerprint,
    candidate_url: str,
    candidate_root: SelectorEntry | dict[str, object] | str | None,
    candidate_output_annotation: str,
    candidate_resolver_id: str,
    candidate_resolver_version: str,
    candidate_operations: tuple[str, ...],
    candidate_row: RowFingerprint,
    candidate_contract_name: str | None = None,
) -> FingerprintFieldReferenceRecord | None:
    """Select one compatible strategy or abstain when candidates conflict."""
    compatible = [
        reference
        for reference in references
        if reference.extractor is not None
        and compare_extractor_reference(
            candidate_fingerprint=candidate_fingerprint,
            candidate_url=candidate_url,
            candidate_root=candidate_root,
            candidate_output_annotation=candidate_output_annotation,
            candidate_resolver_id=candidate_resolver_id,
            candidate_resolver_version=candidate_resolver_version,
            candidate_operations=candidate_operations,
            candidate_row=candidate_row,
            reference=reference,
            candidate_contract_name=candidate_contract_name,
        ).compatible
    ]
    if not compatible:
        return None
    strategy_ids = {
        (reference.extractor.extractor.fingerprint, reference.extractor.operations)
        for reference in compatible
        if reference.extractor is not None
    }
    return compatible[0] if len(strategy_ids) == 1 else None


def extractor_strategy_from_fingerprint(
    fingerprint: ExtractorFingerprint,
    *,
    spec: object,
    output_annotation: str,
) -> ExtractorStrategyRecord:
    """Build a reusable strategy payload from one successful runtime observation."""
    from yosoi.models.extraction import ExtractorSpec

    if not isinstance(spec, ExtractorSpec):
        raise TypeError('spec must be an ExtractorSpec')
    if fingerprint.validation_result != 'valid':
        raise ValueError('only validated extractor executions can become strategy references')
    return ExtractorStrategyRecord(
        extractor=spec,
        output_annotation=output_annotation,
        row=fingerprint.row,
        evidence_sources=fingerprint.evidence_sources,
        operations=fingerprint.operations,
        opaque=fingerprint.opaque,
    )


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
    if reference.selector is None:
        raise ValueError('compare_field_reference requires a selector strategy reference')
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


__all__ = [
    'ExtractorGeneralizationSimilarity',
    'compare_extractor_reference',
    'compare_field_reference',
    'extractor_strategy_from_fingerprint',
    'root_scope',
    'root_signature',
    'route_template',
    'select_extractor_reference',
]
