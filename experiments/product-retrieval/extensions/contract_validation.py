"""Bind ranked rendered-DOM candidates to public Yosoi Contract validation."""

from __future__ import annotations

import hashlib
import importlib
import importlib.metadata
import json
from collections.abc import Mapping
from functools import lru_cache
from pathlib import Path
from typing import Any

from yosoi.contracts import ContractSchema, FieldSchema, RuntimeContract
from yosoi.documents import Document
from yosoi.outcomes import (
    Attribute,
    AttributeValue,
    Complete,
    DomCoordinate,
    Finding,
    Indeterminate,
    LocateResult,
    Matched,
    NoMatch,
    Partial,
    RegionLineage,
    RenderedDomLocation,
    TextValue,
    Unknown,
)
from yosoi.scalars import (
    ContractId,
    DomNodeId,
    FieldId,
    OutputId,
    RegionId,
)

PRODUCT_SCHEMA_ID = "product"
PRODUCT_FIELDS = ("id", "name", "price", "color", "material", "stock")
DEFAULT_REQUIRED_FIELDS = PRODUCT_FIELDS
REQUIRED_FIELDS = PRODUCT_FIELDS
_IGNORED_TEXT_TAGS = {"script", "style", "noscript", "template"}
_MAX_SOURCE_NODES = 20_000
_MAX_SOURCE_DEPTH = 256


def _normalize(value: str) -> str:
    """Match the corpus's representation-neutral whitespace normalization."""
    return " ".join(value.split())


def _document_index(
    case_document: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str], dict[str, str]]:
    raw_nodes = case_document.get("nodes")
    root_value = case_document.get("root")
    if not isinstance(raw_nodes, list) or not raw_nodes:
        raise ValueError("rendered DOM has no node list")
    nodes: dict[str, Mapping[str, Any]] = {}
    for node in raw_nodes:
        if not isinstance(node, Mapping) or "id" not in node:
            raise ValueError("rendered DOM contains an invalid node")
        node_id = str(node["id"])
        if node_id in nodes:
            raise ValueError("rendered DOM contains duplicate stringified node IDs")
        nodes[node_id] = node
    if len(nodes) > _MAX_SOURCE_NODES:
        raise ValueError("rendered DOM exceeds the validation node budget")

    root_id = str(root_value)
    if root_id not in nodes:
        raise ValueError("rendered DOM root is missing")
    children_by_id: dict[str, list[str]] = {}
    for node_id, node in nodes.items():
        raw_children = node.get("children", [])
        if not isinstance(raw_children, list):
            raise ValueError("rendered DOM child list is invalid")
        children: list[str] = []
        for raw_child in raw_children:
            child_id = str(raw_child)
            if child_id not in nodes:
                raise ValueError("rendered DOM references an absent child")
            children.append(child_id)
        children_by_id[node_id] = children

    parents: dict[str, str] = {}
    seen = {root_id}
    traversal: list[tuple[str, int, bool]] = [(root_id, 0, False)]
    order: list[str] = []
    excluded: dict[str, bool] = {}
    while traversal:
        node_id, depth, hidden_parent = traversal.pop()
        if depth > _MAX_SOURCE_DEPTH:
            raise ValueError("rendered DOM exceeds the validation depth budget")
        if len(order) >= _MAX_SOURCE_NODES:
            raise ValueError("rendered DOM exceeds the validation traversal budget")
        order.append(node_id)
        node = nodes[node_id]
        tag = str(node.get("tag_name", "")).lower()
        hidden = hidden_parent or (
            node.get("kind") == "element" and tag in _IGNORED_TEXT_TAGS
        )
        excluded[node_id] = hidden
        for child_id in reversed(children_by_id[node_id]):
            if child_id in seen:
                raise ValueError("rendered DOM contains a cycle or shared child")
            seen.add(child_id)
            parents[child_id] = node_id
            traversal.append((child_id, depth + 1, hidden))
    if len(order) != len(nodes):
        raise ValueError("rendered DOM contains unreachable nodes")

    text_by_id: dict[str, str] = {}
    for node_id in reversed(order):
        node = nodes[node_id]
        if excluded[node_id]:
            text_by_id[node_id] = ""
        elif node.get("kind") == "text":
            text_by_id[node_id] = _normalize(str(node.get("value", "")))
        else:
            text_by_id[node_id] = _normalize(
                " ".join(text_by_id[child_id] for child_id in children_by_id[node_id])
            )
    return nodes, parents, text_by_id


