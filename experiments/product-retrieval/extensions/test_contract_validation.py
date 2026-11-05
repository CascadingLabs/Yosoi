"""Small native Contract checks for source-bound ranked candidates."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from contract_validation import (
    REQUIRED_FIELDS,
    sdk_identity,
    sdk_identity_ref,
    validate_selection,
)


def dom_snapshot(*, product_name: str = "Canvas Bag") -> dict[str, object]:
    nodes = [
        {"id": 1, "kind": "document", "parent": None, "children": [2]},
        {
            "id": 2,
            "kind": "element",
            "tag_name": "html",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 1,
            "children": [3],
            "attributes": [],
        },
        {
            "id": 3,
            "kind": "element",
            "tag_name": "body",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 2,
            "children": [4, 20],
            "attributes": [],
        },
        {
            "id": 4,
            "kind": "element",
            "tag_name": "article",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 3,
            "children": [5, 7, 9, 11, 13],
            "attributes": [
                {"name": "data-product-id", "namespace_uri": "", "value": "prod-7"}
            ],
        },
        {
            "id": 5,
            "kind": "element",
            "tag_name": "h1",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 4,
            "children": [6],
            "attributes": [],
        },
        {
            "id": 6,
            "kind": "text",
            "parent": 5,
            "children": [],
            "value": f"  {product_name[:6]}  \n {product_name[6:]}  ",
        },
        {
            "id": 7,
            "kind": "element",
            "tag_name": "span",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 4,
            "children": [8],
            "attributes": [{"name": "class", "namespace_uri": "", "value": "price"}],
        },
        {"id": 8, "kind": "text", "parent": 7, "children": [], "value": "$18.00"},
        {
            "id": 9,
            "kind": "element",
            "tag_name": "span",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 4,
            "children": [10],
            "attributes": [],
        },
        {"id": 10, "kind": "text", "parent": 9, "children": [], "value": "Sand"},
        {
            "id": 11,
            "kind": "element",
            "tag_name": "span",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 4,
            "children": [12],
            "attributes": [],
        },
        {
            "id": 12,
            "kind": "text",
            "parent": 11,
            "children": [],
            "value": "Cotton canvas",
        },
        {
            "id": 13,
            "kind": "element",
            "tag_name": "p",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 4,
            "children": [14, 15],
            "attributes": [],
        },
        {"id": 14, "kind": "text", "parent": 13, "children": [], "value": "In stock"},
        {
            "id": 15,
            "kind": "element",
            "tag_name": "script",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 13,
            "children": [16],
            "attributes": [],
        },
        {
            "id": 16,
            "kind": "text",
            "parent": 15,
            "children": [],
            "value": "do not project",
        },
        {
            "id": 20,
            "kind": "element",
            "tag_name": "article",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 3,
            "children": [21, 23],
            "attributes": [],
        },
        {
            "id": 21,
            "kind": "element",
            "tag_name": "span",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 20,
            "children": [22],
            "attributes": [],
        },
        {"id": 22, "kind": "text", "parent": 21, "children": [], "value": "$99.00"},
        {
            "id": 23,
            "kind": "element",
            "tag_name": "h1",
            "namespace_uri": "http://www.w3.org/1999/xhtml",
            "parent": 20,
            "children": [24],
            "attributes": [],
        },
        {"id": 24, "kind": "text", "parent": 23, "children": [], "value": "Decoy"},
    ]
    return {
        "schema": "yosoi.rendered-dom.v1",
        "tree_model": "document_light_dom",
        "document_epoch": 9,
        "root": 1,
        "nodes": nodes,
    }


def selected(snapshot: dict[str, object]) -> dict[str, dict[str, object]]:
    return {
        "id": {
            "id": "id-candidate",
            "node_id": "4",
            "projection": "@data-product-id",
            "text": "prod-7",
        },
        "name": {
            "id": "name-candidate",
            "node_id": "5",
            "projection": "text",
            "text": "Canvas Bag",
        },
        "price": {
            "id": "price-candidate",
            "node_id": "7",
            "projection": "text",
            "text": "$18.00",
        },
        "color": {
            "id": "color-candidate",
            "node_id": "9",
            "projection": "text",
            "text": "Sand",
        },
        "material": {
            "id": "material-candidate",
            "node_id": "11",
            "projection": "text",
            "text": "Cotton canvas",
        },
        "stock": {
            "id": "stock-candidate",
            "node_id": "13",
            "projection": "text",
            "text": "In stock",
        },
    }


def complete_scan(*, price_ties: int = 1) -> dict[str, object]:
    return {
        "status": "complete",
        "candidate_generation_complete": True,
        "all_candidates_scored": True,
        "fields": {
            field: {
                "status": "complete",
                "top_tie_count": price_ties if field == "price" else 1,
            }
            for field in REQUIRED_FIELDS
        },
    }


def test_complete_source_bound_selection_runs_native_runtime_contract() -> None:
    snapshot = dom_snapshot()
    report = validate_selection(
        snapshot,
        "matrix-case-1",
        4,
        selected(snapshot),
        complete_scan(price_ties=2),
    )

    assert report["status"] == "native_validated"
    assert report["native"]["extraction_status"] == "candidates"
    assert report["native"]["validation_status"] == "evaluated"
    assert len(report["native"]["records"]) == 1
    assert report["native"]["issues"] == []
    assert report["source_bindings"]["id"]["projection"] == "@data-product-id"
    assert report["source_bindings"]["name"]["source_value_matches"] is True
    assert report["ranking_ties"] == {"price": 2}
    assert report["semantic_truth_verified"] is False
    assert report["dom_uniqueness_verified"] is False
    assert report["native_cardinality_scope"].startswith("submitted selections only")
    assert report["submitted_finding_count_by_field"] == {
        field: 1 for field in REQUIRED_FIELDS
    }
    schema = report["contract_schema"]
    assert schema["id"] == "product"
    assert schema["identity"]
    assert schema["scope"] == "repeated"

    identity = sdk_identity()
    assert identity["distribution_version"]
    assert report["sdk_identity_ref"] == sdk_identity_ref()
    for module_name in (
        "yosoi.outcomes",
        "yosoi.documents",
        "yosoi.contracts",
        "yosoi.runtime_contracts",
    ):
        module_identity = identity["python_modules"][module_name]
        assert Path(module_identity["path"]).is_file()
        assert len(module_identity["sha256"]) == 64
        assert module_identity["byte_len"] > 0
    native_identity = identity["native_module"]
    assert Path(native_identity["path"]).is_file()
    assert len(native_identity["sha256"]) == 64
    assert native_identity["byte_len"] > 0

    record = report["native"]["records"][0]
    assert record["value"]["name"]["value"]["value"] == "Canvas Bag"
    assert record["value"]["id"]["value"]["value"] == "prod-7"
    assert record["candidate"]["region"]["coordinate"]["coordinate"]["node_id"] == 4


def test_complete_scan_with_missing_selection_reports_native_missing_required() -> None:
    snapshot = dom_snapshot()
    choices = selected(snapshot)
    choices["material"] = None
    report = validate_selection(
        snapshot, "matrix-case-missing", 4, choices, complete_scan()
    )

    assert report["status"] == "native_issues"
    assert report["source_bindings"]["material"]["status"] == "missing_selection"
    issues = report["native"]["issues"]
    assert len(issues) == 1
    assert any(
        field["field"] == "material" and field["kind"]["kind"] == "missing_required"
        for field in issues[0]["fields"]
    )


def test_budgeted_or_unknown_search_never_forges_complete_findings() -> None:
    snapshot = dom_snapshot()
    budgeted = validate_selection(
        snapshot,
        "matrix-case-budgeted",
        4,
        selected(snapshot),
        {"status": "complete", "budget_exhausted": True},
    )
    assert budgeted["status"] == "indeterminate"
    assert budgeted["completeness"]["effective_status"] == "partial"
    assert budgeted["native"]["extraction_status"] == "indeterminate"
    assert budgeted["native"]["validation_status"] == "indeterminate"

    unknown = validate_selection(
        snapshot, "matrix-case-unknown", 4, selected(snapshot), None
    )
    assert unknown["status"] == "indeterminate"
    assert unknown["native"]["validation_status"] == "indeterminate"


def test_candidate_outside_predicted_root_is_rejected_before_native_validation() -> (
    None
):
    snapshot = dom_snapshot()
    choices = selected(snapshot)
    choices["price"] = {
        "id": "decoy-price",
        "node_id": "21",
        "projection": "text",
        "text": "$99.00",
    }
    report = validate_selection(
        snapshot, "matrix-case-decoy", 4, choices, complete_scan()
    )

    assert report["status"] == "source_binding_rejected"
    assert report["reason_code"] == "candidate_outside_predicted_root"
    assert report["source_bindings"]["price"]["status"] == "outside_predicted_root"
    assert report["native"] is None


def test_projection_mismatch_rejects_before_native_extraction() -> None:
    snapshot = dom_snapshot()
    choices = selected(snapshot)
    choices["price"] = {**choices["price"], "text": "$999.00"}
    report = validate_selection(
        snapshot, "matrix-case-mismatch", 4, choices, complete_scan()
    )

    assert report["status"] == "source_binding_rejected"
    assert report["reason_code"] == "candidate_projection_not_bound_to_document"
    assert report["native"] is None


def test_empty_selection_with_complete_root_still_creates_native_candidate() -> None:
    snapshot = dom_snapshot()
    report = validate_selection(
        snapshot,
        "matrix-case-empty",
        4,
        {field: None for field in REQUIRED_FIELDS},
        complete_scan(),
    )

    assert report["status"] == "native_issues"
    assert report["native"]["extraction_status"] == "candidates"
    assert len(report["native"]["issues"]) == 1
    assert len(report["native"]["issues"][0]["fields"]) == len(REQUIRED_FIELDS)


def test_complete_no_root_returns_native_no_match_without_fabricating_region() -> None:
    snapshot = dom_snapshot()
    report = validate_selection(
        snapshot,
        "matrix-case-no-root",
        None,
        {field: None for field in REQUIRED_FIELDS},
        complete_scan(),
    )
    assert report["status"] == "no_match"
    assert report["native"]["extraction_status"] == "no_match"
    assert report["native"]["validation_status"] == "no_match"


def test_explicit_optional_schema_uses_native_zero_or_one_without_inference() -> None:
    snapshot = dom_snapshot()
    choices = selected(snapshot)
    for field in ("color", "material", "stock"):
        choices[field] = None

    report = validate_selection(
        snapshot,
        "matrix-case-optionals",
        4,
        choices,
        complete_scan(),
        required_fields=("id", "name", "price"),
    )

    assert report["status"] == "native_validated"
    contract_schema = report["contract_schema"]
    assert contract_schema["identity"]
    assert contract_schema["required_fields"] == ["id", "name", "price"]
    assert contract_schema["optional_fields"] == ["color", "material", "stock"]
    cardinality = {
        field["id"]: field["cardinality"] for field in contract_schema["fields"]
    }
    assert cardinality == {
        "id": "exactly_one",
        "name": "exactly_one",
        "price": "exactly_one",
        "color": "zero_or_one",
        "material": "zero_or_one",
        "stock": "zero_or_one",
    }
    record = report["native"]["records"][0]
    assert record["value"]["color"] == {
        "cardinality": "zero_or_one",
        "value": None,
    }


def test_invalid_required_field_configuration_is_rejected() -> None:
    report = validate_selection(
        dom_snapshot(),
        "matrix-case-invalid-schema",
        4,
        selected(dom_snapshot()),
        complete_scan(),
        required_fields=("id", "not-a-product-field"),
    )
    assert report["status"] == "invalid_contract_schema"
    assert report["contract_schema"] is None
