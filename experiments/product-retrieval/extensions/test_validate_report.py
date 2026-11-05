"""Small report-folding and deduplicated-campaign tests without native validation."""

from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Any

import pytest

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

campaign = importlib.import_module("validate_report")


def candidate(case_id: str, field: str, node_id: int) -> dict[str, Any]:
    projection = "@data-product-id" if field == "id" else "text"
    return {
        "id": f"{case_id}:candidate:{field}",
        "node_id": str(node_id),
        "projection": projection,
        "text": f"value-{field}",
        "context": "not part of adapter input",
        "attributes": {"data-product-id": "not copied to selection"},
        "path": ["html", "body", "article"],
        "motifs": ["record"],
        "ancestors": ["root"],
    }


def corpus_data(case_id: str = "case-1") -> dict[str, Any]:
    candidates = [
        candidate(case_id, field, node_id)
        for node_id, field in enumerate(campaign.RESULT_FIELDS, start=1)
    ]
    return {
        "cases": [
            {
                "id": case_id,
                "source_id": "source-1",
                "variant": "baseline",
                "split": "controlled",
                "family": "simple",
                "document": {
                    "schema": "test-rendered-dom",
                    "nodes": [],
                },
                "candidates": candidates,
                # Target annotations are present in this source object but the
                # candidate index and adapter payload must never copy them.
                "expected": {"gold": "must-not-leak"},
                "expected_values": {"secret": "must-not-leak"},
            }
        ]
    }


def matrix_rows(case_id: str = "case-1") -> list[dict[str, Any]]:
    rows = []
    for method in ("method-a", "method-b"):
        for node_id, field in enumerate(campaign.RESULT_FIELDS, start=1):
            picked = candidate(case_id, field, node_id)
            rows.append(
                {
                    "case": case_id,
                    "group": "obj-001",
                    "representation": "context",
                    "method": method,
                    "mode": "global",
                    "source_id": "source-1",
                    "variant": "baseline",
                    "split": "controlled",
                    "family": "simple",
                    "seed_case": False,
                    "field": field,
                    "candidate_count": len(campaign.RESULT_FIELDS),
                    "top": [
                        {
                            "id": picked["id"],
                            "node_id": picked["node_id"],
                            "score": 1.0,
                        }
                    ],
                    "top_tie_count": 1,
                    "abstained": False,
                    "evaluation_mode": "global",
                    "expected_present": True,
                    "top1_correct": not (method == "method-b" and field == "price"),
                    "canonical_top1_correct": True,
                    "candidate_present": True,
                    "owner_correct": True,
                    "hit": {"1": True, "3": True, "5": True},
                    "reciprocal_rank": 1.0,
                }
            )
    return rows


def write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    corpus = corpus_data()
    corpus_path = tmp_path / "corpus.json"
    corpus_path.write_bytes(campaign._canonical_bytes(corpus))
    frozen = {
        "version": 1,
        "corpus_checksum": campaign._canonical_sha256(corpus),
        "implementation": {"methods.py": "test-code-digest"},
    }
    frozen_path = tmp_path / "frozen.json"
    frozen_path.write_bytes(campaign._canonical_bytes(frozen))
    report = {
        "version": 1,
        "frozen_checksum": campaign._canonical_sha256(frozen),
        "failures": [],
        "skipped_methods": [],
        "rows": matrix_rows(),
    }
    report_path = tmp_path / "report.json"
    report_path.write_bytes(campaign._canonical_bytes(report))
    return report_path, corpus_path


def test_stream_reader_yields_rows_and_hashes_original_bytes(tmp_path: Path) -> None:
    path = tmp_path / "small-report.json"
    payload = campaign._canonical_bytes({"version": 1, "failures": [], "rows": [1, 2]})
    path.write_bytes(payload)
    rows = []
    metadata, digest, count = campaign.stream_report_rows(path, rows.append)
    assert rows == [1, 2]
    assert count == 2
    assert metadata == {"version": 1, "failures": []}
    assert digest == campaign.hashlib.sha256(payload).hexdigest()