def _candidate_projection(
    candidate: Mapping[str, Any],
    nodes: Mapping[str, Mapping[str, Any]],
    text_by_id: Mapping[str, str],
) -> tuple[str, str, str]:
    """Resolve one generic text/attribute candidate against the retained snapshot."""
    node_id = str(candidate.get("node_id", ""))
    node = nodes.get(node_id)
    if node is None:
        raise ValueError("candidate node ID is absent from the case document")
    if node.get("kind") != "element":
        raise ValueError("candidate coordinate does not identify an element")

    projection = candidate.get("projection")
    if projection == "text":
        actual = text_by_id[node_id]
    elif (
        isinstance(projection, str)
        and projection.startswith("@")
        and len(projection) > 1
    ):
        attribute_name = projection[1:]
        attributes = node.get("attributes", [])
        if not isinstance(attributes, list):
            raise ValueError("candidate element has an invalid attribute list")
        matches = [
            str(attribute.get("value", ""))
            for attribute in attributes
            if isinstance(attribute, Mapping)
            and attribute.get("name") == attribute_name
        ]
        if len(matches) != 1:
            raise ValueError("candidate attribute projection is absent or ambiguous")
        actual = _normalize(matches[0])
    else:
        raise ValueError("candidate projection is not text or a named attribute")

    candidate_text = candidate.get("text")
    if not isinstance(candidate_text, str):
        raise ValueError("candidate projected text is not a string")
    projected = _normalize(candidate_text)
    if projected != actual:
        raise ValueError("candidate text does not match its source node projection")
    return node_id, str(projection), actual


def _inside_region(node_id: str, root_id: str, parents: Mapping[str, str]) -> bool:
    current: str | None = node_id
    seen: set[str] = set()
    while current is not None:
        if current == root_id:
            return True
        if current in seen:
            return False
        seen.add(current)
        current = parents.get(current)
    return False


def _coverage_state(
    completeness: Mapping[str, Any] | None,
) -> tuple[str, str, int | None]:
    """Return complete/partial/unknown after rejecting omitted or budgeted work."""
    if not isinstance(completeness, Mapping):
        return "unknown", "completeness_not_provided", None

    raw_status = completeness.get("status")
    if raw_status is None and completeness.get("complete") is True:
        raw_status = "complete"
    status = raw_status if isinstance(raw_status, str) else "unknown"
    reason = completeness.get("reason_code")
    reason_code = reason if isinstance(reason, str) and reason else None

    lost_items = completeness.get("lost_items")
    if (
        not isinstance(lost_items, int)
        or isinstance(lost_items, bool)
        or lost_items < 0
    ):
        lost_items = None

    unsafe_flags = (
        "budget_exhausted",
        "truncated",
        "incomplete",
        "candidate_budget_exhausted",
        "scoring_budget_exhausted",
    )
    flagged = any(completeness.get(key) is True for key in unsafe_flags)
    if completeness.get("candidate_generation_complete") is False:
        flagged = True
    if completeness.get("all_candidates_scored") is False:
        flagged = True
    if lost_items not in (None, 0):
        flagged = True

    field_coverage = completeness.get("fields")
    if field_coverage is not None:
        if not isinstance(field_coverage, Mapping):
            flagged = True
        else:
            for field_id in PRODUCT_FIELDS:
                entry = field_coverage.get(field_id)
                if isinstance(entry, Mapping):
                    field_status = entry.get("status")
                    field_lost = entry.get("lost_items")
                    if (
                        field_status not in {"complete", "no_match_complete"}
                        or entry.get("budget_exhausted") is True
                        or entry.get("truncated") is True
                        or (isinstance(field_lost, int) and field_lost > 0)
                    ):
                        flagged = True
                elif entry not in {"complete", "no_match_complete", True}:
                    flagged = True

    if flagged or status in {"partial", "budget_exhausted", "incomplete"}:
        return "partial", reason_code or "selection_incomplete_or_budgeted", lost_items
    if status == "complete":
        return "complete", reason_code or "complete_candidate_scan", lost_items
    return "unknown", reason_code or "selection_completeness_unknown", lost_items


