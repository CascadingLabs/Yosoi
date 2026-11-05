"""Fold frozen retrieval rows into deduplicated, gated Contract validations."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import time
from collections import Counter, defaultdict
from collections.abc import Mapping
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
PRODUCT_ROOT = HERE.parent
REPO_ROOT = PRODUCT_ROOT.parents[1]
ROW_KEY_FIELDS = ("case", "group", "representation", "method", "mode")
RESULT_FIELDS = ("root", "id", "name", "price", "color", "material", "stock")
PRODUCT_FIELDS = RESULT_FIELDS[1:]
DEFAULT_CANDIDATE_LIMIT = 5_000
SCHEMA_CONFIGS: dict[str, tuple[str, ...]] = {
    "six_required": PRODUCT_FIELDS,
    "core_required": ("id", "name", "price"),
}


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def _canonical_sha256(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _file_identity(path: Path, digest: str | None = None) -> dict[str, Any]:
    stat = path.stat()
    return {
        "path": str(path.resolve()),
        "byte_len": stat.st_size,
        "sha256": digest if digest is not None else _sha256_file(path),
    }


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        while chunk := stream.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


class _StreamingJson:
    """Incrementally parse one top-level report object and hash its exact bytes."""

    def __init__(self, path: Path, chunk_chars: int = 1 << 20) -> None:
        self.path = path
        self.stream = path.open("r", encoding="utf-8", newline="")
        self.chunk_chars = chunk_chars
        self.buffer = ""
        self.position = 0
        self.eof = False
        self.digest = hashlib.sha256()
        self.decoder = json.JSONDecoder()

    def close(self) -> None:
        self.stream.close()

    def _fill(self, *, preserve: bool = False) -> bool:
        if self.eof:
            return False
        if not preserve and self.position:
            self.buffer = self.buffer[self.position :]
            self.position = 0
        chunk = self.stream.read(self.chunk_chars)
        if not chunk:
            self.eof = True
            return False
        self.digest.update(chunk.encode("utf-8"))
        self.buffer += chunk
        return True

    def _skip_space(self) -> None:
        while True:
            while (
                self.position < len(self.buffer)
                and self.buffer[self.position] in " \t\r\n"
            ):
                self.position += 1
            if self.position < len(self.buffer) or not self._fill():
                return

    def peek(self) -> str | None:
        self._skip_space()
        return self.buffer[self.position] if self.position < len(self.buffer) else None

    def expect(self, char: str) -> None:
        observed = self.peek()
        if observed != char:
            raise ValueError(f"invalid report JSON structure; expected {char!r}")
        self.position += 1

    def read_value(self) -> Any:
        self._skip_space()
        if self.position >= len(self.buffer):
            raise ValueError("unexpected end of report JSON")
        if self.position:
            self.buffer = self.buffer[self.position :]
            self.position = 0
        while True:
            try:
                value, end = self.decoder.raw_decode(self.buffer, 0)
            except json.JSONDecodeError:
                if not self._fill(preserve=True):
                    raise
                continue
            if end == len(self.buffer) and not self.eof:
                self._fill(preserve=True)
                continue
            self.position = end
            return value

    def read_rows(self, consume) -> int:
        self.expect("[")
        if self.peek() == "]":
            self.position += 1
            return 0
        count = 0
        while True:
            consume(self.read_value())
            count += 1
            separator = self.peek()
            if separator == ",":
                self.position += 1
                continue
            if separator == "]":
                self.position += 1
                return count
            raise ValueError("invalid report rows array")

    def finish(self) -> str:
        self._skip_space()
        if self.position < len(self.buffer):
            raise ValueError("trailing content after report JSON object")
        while not self.eof:
            self._fill()
            self._skip_space()
            if self.position < len(self.buffer):
                raise ValueError("trailing content after report JSON object")
        return self.digest.hexdigest()


def stream_report_rows(path: Path, consume) -> tuple[dict[str, Any], str, int]:
    """Stream report rows to ``consume`` and return metadata, digest, and row count."""
    reader = _StreamingJson(path)
    metadata: dict[str, Any] = {}
    rows_seen = False
    row_count = 0
    try:
        reader.expect("{")
        while reader.peek() != "}":
            key = reader.read_value()
            if not isinstance(key, str):
                raise ValueError("report object keys must be strings")
            reader.expect(":")
            if key == "rows":
                if rows_seen:
                    raise ValueError("report contains duplicate rows fields")
                rows_seen = True
                row_count = reader.read_rows(consume)
            else:
                metadata[key] = reader.read_value()
            separator = reader.peek()
            if separator == ",":
                reader.position += 1
            elif separator == "}":
                break
            else:
                raise ValueError("invalid top-level report JSON object")
        reader.expect("}")
        report_sha256 = reader.finish()
    finally:
        reader.close()
    if not rows_seen:
        raise ValueError("report has no rows array")
    return metadata, report_sha256, row_count


def _candidate_projection(candidate: Mapping[str, Any]) -> dict[str, Any]:
    """Copy only source identity and projected content needed by the adapter."""
    return {
        "id": candidate.get("id"),
        "node_id": str(candidate.get("node_id", "")),
        "projection": candidate.get("projection"),
        "text": candidate.get("text"),
    }


def _index_corpus_cases(corpus_data: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    """Index document and candidate source data without reading annotation keys."""
    raw_cases = corpus_data.get("cases")
    if not isinstance(raw_cases, list):
        raise ValueError("corpus has no cases array")
    indexed: dict[str, dict[str, Any]] = {}
    for raw_case in raw_cases:
        if not isinstance(raw_case, Mapping):
            raise ValueError("corpus contains a non-mapping case")
        case_id = raw_case.get("id")
        document = raw_case.get("document")
        raw_candidates = raw_case.get("candidates")
        if (
            not isinstance(case_id, str)
            or not isinstance(document, Mapping)
            or not isinstance(raw_candidates, list)
        ):
            raise ValueError("corpus case lacks id, document, or candidates")
        if case_id in indexed:
            raise ValueError(f"duplicate corpus case {case_id}")
        candidate_by_id: dict[str, dict[str, Any]] = {}
        candidate_error = None
        for raw_candidate in raw_candidates:
            if not isinstance(raw_candidate, Mapping):
                candidate_error = "invalid_candidate_record"
                break
            candidate = _candidate_projection(raw_candidate)
            candidate_id = candidate["id"]
            if not isinstance(candidate_id, str) or candidate_id in candidate_by_id:
                candidate_error = "invalid_or_duplicate_candidate_id"
                break
            if not isinstance(candidate["text"], str) or not isinstance(
                candidate["projection"], str
            ):
                candidate_error = "invalid_candidate_projection"
                break
            candidate_by_id[candidate_id] = candidate
        indexed[case_id] = {
            "document": dict(document),
            "candidate_by_id": candidate_by_id,
            "candidate_count": len(raw_candidates),
            "candidate_error": candidate_error,
            "variant": raw_case.get("variant"),
            "split": raw_case.get("split"),
            "family": raw_case.get("family"),
            "source_id": raw_case.get("source_id"),
        }
    return indexed


def _row_key(row: Mapping[str, Any]) -> tuple[str, ...]:
    values = []
    for field in ROW_KEY_FIELDS:
        value = row.get(field)
        if not isinstance(value, str) or not value:
            raise ValueError(f"report row has an invalid {field!r} key")
        values.append(value)
    return tuple(values)


def _candidate_from_top(
    row: Mapping[str, Any], case_info: Mapping[str, Any]
) -> tuple[dict[str, Any] | None, str | None]:
    if case_info.get("candidate_error"):
        return None, f"corpus_candidate_index_error:{case_info['candidate_error']}"
    top = row.get("top")
    if not isinstance(top, list):
        return None, "top_candidates_not_a_list"
    if not top:
        if row.get("abstained") is False:
            return None, "nonabstained_row_has_no_top_candidate"
        return None, None
    first = top[0]
    if not isinstance(first, Mapping):
        return None, "top_candidate_not_a_mapping"
    candidate_id = first.get("id")
    if not isinstance(candidate_id, str):
        return None, "top_candidate_id_missing"
    candidate_by_id = case_info["candidate_by_id"]
    candidate = candidate_by_id.get(candidate_id)
    if candidate is None:
        return None, "top_candidate_not_in_corpus"
    observed_node_id = first.get("node_id")
    if observed_node_id is not None and str(observed_node_id) != candidate["node_id"]:
        return None, "report_candidate_node_id_disagrees_with_corpus"
    selected = dict(candidate)
    selected["top_tie_count"] = row.get("top_tie_count", 1)
    return selected, None


class _ReportFolder:
    """Incrementally fold report rows without holding the full report in memory."""

    def __init__(
        self,
        case_index: Mapping[str, Mapping[str, Any]],
        report_failures=(),
        *,
        candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    ) -> None:
        if candidate_limit < 1:
            raise ValueError("candidate_limit must be positive")
        self.case_index = case_index
        self.candidate_limit = candidate_limit
        self.records: dict[tuple[str, ...], dict[str, Any]] = {}
        self.fold_errors: list[dict[str, Any]] = []
        self.failure_lookup: dict[
            tuple[str, str, str, str, str], list[dict[str, Any]]
        ] = defaultdict(list)
        self.add_failures(report_failures)

    def add_failures(self, report_failures) -> None:
        for failure in report_failures:
            if not isinstance(failure, Mapping):
                continue
            try:
                key = tuple(
                    str(failure[name])
                    for name in (
                        "case",
                        "group",
                        "representation",
                        "method",
                        "field",
                    )
                )
            except KeyError:
                continue
            self.failure_lookup[key].append(
                {
                    "error": failure.get("error"),
                    "reason_code": "scorer_failure",
                }
            )

    def consume(self, row: Any) -> None:
        if not isinstance(row, Mapping):
            self.fold_errors.append({"reason_code": "report_row_not_a_mapping"})
            return
        try:
            key = _row_key(row)
        except ValueError as error:
            self.fold_errors.append(
                {"reason_code": "invalid_record_key", "detail": str(error)}
            )
            return
        case_id, _group, _representation, _method, _mode = key
        case_info = self.case_index.get(case_id)
        if case_info is None:
            self.fold_errors.append(
                {"reason_code": "report_case_not_in_corpus", "record_key": list(key)}
            )
            return
        field_id = row.get("field")
        if field_id not in RESULT_FIELDS:
            self.fold_errors.append(
                {
                    "reason_code": "unknown_report_field",
                    "record_key": list(key),
                    "field": field_id,
                }
            )
            return

        record = self.records.setdefault(
            key,
            {
                "key": dict(zip(ROW_KEY_FIELDS, key, strict=True)),
                "case_metadata": {
                    "source_id": case_info.get("source_id"),
                    "variant": case_info.get("variant"),
                    "split": case_info.get("split"),
                    "family": case_info.get("family"),
                    "seed_case": bool(row.get("seed_case")),
                },
                "case_document": case_info["document"],
                "case_candidate_count": case_info["candidate_count"],
                "case_candidate_error": case_info.get("candidate_error"),
                "rows_by_field": {},
                "selection_errors": [],
                "truth_after_validation": {},
            },
        )

        if field_id in record["rows_by_field"]:
            record["selection_errors"].append(
                {"field": field_id, "reason_code": "duplicate_report_field_row"}
            )
            return

        selected, error = _candidate_from_top(row, case_info)
        if error is not None:
            record["selection_errors"].append({"field": field_id, "reason_code": error})

        candidate_count = row.get("candidate_count")
        if not isinstance(candidate_count, int) or isinstance(candidate_count, bool):
            candidate_count = None
        tie_count = row.get("top_tie_count", 0)
        if (
            not isinstance(tie_count, int)
            or isinstance(tie_count, bool)
            or tie_count < 0
        ):
            tie_count = 0
        record["rows_by_field"][field_id] = {
            "selected": selected,
            "candidate_count": candidate_count,
            "top_tie_count": tie_count,
            "abstained": row.get("abstained"),
            "evaluation_mode": row.get("evaluation_mode"),
        }
        # This sidecar is not part of the adapter input; interpretation is deferred
        # until all deduplicated native calls have returned.
        record["truth_after_validation"][field_id] = {
            name: row.get(name)
            for name in (
                "expected_present",
                "top1_correct",
                "canonical_top1_correct",
                "candidate_present",
                "owner_correct",
                "hit",
                "reciprocal_rank",
            )
        }

    def finish(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        folded: list[dict[str, Any]] = []
        for key, record in self.records.items():
            case_id, group, representation, method, _mode = key
            field_coverage: dict[str, dict[str, Any]] = {}
            missing_rows: list[str] = []
            scorer_errors: list[dict[str, Any]] = []
            candidate_cap = (
                record["case_candidate_count"] >= self.candidate_limit
                or record["case_candidate_error"] is not None
                or any(
                    row is not None
                    and row["candidate_count"] is not None
                    and row["candidate_count"] >= self.candidate_limit
                    for row in record["rows_by_field"].values()
                )
            )
            for field_id in PRODUCT_FIELDS:
                field_row = record["rows_by_field"].get(field_id)
                failures_for_field = self.failure_lookup.get(
                    (case_id, group, representation, method, field_id), []
                )
                if field_row is None:
                    missing_rows.append(field_id)
                if failures_for_field:
                    scorer_errors.extend(
                        {"field": field_id, **failure} for failure in failures_for_field
                    )
                complete = (
                    field_row is not None
                    and not failures_for_field
                    and not candidate_cap
                    and field_row["candidate_count"] is not None
                    and field_row["candidate_count"] < self.candidate_limit
                    and not any(
                        error["field"] == field_id
                        for error in record["selection_errors"]
                    )
                )
                field_coverage[field_id] = {
                    "status": "complete" if complete else "partial",
                    "top_tie_count": (
                        0 if field_row is None else field_row["top_tie_count"]
                    ),
                }

            root_row = record["rows_by_field"].get("root")
            root_failures = self.failure_lookup.get(
                (case_id, group, representation, method, "root"), []
            )
            if root_row is None:
                missing_rows.append("root")
            if root_failures:
                scorer_errors.extend(
                    {"field": "root", **failure} for failure in root_failures
                )
            root_complete = (
                root_row is not None
                and not root_failures
                and not candidate_cap
                and root_row["candidate_count"] is not None
                and root_row["candidate_count"] < self.candidate_limit
                and not any(
                    error["field"] == "root" for error in record["selection_errors"]
                )
            )
            all_rows_complete = (
                root_complete
                and all(
                    item["status"] == "complete" for item in field_coverage.values()
                )
                and not scorer_errors
            )
            completeness = {
                "status": "complete" if all_rows_complete else "partial",
                "reason_code": (
                    "complete_bounded_candidate_scan"
                    if all_rows_complete
                    else "report_rows_missing_or_candidate_budgeted"
                ),
                "candidate_generation_complete": not candidate_cap,
                "all_candidates_scored": (
                    not missing_rows
                    and not scorer_errors
                    and not record["selection_errors"]
                ),
                "budget_exhausted": candidate_cap,
                "fields": field_coverage,
            }

            root_candidate = None if root_row is None else root_row.get("selected")
            predicted_root_id = (
                None if root_candidate is None else str(root_candidate["node_id"])
            )
            selected_candidates = {
                field_id: (
                    None
                    if record["rows_by_field"].get(field_id) is None
                    else record["rows_by_field"][field_id]["selected"]
                )
                for field_id in PRODUCT_FIELDS
            }
            record["predicted_root_id"] = predicted_root_id
            record["selected_candidates"] = selected_candidates
            record["completeness"] = completeness
            record["scorer_failures"] = scorer_errors
            record["missing_report_fields"] = missing_rows
            record["ranking_ties"] = {
                field_id: detail["top_tie_count"]
                for field_id, detail in field_coverage.items()
                if detail["top_tie_count"] > 1
            }
            root_ties = 0 if root_row is None else root_row["top_tie_count"]
            if root_ties > 1:
                record["ranking_ties"]["root"] = root_ties
            folded.append(record)
        return folded, self.fold_errors


def fold_report_rows(
    rows,
    case_index: Mapping[str, Mapping[str, Any]],
    *,
    report_failures=(),
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Fold seven field rows into record keys without passing truth to validators."""
    folder = _ReportFolder(case_index, report_failures, candidate_limit=candidate_limit)
    for row in rows:
        folder.consume(row)
    return folder.finish()