def test_prepare_folds_seven_fields_and_deduplicates_without_gold_leakage(
    tmp_path: Path,
) -> None:
    report_path, corpus_path = write_inputs(tmp_path)
    prepared = campaign.prepare_campaign(report_path, corpus_path)

    assert prepared["manifest"]["report_row_count"] == 14
    assert prepared["folded_record_key_count"] == 2
    # Two methods chose identical candidates; each of the two declared schemas
    # therefore creates one validation unit, not four.
    assert prepared["unique_selection_count"] == 2
    assert len(prepared["record_links"]) == 4
    selection = next(iter(prepared["selections"].values()))
    assert len(selection["record_keys"]) == 2
    assert set(selection["selected_candidates"]) == set(campaign.PRODUCT_FIELDS)
    assert all(
        set(candidate) == {"id", "node_id", "projection", "text", "top_tie_count"}
        for candidate in selection["selected_candidates"].values()
    )
    case_document = prepared["case_documents"][selection["case_id"]]
    assert "expected" not in case_document
    assert "expected_values" not in case_document


def test_validation_requires_go_and_never_receives_gold(tmp_path: Path) -> None:
    report_path, corpus_path = write_inputs(tmp_path)
    prepared = campaign.prepare_campaign(report_path, corpus_path)
    calls = []
    events = []

    def fake_validator(
        document_id,
        source_document_id,
        predicted_root_id,
        selected_candidates,
        completeness,
        *,
        required_fields,
    ):
        events.append("validation")
        calls.append(
            {
                "document_id": document_id,
                "source_document_id": source_document_id,
                "predicted_root_id": predicted_root_id,
                "selected_candidates": selected_candidates,
                "completeness": completeness,
                "required_fields": required_fields,
            }
        )
        assert "expected" not in document_id
        assert all(
            not ({"expected", "expected_values", "gold"} & set(candidate))
            for candidate in selected_candidates.values()
            if candidate is not None
        )
        return {
            "status": "native_validated",
            "native": {
                "extraction_status": "candidates",
                "validation_status": "evaluated",
                "records": [{"value": {}}],
                "issues": [],
                "extraction_diagnostics": [],
                "failure": None,
            },
            "source_bindings": {},
            "ranking_ties": {},
            "semantic_truth_verified": False,
        }

    with pytest.raises(PermissionError, match="requires explicit go"):
        campaign.execute_campaign(prepared, validator=fake_validator)
    assert calls == []

    def save_manifest(manifest):
        events.append("manifest")
        assert manifest["prepared_unique_selections"] == 2
        assert manifest["report"]["sha256"] == prepared["manifest"]["report"]["sha256"]

    report = campaign.execute_campaign(
        prepared, go=True, validator=fake_validator, on_start=save_manifest
    )
    assert len(calls) == 2
    assert events == ["manifest", "validation", "validation"]
    assert report["unique_selection_count"] == 2
    assert report["record_key_count"] == 4
    assert report["native_valid_but_wrong_count"] == 2
    assert report["unique_selection_status_counts"] == {"native_validated": 2}
    assert all(
        "truth_after_validation" not in call["selected_candidates"] for call in calls
    )


def test_missing_row_or_candidate_cap_marks_completeness_partial() -> None:
    case_index = campaign._index_corpus_cases(corpus_data())
    rows = matrix_rows()
    rows = [
        row
        for row in rows
        if not (row["method"] == "method-a" and row["field"] == "material")
    ]
    rows = [
        {
            **row,
            "candidate_count": campaign.DEFAULT_CANDIDATE_LIMIT,
        }
        if row["method"] == "method-b"
        else row
        for row in rows
    ]
    records, errors = campaign.fold_report_rows(rows, case_index)
    assert errors == []
    for record in records:
        if record["key"]["method"] == "method-a":
            assert record["completeness"]["status"] == "partial"
            assert "material" in record["missing_report_fields"]
        else:
            assert record["completeness"]["status"] == "partial"
            assert record["completeness"]["budget_exhausted"] is True


if __name__ == "__main__":
    import pytest

    raise SystemExit(pytest.main([__file__, "-q"]))