def _tie_counts(
    selected_candidates: Mapping[str, Any],
    completeness: Mapping[str, Any] | None,
) -> dict[str, int]:
    ties: dict[str, int] = {}
    field_status = (
        completeness.get("fields") if isinstance(completeness, Mapping) else None
    )
    global_ties = (
        completeness.get("ranking_ties") if isinstance(completeness, Mapping) else None
    )
    for field_id in PRODUCT_FIELDS:
        count: Any = None
        candidate = selected_candidates.get(field_id)
        if isinstance(candidate, Mapping):
            count = candidate.get("top_tie_count")
        if count is None and isinstance(field_status, Mapping):
            detail = field_status.get(field_id)
            if isinstance(detail, Mapping):
                count = detail.get("top_tie_count")
        if count is None and isinstance(global_ties, Mapping):
            count = global_ties.get(field_id)
        if isinstance(count, bool):
            count = 2 if count else 1
        if not isinstance(count, int) or count < 1:
            count = 1
        if count > 1:
            ties[field_id] = count
    return ties


def _schema(required_fields: tuple[str, ...]) -> tuple[ContractSchema, RuntimeContract]:
    contract_id = ContractId.try_new(PRODUCT_SCHEMA_ID)
    required = set(required_fields)
    schema = ContractSchema(
        id=contract_id,
        description="One predicted product detail record",
        scope="repeated",
        fields=tuple(
            FieldSchema(
                id=FieldId.try_new(field_id),
                description=field_id,
                cardinality=("exactly_one" if field_id in required else "zero_or_one"),
                value_type="string",
            )
            for field_id in PRODUCT_FIELDS
        ),
    )
    return schema, RuntimeContract.new(schema)


def _schema_report(
    schema: ContractSchema, required_fields: tuple[str, ...]
) -> dict[str, Any]:
    required = set(required_fields)
    return {
        "id": str(schema.id),
        "identity": str(schema.identity()),
        "scope": schema.scope,
        "required_fields": list(required_fields),
        "optional_fields": [field for field in PRODUCT_FIELDS if field not in required],
        "fields": [
            {
                "id": str(field.id),
                "cardinality": field.cardinality,
                "value_type": field.value_type,
            }
            for field in schema.fields
        ],
    }


def _native_report(extracted: Any, outcome: Any) -> dict[str, Any]:
    issues: list[dict[str, Any]] = []
    for issue in outcome.issues:
        issues.append(
            {
                "region": (
                    None
                    if issue.candidate.region is None
                    else issue.candidate.region.model_dump(mode="json")
                ),
                "fields": [
                    {
                        "field": str(field.field),
                        "kind": field.kind.model_dump(mode="json"),
                        "evidence_count": len(field.evidence),
                    }
                    for field in issue.fields
                ],
            }
        )
    return {
        "extraction_status": extracted.status,
        "validation_status": outcome.status,
        "records": [record.model_dump(mode="json") for record in outcome.records],
        "issues": issues,
        "extraction_diagnostics": [
            diagnostic.model_dump(mode="json")
            for diagnostic in outcome.extraction_diagnostics
        ],
        "failure": (
            None if outcome.failure is None else outcome.failure.model_dump(mode="json")
        ),
    }