def _normalize_schema_configs(
    schema_configs: Mapping[str, tuple[str, ...]] | None,
) -> dict[str, tuple[str, ...]]:
    raw = SCHEMA_CONFIGS if schema_configs is None else schema_configs
    normalized: dict[str, tuple[str, ...]] = {}
    for name, fields in raw.items():
        if not isinstance(name, str) or not name:
            raise ValueError("schema configuration names must be non-empty strings")
        if not isinstance(fields, (list, tuple)) or not all(
            isinstance(field, str) for field in fields
        ):
            raise ValueError(f"schema configuration {name!r} must contain field IDs")
        requested = tuple(fields)
        if (
            not requested
            or len(set(requested)) != len(requested)
            or not set(requested).issubset(PRODUCT_FIELDS)
        ):
            raise ValueError(
                f"schema configuration {name!r} has invalid required fields"
            )
        requested_set = set(requested)
        normalized[name] = tuple(
            field for field in PRODUCT_FIELDS if field in requested_set
        )
    if not normalized:
        raise ValueError("at least one schema configuration is required")
    return normalized


def build_deduplicated_plan(
    records: list[dict[str, Any]],
    case_index: Mapping[str, Mapping[str, Any]],
    *,
    schema_configs: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Create native inputs and row links, deduplicated by case/schema/completeness.

    Gold-derived correctness values stay in a separate record sidecar and are not
    copied into any adapter selection input. The executor passes only one selection
    entry to the SDK adapter at a time.
    """
    configs = _normalize_schema_configs(schema_configs)
    selections: dict[str, dict[str, Any]] = {}
    record_links: list[dict[str, Any]] = []
    case_documents = {
        case_id: case_info["document"] for case_id, case_info in case_index.items()
    }

    for record in records:
        case_id = record["key"]["case"]
        case_info = case_index.get(case_id)
        if case_info is None:
            continue
        for schema_name, required_fields in configs.items():
            selection = {
                "case_id": case_id,
                "document_id": case_id,
                "predicted_root_id": record["predicted_root_id"],
                "selected_candidates": record["selected_candidates"],
                "completeness": record["completeness"],
                "required_fields": list(required_fields),
                "selection_errors": record["selection_errors"],
                "schema_name": schema_name,
            }
            identity = {
                key: selection[key]
                for key in (
                    "case_id",
                    "document_id",
                    "predicted_root_id",
                    "selected_candidates",
                    "completeness",
                    "required_fields",
                    "selection_errors",
                )
            }
            selection_id = hashlib.sha256(_canonical_bytes(identity)).hexdigest()
            selection_entry = selections.setdefault(
                selection_id,
                {
                    **selection,
                    "record_keys": [],
                    "candidate_universe_count": case_info["candidate_count"],
                },
            )
            selection_entry["record_keys"].append(record["key"])
            record_links.append(
                {
                    "record_key": record["key"],
                    "case_metadata": record["case_metadata"],
                    "schema_name": schema_name,
                    "selection_id": selection_id,
                    "truth_after_validation": record["truth_after_validation"],
                    "ranking_ties": record["ranking_ties"],
                    "scorer_failures": record["scorer_failures"],
                    "missing_report_fields": record["missing_report_fields"],
                }
            )

    return {
        "schema_configs": {
            name: list(required_fields) for name, required_fields in configs.items()
        },
        "case_documents": case_documents,
        "selections": selections,
        "record_links": record_links,
    }


def _load_corpus(path: Path) -> tuple[dict[str, Any], str]:
    raw = path.read_bytes()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("corpus JSON is not an object")
    return data, hashlib.sha256(raw).hexdigest()


def prepare_campaign(
    report_path: Path,
    corpus_path: Path | None = None,
    *,
    candidate_limit: int = DEFAULT_CANDIDATE_LIMIT,
    schema_configs: Mapping[str, tuple[str, ...]] | None = None,
) -> dict[str, Any]:
    """Stream-fold one frozen report and prepare deduplicated Contract selections.

    This function does not invoke Contract validation. It reads report rows once,
    selects candidate source data only from corpus candidate records, and keeps row
    correctness metrics in a sidecar that execute_campaign reads only after native
    validation returns.
    """
    report_path = Path(report_path)
    corpus_path = (
        report_path.parent / "corpus.json" if corpus_path is None else Path(corpus_path)
    )
    frozen_path = report_path.parent / "frozen.json"
    corpus_data, corpus_raw_sha = _load_corpus(corpus_path)
    case_index = _index_corpus_cases(corpus_data)
    folder = _ReportFolder(case_index, candidate_limit=candidate_limit)
    report_metadata, report_sha, report_row_count = stream_report_rows(
        report_path, folder.consume
    )
    folder.add_failures(report_metadata.get("failures", []))
    records, fold_errors = folder.finish()

    frozen_data: dict[str, Any] | None = None
    frozen_sha: str | None = None
    if frozen_path.is_file():
        frozen_data, frozen_raw_sha = _load_corpus(frozen_path)
        frozen_sha = frozen_raw_sha
        expected_frozen = report_metadata.get("frozen_checksum")
        if (
            expected_frozen is not None
            and _canonical_sha256(frozen_data) != expected_frozen
        ):
            raise ValueError("report frozen checksum does not match frozen.json")
        expected_corpus = frozen_data.get("corpus_checksum")
        if (
            expected_corpus is not None
            and _canonical_sha256(corpus_data) != expected_corpus
        ):
            raise ValueError("frozen corpus checksum does not match corpus.json")

    plan = build_deduplicated_plan(records, case_index, schema_configs=schema_configs)
    plan["fold_errors"] = fold_errors
    plan["manifest"] = {
        "report": _file_identity(report_path, report_sha),
        "report_row_count": report_row_count,
        "corpus": _file_identity(corpus_path, corpus_raw_sha),
        "frozen": None
        if frozen_sha is None
        else _file_identity(frozen_path, frozen_sha),
        "frozen_checksum": report_metadata.get("frozen_checksum"),
        "semantic_artifact_checksum": report_metadata.get("semantic_artifact_checksum"),
        "report_failures": report_metadata.get("failures", []),
        "skipped_methods": report_metadata.get("skipped_methods", []),
        "candidate_limit": candidate_limit,
        "schema_configs": plan["schema_configs"],
        "campaign_code": _file_identity(Path(__file__)),
        "adapter_code": _file_identity(HERE / "contract_validation.py"),
        "experiment_implementation": (
            None if frozen_data is None else frozen_data.get("implementation")
        ),
    }
    plan["folded_record_key_count"] = len(records)
    plan["unique_selection_count"] = len(plan["selections"])
    return plan


def _summarize_native_result(result: Mapping[str, Any]) -> dict[str, Any]:
    native = result.get("native")
    if not isinstance(native, Mapping):
        native = {}
    issues = native.get("issues", [])
    issue_rows: list[dict[str, Any]] = []
    for issue in issues if isinstance(issues, list) else []:
        if not isinstance(issue, Mapping):
            continue
        fields = issue.get("fields", [])
        issue_rows.append(
            {
                "fields": [
                    {
                        "field": field.get("field"),
                        "kind": field.get("kind"),
                        "evidence_count": field.get("evidence_count"),
                    }
                    for field in fields
                    if isinstance(field, Mapping)
                ],
                "region": issue.get("region"),
            }
        )
    return {
        "status": result.get("status", "invalid_adapter_result"),
        "reason_code": result.get("reason_code"),
        "native_extraction_status": native.get("extraction_status"),
        "native_validation_status": native.get("validation_status"),
        "native_record_count": len(native.get("records", []))
        if isinstance(native.get("records"), list)
        else 0,
        "native_issues": issue_rows,
        "native_extraction_diagnostics": native.get("extraction_diagnostics", []),
        "native_failure": native.get("failure"),
        "source_bindings": result.get("source_bindings", {}),
        "ranking_ties": result.get("ranking_ties", {}),
        "sdk_identity_ref": result.get("sdk_identity_ref"),
        "dom_uniqueness_verified": result.get("dom_uniqueness_verified", False),
        "native_cardinality_scope": result.get("native_cardinality_scope"),
        "semantic_truth_verified": result.get("semantic_truth_verified", False),
    }


def execute_campaign(
    prepared: Mapping[str, Any],
    *,
    go: bool = False,
    validator=None,
    on_start=None,
) -> dict[str, Any]:
    """Run deduplicated native validation only after an explicit GO."""
    if not go:
        raise PermissionError("native Contract campaign requires explicit go=True")
    if validator is None:
        from contract_validation import sdk_identity, validate_selection

        validator = validate_selection
        sdk_snapshot = sdk_identity()
        sdk_ref = hashlib.sha256(_canonical_bytes(sdk_snapshot)).hexdigest()
    else:
        sdk_snapshot = None
        sdk_ref = None

    manifest = {
        **prepared["manifest"],
        "sdk_identity": sdk_snapshot,
        "sdk_identity_ref": sdk_ref,
        "schemas": prepared["schema_configs"],
        "prepared_unique_selections": len(prepared["selections"]),
        "prepared_record_keys": len(prepared["record_links"]),
        "validation_started_before_calls": True,
        "execution_start_unix_ns": time.time_ns(),
    }
    if on_start is not None:
        on_start(manifest)

    validation_by_selection: dict[str, dict[str, Any]] = {}
    validation_cost_by_selection: dict[str, int] = {}
    validation_failures: list[dict[str, Any]] = []
    for selection_id, selection in prepared["selections"].items():
        if selection["selection_errors"]:
            validation_by_selection[selection_id] = {
                "status": "source_binding_failed",
                "reason_code": "selection_preparation_error",
                "selection_errors": selection["selection_errors"],
                "native": None,
                "source_bindings": {},
                "ranking_ties": {},
                "semantic_truth_verified": False,
            }
            continue

        started = time.perf_counter_ns()
        try:
            result = validator(
                prepared["case_documents"][selection["case_id"]],
                selection["document_id"],
                selection["predicted_root_id"],
                selection["selected_candidates"],
                selection["completeness"],
                required_fields=tuple(selection["required_fields"]),
            )
            elapsed = time.perf_counter_ns() - started
            if not isinstance(result, Mapping):
                raise TypeError("Contract validation adapter returned a non-mapping")
            validation_by_selection[selection_id] = _summarize_native_result(result)
            validation_cost_by_selection[selection_id] = elapsed
        except Exception as error:
            elapsed = time.perf_counter_ns() - started
            failure = {
                "selection_id": selection_id,
                "case": selection["case_id"],
                "schema": selection["schema_name"],
                "error_type": type(error).__name__,
                "reason": str(error),
            }
            validation_failures.append(failure)
            validation_by_selection[selection_id] = {
                "status": "native_error",
                "reason_code": "contract_validation_exception",
                "error_type": type(error).__name__,
                "reason": str(error),
                "native": None,
                "source_bindings": {},
                "ranking_ties": {},
                "semantic_truth_verified": False,
            }
            validation_cost_by_selection[selection_id] = elapsed

    # Only after native validation do row correctness values enter any aggregate.
    record_results: list[dict[str, Any]] = []
    grouped: dict[tuple[str, str, str, str], Counter[str]] = defaultdict(Counter)
    record_status_counts: Counter[str] = Counter()
    native_valid_but_wrong: list[dict[str, Any]] = []
    native_issues: list[dict[str, Any]] = []
    source_binding_failures: list[dict[str, Any]] = []
    native_valid_but_wrong_selection_ids: set[str] = set()
    missing_required_issue_count = 0
    optional_missing_count = 0
    zero_root_record_count = 0
    runtime_cost_samples_ns = [value for value in validation_cost_by_selection.values()]
    for link in prepared["record_links"]:
        selection_id = link["selection_id"]
        validation = validation_by_selection[selection_id]
        key = link["record_key"]
        metadata = link["case_metadata"]
        truth = link["truth_after_validation"]
        wrong_fields = [
            field
            for field, values in truth.items()
            if values.get("top1_correct") is False
        ]
        canonical_wrong_fields = [
            field
            for field, values in truth.items()
            if values.get("canonical_top1_correct") is False
        ]
        owner_mismatch = any(
            values.get("owner_correct") is False for values in truth.values()
        )
        is_native_valid = validation["status"] == "native_validated"
        valid_but_wrong = is_native_valid and bool(wrong_fields)
        result_row = {
            "record_key": key,
            "case_metadata": metadata,
            "schema_name": link["schema_name"],
            "selection_id": selection_id,
            "status": validation["status"],
            "native_valid_but_wrong": valid_but_wrong,
            "wrong_fields_after_validation": wrong_fields,
            "canonical_wrong_fields_after_validation": canonical_wrong_fields,
            "owner_mismatch_after_validation": owner_mismatch,
            "native": validation,
            "runtime_cost_ns": validation_cost_by_selection.get(selection_id),
            "ranking_ties": link["ranking_ties"],
            "scorer_failures": link["scorer_failures"],
            "missing_report_fields": link["missing_report_fields"],
            "optional_missing_fields": [
                field
                for field in PRODUCT_FIELDS
                if field not in prepared["schema_configs"][link["schema_name"]]
                and prepared["selections"][selection_id]["selected_candidates"].get(
                    field
                )
                is None
            ],
        }
        record_results.append(result_row)
        record_status_counts[validation["status"]] += 1
        group_key = (
            key["case"],
            metadata.get("variant") or "unknown",
            key["method"],
            link["schema_name"],
        )
        grouped[group_key]["records"] += 1
        grouped[group_key][validation["status"]] += 1
        grouped[group_key]["native_valid_but_wrong"] += int(valid_but_wrong)
        grouped[group_key]["owner_mismatch"] += int(owner_mismatch)
        grouped[group_key]["wrong_field_count"] += len(wrong_fields)
        grouped[group_key]["missing_optional_count"] += len(
            result_row["optional_missing_fields"]
        )
        if valid_but_wrong:
            native_valid_but_wrong_selection_ids.add(selection_id)
            native_valid_but_wrong.append(
                {
                    "record_key": key,
                    "schema_name": link["schema_name"],
                    "selection_id": selection_id,
                    "wrong_fields": wrong_fields,
                    "canonical_wrong_fields": canonical_wrong_fields,
                }
            )
        if validation["status"] == "native_issues":
            missing_required_issue_count += sum(
                1
                for issue in validation.get("native_issues", [])
                for field_issue in issue.get("fields", [])
                if isinstance(field_issue.get("kind"), Mapping)
                and field_issue["kind"].get("kind") == "missing_required"
            )
            native_issues.append(
                {
                    "record_key": key,
                    "schema_name": link["schema_name"],
                    "selection_id": selection_id,
                    "issues": validation["native_issues"],
                }
            )
        if validation["status"] in {
            "source_binding_failed",
            "source_binding_rejected",
        }:
            source_binding_failures.append(
                {
                    "record_key": key,
                    "schema_name": link["schema_name"],
                    "selection_id": selection_id,
                    "reason_code": validation.get("reason_code"),
                    "selection_errors": validation.get("selection_errors"),
                    "source_bindings": validation.get("source_bindings"),
                }
            )
        if prepared["selections"][selection_id]["predicted_root_id"] is None:
            zero_root_record_count += 1
        optional_missing_count += len(result_row["optional_missing_fields"])

    by_case_variant_method = [
        {
            "case": key[0],
            "variant": key[1],
            "method": key[2],
            "schema_name": key[3],
            **dict(counts),
        }
        for key, counts in sorted(grouped.items())
    ]
    status_by_selection = Counter(
        result["status"] for result in validation_by_selection.values()
    )
    return {
        "version": 1,
        "manifest": manifest,
        "unique_selection_count": len(prepared["selections"]),
        "record_key_count": len(prepared["record_links"]),
        "unique_selection_status_counts": dict(status_by_selection),
        "record_status_counts": dict(record_status_counts),
        "native_valid_but_wrong_count": len(native_valid_but_wrong),
        "native_valid_but_wrong_unique_selection_count": len(
            native_valid_but_wrong_selection_ids
        ),
        "native_valid_but_wrong": native_valid_but_wrong,
        "native_issues": native_issues,
        "missing_required_issue_count": missing_required_issue_count,
        "optional_missing_count": optional_missing_count,
        "zero_root_record_count": zero_root_record_count,
        "source_binding_failures": source_binding_failures,
        "validation_failures": validation_failures,
        "fold_errors": prepared["fold_errors"],
        "scorer_failures": prepared["manifest"]["report_failures"],
        "by_case_variant_method": by_case_variant_method,
        "runtime_cost_samples_ns": runtime_cost_samples_ns,
        "record_results": record_results,
    }


def write_campaign_report(path: Path, report: Mapping[str, Any]) -> None:
    "Write a deterministic JSON report, using gzip when the output suffix requests it."
    encoded = json.dumps(
        report, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".gz":
        path.write_bytes(gzip.compress(encoded, mtime=0))
    else:
        path.write_bytes(encoded)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    prepare_parser = subparsers.add_parser(
        "prepare",
        help="fold rows and count deduplicated selections without Contract calls",
    )
    prepare_parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / ".generated/product-retrieval-minilm-v3/report.json",
    )
    prepare_parser.add_argument("--corpus", type=Path)
    prepare_parser.add_argument(
        "--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT
    )
    run_parser = subparsers.add_parser(
        "validate", help="run native Contract checks after explicit owner GO"
    )
    run_parser.add_argument(
        "--report",
        type=Path,
        default=REPO_ROOT / ".generated/product-retrieval-minilm-v3/report.json",
    )
    run_parser.add_argument("--corpus", type=Path)
    run_parser.add_argument(
        "--candidate-limit", type=int, default=DEFAULT_CANDIDATE_LIMIT
    )
    run_parser.add_argument("--output", type=Path, required=True)
    run_parser.add_argument("--go", action="store_true")
    args = parser.parse_args()

    if args.command == "prepare":
        prepared = prepare_campaign(
            args.report, args.corpus, candidate_limit=args.candidate_limit
        )
        print(
            json.dumps(
                {
                    "report_rows": prepared["manifest"]["report_row_count"],
                    "record_key_count": prepared["folded_record_key_count"],
                    "unique_selection_count": prepared["unique_selection_count"],
                    "fold_errors": len(prepared["fold_errors"]),
                    "native_validation": "not run",
                },
                sort_keys=True,
            ),
            flush=True,
        )
        return

    if not args.go:
        parser.error("validate requires --go after owner approval")
    prepared = prepare_campaign(
        args.report, args.corpus, candidate_limit=args.candidate_limit
    )
    manifest_path = args.output.with_suffix(args.output.suffix + ".manifest.json")
    if args.output.exists():
        raise FileExistsError(f"refusing to overwrite {args.output}")
    if manifest_path.exists():
        raise FileExistsError(f"refusing to overwrite {manifest_path}")

    def persist_manifest(manifest):
        write_campaign_report(manifest_path, manifest)

    result = execute_campaign(prepared, go=True, on_start=persist_manifest)
    write_campaign_report(args.output, result)
    print(
        json.dumps(
            {
                "report_rows": prepared["manifest"]["report_row_count"],
                "record_key_count": result["record_key_count"],
                "unique_selection_count": result["unique_selection_count"],
                "status_counts": result["unique_selection_status_counts"],
                "output": str(args.output),
            },
            sort_keys=True,
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
