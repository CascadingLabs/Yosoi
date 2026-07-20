"""Persistent fingerprint cache and audit-trail models.

These models are intentionally storage-oriented. They do not decide whether a
selector may be served; they preserve the evidence later classifier/reuse layers
need to answer "what was this page/field similar to, and why?" without retaining
raw HTML.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from yosoi.core.fetcher import FetcherType
from yosoi.generalization.fingerprint import FingerprintLayerSimilarity, PageFingerprint, PageSimilarity
from yosoi.models.extraction import EvidenceSource, ExtractorSpec, RowFingerprint
from yosoi.models.selectors import SelectorEntry

FINGERPRINT_RECORD_VERSION = 'fp1'
Decision = Literal['reuse', 'quarantine', 'discover']
FetchTier: TypeAlias = FetcherType | Literal['unknown']
RootKind = Literal['dom', 'accessibility', 'action', 'visual', 'rootless']


def utc_now_iso() -> str:
    """Return an ISO-8601 UTC timestamp for cache/audit records."""
    return datetime.now(timezone.utc).isoformat()


class FingerprintPageRecord(BaseModel):
    """A cached fingerprint for one fetched page, without raw HTML."""

    model_config = ConfigDict(frozen=True)

    version: str = FINGERPRINT_RECORD_VERSION
    url: str = Field(min_length=1)
    fingerprint: PageFingerprint
    fetched_at: str = Field(default_factory=utc_now_iso)
    fetch_tier: FetchTier = 'unknown'
    label: str | None = None
    contract_name: str | None = None
    contract_fingerprint: str | None = None


class FingerprintReferenceRecord(BaseModel):
    """A named page-level reference environment that future pages can be classified against."""

    model_config = ConfigDict(frozen=True)

    version: str = FINGERPRINT_RECORD_VERSION
    reference_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    url: str = Field(min_length=1)
    fingerprint: PageFingerprint
    created_at: str = Field(default_factory=utc_now_iso)
    fetch_tier: FetchTier = 'unknown'
    contract_name: str | None = None
    contract_fingerprint: str | None = None
    notes: str | None = None


class RootScopeRecord(BaseModel):
    """A field's parent scope, with explicit selector family.

    Today extraction scopes only DOM roots (CSS/XPath), but the public selector model
    can also point at accessibility/action/visual targets. Keeping the root as a
    recursive concept prevents audit records from flattening every root into a CSS
    string and leaves room for AX/action scoped replay.
    """

    model_config = ConfigDict(frozen=True)

    kind: RootKind
    signature: str = Field(min_length=1)
    selector: SelectorEntry | None = None


class ExtractorStrategyRecord(BaseModel):
    """Reusable extractor strategy evidence; never an extracted value."""

    model_config = ConfigDict(frozen=True)

    scheme: str = 'yef1'
    extractor: ExtractorSpec
    output_annotation: str = Field(min_length=1)
    row: RowFingerprint
    evidence_sources: tuple[EvidenceSource, ...] = ()
    operations: tuple[str, ...] = ()
    opaque: bool = False


class FingerprintFieldReferenceRecord(BaseModel):
    """A field/root-scoped selector or extractor strategy reference."""

    model_config = ConfigDict(frozen=True)

    version: str = FINGERPRINT_RECORD_VERSION
    reference_id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    url: str = Field(min_length=1)
    route_template: str = Field(min_length=1)
    fingerprint: PageFingerprint
    created_at: str = Field(default_factory=utc_now_iso)
    fetch_tier: FetchTier = 'unknown'
    contract_name: str | None = None
    contract_fingerprint: str | None = None
    field_name: str = Field(min_length=1)
    yosoi_type: str | None = None
    root: RootScopeRecord
    selector: SelectorEntry | None = None
    extractor: ExtractorStrategyRecord | None = None
    notes: str | None = None

    @model_validator(mode='after')
    def _exactly_one_strategy(self) -> FingerprintFieldReferenceRecord:
        if (self.selector is None) == (self.extractor is None):
            raise ValueError('field references require exactly one strategy kind: selector or extractor')
        return self


class ScoreNode(BaseModel):
    """A named similarity node in the audit tree."""

    model_config = ConfigDict(frozen=True)

    score: float | None = Field(default=None, ge=0.0, le=1.0)
    passed: bool | None = None
    evidence: dict[str, str | int | float | bool | None] = Field(default_factory=dict)


class PageLayerSimilarity(BaseModel):
    """Recursive page-fingerprint layer evidence."""

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    same_shape: bool
    skeleton: ScoreNode
    semantic: ScoreNode
    identity: ScoreNode
    accessibility: ScoreNode
    network: ScoreNode
    endpoint: ScoreNode

    @classmethod
    def from_similarity(cls, similarity: PageSimilarity) -> PageLayerSimilarity:
        """Build nested page-layer evidence from the existing page similarity model."""
        return cls(
            score=similarity.score,
            same_shape=similarity.same_shape,
            skeleton=_score_node(similarity.skeleton),
            semantic=_score_node(similarity.semantic),
            identity=_score_node(similarity.identity),
            accessibility=_score_node(similarity.ax),
            network=_score_node(similarity.network),
            endpoint=_score_node(similarity.endpoint),
        )


class FieldScopeSimilarity(BaseModel):
    """Field/root/route scope evidence layered beneath page similarity."""

    model_config = ConfigDict(frozen=True)

    route: ScoreNode
    field_name: ScoreNode
    field_type: ScoreNode
    root: ScoreNode
    contract: ScoreNode
    same_field_scope: bool


class FieldGeneralizationSimilarity(BaseModel):
    """Auditable candidate-field -> reference-field similarity breakdown.

    The structure is intentionally recursive: page layers own skeleton/semantic/
    accessibility/network concepts, while field scope owns route/field/root/contract.
    Flattening for legacy JSONL happens only at the audit-record boundary.
    """

    model_config = ConfigDict(frozen=True)

    score: float = Field(ge=0.0, le=1.0)
    page: PageLayerSimilarity
    field_scope: FieldScopeSimilarity

    @classmethod
    def from_page_similarity(
        cls,
        *,
        page: PageSimilarity,
        route: float,
        field_name: float,
        field_type: float,
        root: float,
        contract: float,
    ) -> FieldGeneralizationSimilarity:
        """Build a nested field/root score from page similarity plus scope evidence."""
        same_field_scope = page.same_shape and route >= 1.0 and field_type >= 1.0 and root >= 1.0
        score = (page.score * 2.0 + route + field_type + root + field_name + contract) / 7.0
        return cls(
            score=max(0.0, min(1.0, score)),
            page=PageLayerSimilarity.from_similarity(page),
            field_scope=FieldScopeSimilarity(
                route=ScoreNode(score=route),
                field_name=ScoreNode(score=field_name),
                field_type=ScoreNode(score=field_type),
                root=ScoreNode(score=root),
                contract=ScoreNode(score=contract),
                same_field_scope=same_field_scope,
            ),
        )


def _score_node(layer: FingerprintLayerSimilarity | None) -> ScoreNode:
    if layer is None:
        return ScoreNode()
    return ScoreNode(
        score=layer.jaccard,
        evidence={
            'weighted': layer.weighted,
            'containment': layer.containment,
        },
    )


def _layer_score(layer: FingerprintLayerSimilarity | None) -> float | None:
    return None if layer is None else layer.jaccard


def _layer_weighted(layer: FingerprintLayerSimilarity | None) -> float | None:
    return None if layer is None else layer.weighted


class FingerprintClassificationRecord(BaseModel):
    """Append-only audit record for one candidate-vs-reference classification."""

    model_config = ConfigDict(frozen=True)

    version: str = FINGERPRINT_RECORD_VERSION
    run_id: str = Field(min_length=1)
    candidate_url: str = Field(min_length=1)
    candidate_label: str | None = None
    classified_at: str = Field(default_factory=utc_now_iso)
    best_reference_id: str | None = None
    best_reference_label: str | None = None
    score: float = Field(ge=0.0, le=1.0)
    same_shape: bool
    decision: Decision
    layer_scores: dict[str, float | None] = Field(default_factory=dict)
    evidence: tuple[str, ...] = ()

    @classmethod
    def from_similarity(
        cls,
        *,
        run_id: str,
        candidate_url: str,
        similarity: PageSimilarity,
        decision: Decision,
        candidate_label: str | None = None,
        best_reference_id: str | None = None,
        best_reference_label: str | None = None,
        evidence: tuple[str, ...] = (),
    ) -> FingerprintClassificationRecord:
        """Build an audit record from a computed page-fingerprint similarity."""
        return cls(
            run_id=run_id,
            candidate_url=candidate_url,
            candidate_label=candidate_label,
            best_reference_id=best_reference_id,
            best_reference_label=best_reference_label,
            score=similarity.score,
            same_shape=similarity.same_shape,
            decision=decision,
            layer_scores={
                'skeleton': _layer_score(similarity.skeleton),
                'semantic': _layer_score(similarity.semantic),
                'identity': _layer_score(similarity.identity),
                'accessibility': _layer_score(similarity.ax),
                'network': _layer_score(similarity.network),
                'endpoint': _layer_score(similarity.endpoint),
                'skeleton_weighted': _layer_weighted(similarity.skeleton),
                'semantic_weighted': _layer_weighted(similarity.semantic),
                'identity_weighted': _layer_weighted(similarity.identity),
                'accessibility_weighted': _layer_weighted(similarity.ax),
                'network_weighted': _layer_weighted(similarity.network),
                'endpoint_weighted': _layer_weighted(similarity.endpoint),
            },
            evidence=evidence,
        )

    @classmethod
    def from_field_similarity(
        cls,
        *,
        run_id: str,
        candidate_url: str,
        similarity: FieldGeneralizationSimilarity,
        decision: Decision,
        candidate_label: str | None = None,
        best_reference_id: str | None = None,
        best_reference_label: str | None = None,
        evidence: tuple[str, ...] = (),
    ) -> FingerprintClassificationRecord:
        """Build an audit record from expanded field/root generalization evidence."""
        return cls(
            run_id=run_id,
            candidate_url=candidate_url,
            candidate_label=candidate_label,
            best_reference_id=best_reference_id,
            best_reference_label=best_reference_label,
            score=similarity.score,
            same_shape=similarity.field_scope.same_field_scope,
            decision=decision,
            layer_scores={
                'page': similarity.page.score,
                'skeleton': similarity.page.skeleton.score,
                'semantic': similarity.page.semantic.score,
                'identity': similarity.page.identity.score,
                'accessibility': similarity.page.accessibility.score,
                'network': similarity.page.network.score,
                'endpoint': similarity.page.endpoint.score,
                'route': similarity.field_scope.route.score,
                'field_name': similarity.field_scope.field_name.score,
                'field_type': similarity.field_scope.field_type.score,
                'root': similarity.field_scope.root.score,
                'contract': similarity.field_scope.contract.score,
            },
            evidence=evidence,
        )


__all__ = [
    'FINGERPRINT_RECORD_VERSION',
    'Decision',
    'ExtractorStrategyRecord',
    'FetchTier',
    'FieldGeneralizationSimilarity',
    'FieldScopeSimilarity',
    'FingerprintClassificationRecord',
    'FingerprintFieldReferenceRecord',
    'FingerprintPageRecord',
    'FingerprintReferenceRecord',
    'PageLayerSimilarity',
    'RootKind',
    'RootScopeRecord',
    'ScoreNode',
    'utc_now_iso',
]