def _validate_selection(
    case_document: dict[str, Any],
    document_id: str,
    predicted_root_id: str | int | None,
    selected_candidates: dict[str, dict[str, Any] | None],
    completeness: dict[str, Any] | None = None,
    required_fields: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Bind selected candidates to a rendered DOM and run native Contract validation.

    Only the supplied DOM, candidate node/projection/text, predicted root, and
    completeness/tie metadata are read. Gold fields and oracle values are never read.
    Source projection equality and root ancestry are checked here because public
    Finding/LocateResult constructors validate coordinate shape and lineage
    references, not coordinate membership against document bytes.

    Completeness must be explicit. Missing, partial, unknown, truncated, or
    budget-exhausted coverage becomes a native Indeterminate outcome rather than a
    fabricated Complete claim. Under an explicit complete scan, a missing selection
    is represented by no finding, allowing native validation to report
    ``missing_required``. ``required_fields`` is an explicit caller-owned schema
    choice; omitted fields become native ``zero_or_one`` fields. Selection or gold
    data never changes schema cardinality.
    """
    if required_fields is None:
        configured_required = DEFAULT_REQUIRED_FIELDS
    elif isinstance(required_fields, (tuple, list)) and all(
        isinstance(field, str) for field in required_fields
    ):
        configured_required = tuple(required_fields)
    else:
        return {
            "status": "invalid_contract_schema",
            "reason_code": "required_fields_must_be_a_string_sequence",
            "contract_schema": None,
            "semantic_truth_verified": False,
            "native": None,
        }
    if (
        len(set(configured_required)) != len(configured_required)
        or not set(configured_required).issubset(PRODUCT_FIELDS)
        or not configured_required
    ):
        return {
            "status": "invalid_contract_schema",
            "reason_code": "required_fields_must_be_unique_product_fields",
            "contract_schema": None,
            "required_fields": list(configured_required),
            "semantic_truth_verified": False,
            "native": None,
        }
    schema, runtime_contract = _schema(configured_required)
    schema_report = _schema_report(schema, configured_required)

    if not isinstance(case_document, dict):
        return {
            "status": "source_binding_rejected",
            "reason_code": "invalid_case_document",
            "contract_schema": schema_report,
            "semantic_truth_verified": False,
            "native": None,
        }
    if not isinstance(selected_candidates, dict):
        return {
            "status": "source_binding_rejected",
            "reason_code": "invalid_selection_mapping",
            "contract_schema": schema_report,
            "semantic_truth_verified": False,
            "native": None,
        }
    unknown_fields = sorted(set(selected_candidates) - set(PRODUCT_FIELDS))
    if unknown_fields:
        return {
            "status": "source_binding_rejected",
            "reason_code": "unknown_selected_fields",
            "unknown_fields": unknown_fields,
            "contract_schema": schema_report,
            "semantic_truth_verified": False,
            "native": None,
        }

    coverage_status, coverage_reason, lost_items = _coverage_state(completeness)
    ties = _tie_counts(selected_candidates, completeness)
    source_bindings: dict[str, dict[str, Any]] = {}
    try:
        epoch_value = case_document.get("document_epoch")
        if (
            not isinstance(epoch_value, int)
            or isinstance(epoch_value, bool)
            or epoch_value < 1
        ):
            raise ValueError("rendered DOM document epoch is invalid")
        document = Document.rendered_dom(
            document_id,
            epoch_value,
            json.dumps(case_document, ensure_ascii=False, separators=(",", ":")),
        )
        nodes, parents, text_by_id = _document_index(case_document)
    except Exception as error:
        return {
            "status": "source_binding_rejected",
            "reason_code": "invalid_rendered_dom",
            "detail_type": type(error).__name__,
            "contract_schema": schema_report,
            "semantic_truth_verified": False,
            "native": None,
        }

    native_document_id = document.id
    epoch = document.profile.epoch
    if epoch is None:
        return {
            "status": "source_binding_rejected",
            "reason_code": "rendered_dom_epoch_missing",
            "contract_schema": schema_report,
            "semantic_truth_verified": False,
            "native": None,
        }

    if predicted_root_id is None:
        root_id = None
        root_coordinate = None
        if any(
            selected_candidates.get(field_id) is not None
            for field_id in REQUIRED_FIELDS
        ):
            return {
                "status": "source_binding_rejected",
                "reason_code": "field_selection_without_predicted_root",
                "contract_schema": schema_report,
                "semantic_truth_verified": False,
                "native": None,
            }
    else:
        root_id = str(predicted_root_id)
        root_node = nodes.get(root_id)
        if root_node is None or root_node.get("kind") != "element":
            return {
                "status": "source_binding_rejected",
                "reason_code": "predicted_root_missing_or_not_element",
                "predicted_root_id": root_id,
                "contract_schema": schema_report,
                "semantic_truth_verified": False,
                "native": None,
            }
        root_coordinate = RenderedDomLocation(
            kind="rendered_dom",
            coordinate=DomCoordinate.new(epoch, DomNodeId.try_new(int(root_id))),
        )

    bound_candidates: dict[str, dict[str, Any]] = {}
    for field_id in PRODUCT_FIELDS:
        candidate = selected_candidates.get(field_id)
        if candidate is None:
            source_bindings[field_id] = {"status": "missing_selection"}
            continue
        if not isinstance(candidate, Mapping):
            source_bindings[field_id] = {"status": "invalid_candidate_shape"}
            return {
                "status": "source_binding_rejected",
                "reason_code": "invalid_candidate_shape",
                "field": field_id,
                "source_bindings": source_bindings,
                "contract_schema": schema_report,
                "semantic_truth_verified": False,
                "native": None,
            }
        try:
            node_id, projection, actual_value = _candidate_projection(
                candidate, nodes, text_by_id
            )
            dom_node_id = DomNodeId.try_new(int(node_id))
        except Exception as error:
            source_bindings[field_id] = {
                "status": "projection_mismatch",
                "candidate_id": candidate.get("id"),
                "node_id": candidate.get("node_id"),
                "projection": candidate.get("projection"),
                "detail_type": type(error).__name__,
            }
            return {
                "status": "source_binding_rejected",
                "reason_code": "candidate_projection_not_bound_to_document",
                "field": field_id,
                "source_bindings": source_bindings,
                "contract_schema": schema_report,
                "semantic_truth_verified": False,
                "native": None,
            }

        inside_root = root_id is not None and _inside_region(node_id, root_id, parents)
        source_bindings[field_id] = {
            "status": "bound" if inside_root else "outside_predicted_root",
            "candidate_id": candidate.get("id"),
            "node_id": node_id,
            "projection": projection,
            "source_value_matches": True,
            "inside_predicted_root": inside_root,
        }
        if not inside_root:
            return {
                "status": "source_binding_rejected",
                "reason_code": "candidate_outside_predicted_root",
                "field": field_id,
                "source_bindings": source_bindings,
                "contract_schema": schema_report,
                "ranking_ties": ties,
                "semantic_truth_verified": False,
                "native": None,
            }
        bound_candidates[field_id] = {
            "projection": projection,
            "value": actual_value,
            "dom_node_id": dom_node_id,
        }

    if coverage_status != "complete":
        reason_code = coverage_reason
        evidence = (
            Partial(
                status="partial",
                reason_code=reason_code,
                lost_items=lost_items,
            )
            if coverage_status == "partial"
            else Unknown(status="unknown", reason_code=reason_code)
        )
        located = Indeterminate(
            status="indeterminate",
            document_id=native_document_id,
            completeness=evidence,
            reason_code=reason_code,
        )
        extracted = runtime_contract.extract(located)
        outcome = extracted.validate()
        return {
            "status": "indeterminate",
            "document_id": str(native_document_id),
            "contract_id": str(schema.id),
            "contract_schema": schema_report,
            "predicted_root_id": root_id,
            "completeness": {
                "input_status": None
                if completeness is None
                else completeness.get("status"),
                "effective_status": coverage_status,
                "reason_code": reason_code,
                "lost_items": lost_items,
            },
            "source_bindings": source_bindings,
            "ranking_ties": ties,
            "semantic_truth_verified": False,
            "native": _native_report(extracted, outcome),
        }

    if root_id is None:
        located = NoMatch(status="no_match", document_id=native_document_id)
        extracted = runtime_contract.extract(located)
        outcome = extracted.validate()
        return {
            "status": "no_match",
            "document_id": str(native_document_id),
            "contract_id": str(schema.id),
            "contract_schema": schema_report,
            "predicted_root_id": None,
            "completeness": {
                "input_status": "complete",
                "effective_status": "complete",
                "reason_code": coverage_reason,
                "lost_items": lost_items,
            },
            "source_bindings": source_bindings,
            "ranking_ties": ties,
            "semantic_truth_verified": False,
            "native": _native_report(extracted, outcome),
        }

    if root_coordinate is None:
        return {
            "status": "source_binding_rejected",
            "reason_code": "predicted_root_coordinate_missing",
            "contract_schema": schema_report,
            "semantic_truth_verified": False,
            "native": None,
        }
    lineage = RegionLineage.new(RegionId.try_new(str(schema.id)), 0, root_coordinate)
    findings: list[Finding] = []
    for order, field_id in enumerate(PRODUCT_FIELDS):
        bound = bound_candidates.get(field_id)
        if bound is None:
            continue
        if bound["projection"] == "text":
            projected = TextValue(kind="text", value=bound["value"])
        else:
            projected = AttributeValue(
                kind="attribute",
                value=Attribute(name=bound["projection"][1:], value=bound["value"]),
            )
        coordinate = RenderedDomLocation(
            kind="rendered_dom",
            coordinate=DomCoordinate.new(epoch, bound["dom_node_id"]),
        )
        findings.append(
            Finding.try_new(
                native_document_id,
                OutputId.try_new(field_id),
                order,
                coordinate,
                projected,
                Complete(status="complete"),
                parent_region=lineage,
            )
        )

    located = Matched(
        status="matched",
        result=LocateResult.try_new_with_regions(
            native_document_id, (lineage,), tuple(findings)
        ),
    )
    extracted = runtime_contract.extract(located)
    outcome = extracted.validate()
    native = _native_report(extracted, outcome)
    successful = (
        outcome.status == "evaluated"
        and not outcome.issues
        and not outcome.extraction_diagnostics
        and len(outcome.records) == 1
    )
    return {
        "status": "native_validated" if successful else "native_issues",
        "document_id": str(native_document_id),
        "contract_id": str(schema.id),
        "contract_schema": schema_report,
        "predicted_root_id": root_id,
        "completeness": {
            "input_status": "complete",
            "effective_status": "complete",
            "reason_code": coverage_reason,
            "lost_items": lost_items,
        },
        "source_bindings": source_bindings,
        "ranking_ties": ties,
        "semantic_truth_verified": False,
        "native": native,
    }


def _file_identity(path_value: str | None) -> dict[str, Any]:
    if not path_value:
        return {"path": None, "sha256": None, "byte_len": None}
    path = Path(path_value).resolve()
    digest = hashlib.sha256()
    byte_len = 0
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            byte_len += len(chunk)
            digest.update(chunk)
    return {"path": str(path), "sha256": digest.hexdigest(), "byte_len": byte_len}


@lru_cache(maxsize=1)
def _cached_sdk_identity() -> dict[str, Any]:
    module_names = (
        "yosoi.outcomes",
        "yosoi.documents",
        "yosoi.contracts",
        "yosoi.runtime_contracts",
    )
    modules = {
        name: _file_identity(getattr(importlib.import_module(name), "__file__", None))
        for name in module_names
    }
    native = importlib.import_module("yosoi._native")
    return {
        "distribution_version": importlib.metadata.version("yosoi"),
        "package_version": getattr(
            importlib.import_module("yosoi"), "__version__", None
        ),
        "python_modules": modules,
        "native_module": _file_identity(getattr(native, "__file__", None)),
    }


def sdk_identity() -> dict[str, Any]:
    """Return the imported SDK identity for one campaign-level manifest."""
    return json.loads(json.dumps(_cached_sdk_identity(), sort_keys=True))


@lru_cache(maxsize=1)
def sdk_identity_ref() -> str:
    """Return a compact reference to the full imported SDK identity."""
    encoded = json.dumps(
        _cached_sdk_identity(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def validate_selection(
    case_document: dict[str, Any],
    document_id: str,
    predicted_root_id: str | int | None,
    selected_candidates: dict[str, dict[str, Any] | None],
    completeness: dict[str, Any] | None = None,
    required_fields: tuple[str, ...] | list[str] | None = None,
) -> dict[str, Any]:
    """Validate a selection and attach identity for the actually imported Yosoi SDK.

    The SDK module and native-extension hashes are calculated once and cached for
    this process; they bind every outcome to the implementation that validated it.
    """
    report = _validate_selection(
        case_document,
        document_id,
        predicted_root_id,
        selected_candidates,
        completeness,
        required_fields,
    )
    report["sdk_identity_ref"] = sdk_identity_ref()
    report.setdefault("ranking_ties", {})
    report.setdefault("semantic_truth_verified", False)
    report["dom_uniqueness_verified"] = False
    report["native_cardinality_scope"] = (
        "submitted selections only; this adapter supplies at most one finding per field"
    )
    binding_states = report.get("source_bindings", {})
    report["submitted_finding_count_by_field"] = {
        field_id: (
            1
            if report.get("status") in {"native_validated", "native_issues"}
            and isinstance(binding_states, Mapping)
            and isinstance(binding_states.get(field_id), Mapping)
            and binding_states[field_id].get("status") == "bound"
            else 0
        )
        for field_id in PRODUCT_FIELDS
    }
    return report
