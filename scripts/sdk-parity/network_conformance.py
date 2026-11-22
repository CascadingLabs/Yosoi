"""Typed offline network fixture validation and pinned declaration attribution."""

from __future__ import annotations

import hashlib
from typing import Any

from image_surface_conformance import EVIDENCE_KIND as EVIDENCE_KIND
from image_surface_conformance import RESULT_KIND as RESULT_KIND
from image_surface_conformance import comparison as _image_comparison
from image_surface_conformance import evidence_cases as _image_evidence

FIXTURE_KIND = "yosoi-network-conformance-fixtures"
CASE_PATHS = {
    "policy-defaults": "yosoi::surface::NetworkObservationPolicy",
    "policy-retention": "yosoi::surface::NetworkObservationPolicy::retention",
    "typed-window": "yosoi::surface::NetworkWindow::to_document",
    "ordinary-json": "yosoi::Surface::new",
    **dict.fromkeys(
        ("payload-body-html", "payload-body-json", "payload-body-file"),
        "yosoi::surface::NetworkPayload::from_outcome",
    ),
    "portable-outcome": "yosoi::surface::Outcome::source_document",
}
ERROR_PATHS = {
    "ordinary-json-rejected": "yosoi::surface::NetworkWindow::from_document",
    **dict.fromkeys(
        ("bad-origin", "bad-header", "bad-method", "event-bound"),
        "yosoi::surface::NetworkObservationPolicy::validate",
    ),
    **dict.fromkeys(
        ("window-interval", "duplicate-payload", "empty-request-id"),
        "yosoi::surface::NetworkWindow::validate",
    ),
    **dict.fromkeys(
        ("foreign-membership", "payload-byte-bound", "missing-body"),
        "yosoi::surface::NetworkPayload::from_outcome",
    ),
    "document-byte-bound": "yosoi::Surface::with_limits",
}


def validate_fixture_set(value: Any) -> dict[str, Any]:
    """Require actual linked bodies and all declared positive/negative journeys."""
    if (
        not isinstance(value, dict)
        or type(value.get("schemaVersion")) is not int
        or value.get("schemaVersion") != 1
        or value.get("kind") != FIXTURE_KIND
    ):
        raise ValueError("unsupported Rust network conformance output")
    for field, expected in (("cases", CASE_PATHS), ("errorCases", ERROR_PATHS)):
        rows = value.get(field)
        if not isinstance(rows, list) or any(not isinstance(row, dict) for row in rows):
            raise ValueError("invalid network fixture cases")
        names = [row.get("name") for row in rows]
        if len(names) != len(set(names)) or set(names) != set(expected):
            raise ValueError("network fixture names differ from the contract")
        for row in rows:
            if (
                row.get("rustPath") != expected[row["name"]]
                or not isinstance(row.get("input"), dict)
                or not isinstance(row.get("rust"), dict)
            ):
                raise ValueError(
                    "network fixture does not address its declared operation"
                )
            if field == "errorCases" and (
                row["rust"] != {"rejected": True}
                or not isinstance(row.get("rustFailure"), dict)
                or row["rustFailure"].get("rust_type") != "yosoi::surface::SurfaceError"
                or not isinstance(row["rustFailure"].get("details"), dict)
                or not isinstance(row["rustFailure"].get("message"), str)
                or row["rustFailure"].get("variant")
                not in {"Invalid", "Limit", "Unknown"}
            ):
                raise ValueError("network error lacks an actual typed Rust rejection")
    inputs = value.get("input")
    if not isinstance(inputs, dict) or not isinstance(inputs.get("bodies"), list):
        raise ValueError("network fixtures lack actual body inputs")
    bodies = {
        body.get("id"): body for body in inputs["bodies"] if isinstance(body, dict)
    }
    if set(bodies) != {"body-html", "body-json", "body-file"}:
        raise ValueError("network fixtures require HTML, JSON and FileDocument bodies")
    window = inputs.get("window", {})
    if (
        window.get("schema") != "yosoi.network.v1"
        or window.get("coverage", {}).get("complete") is not False
    ):
        raise ValueError(
            "network fixture must explicitly preserve partial network coverage"
        )
    refs = window.get("payloads", [])
    if len(refs) != len(bodies) or {ref.get("id") for ref in refs} != set(bodies):
        raise ValueError("network response links differ from retained bodies")
    for ref in refs:
        body = bodies[ref["id"]]
        raw = body.get("bytes")
        if not isinstance(raw, list) or any(
            type(byte) is not int or not 0 <= byte <= 255 for byte in raw
        ):
            raise ValueError("network body requires actual octets")
        if (
            ref.get("document_id") != body["id"]
            or ref.get("retained_bytes") != len(raw)
            or ref.get("sha256") != hashlib.sha256(bytes(raw)).hexdigest()
        ):
            raise ValueError(
                "network body bytes/digest/identity disagree with their link"
            )
        if not any(
            event.get("sequence") == ref.get("response_sequence")
            and event.get("request_id") == ref.get("request_id")
            and event.get("hop") == ref.get("hop")
            and event.get("kind", {}).get("kind") == "response_received"
            for event in window.get("events", [])
        ):
            raise ValueError("network payload does not select its exact response/hop")
        expected_profile = {"html": "html5", "json": "json_rfc8259"}.get(
            ref.get("document_kind")
        )
        if expected_profile is not None and (
            body.get("class") != "Document"
            or body.get("profile", {}).get("schema") != expected_profile
        ):
            raise ValueError(
                "network body projection profile differs from its response link"
            )
        if ref.get("document_kind") == "file" and (
            body.get("class") != "BinaryDocument" or body.get("sha256") != ref["sha256"]
        ):
            raise ValueError(
                "network file body class or digest differs from its response link"
            )
    retention = window.get("retention", {})
    if (
        retention.get("retained_header_names") != ["x-request-id"]
        or retention.get("retain_url_query") is not False
    ):
        raise ValueError(
            "network policy must actually filter sensitive allowlist names"
        )
    if (
        not window.get("in_flight")
        or not window.get("in_flight_at_start")
        or not window.get("gaps")
        or not any(
            event.get("kind", {}).get("kind") == "redirect"
            for event in window.get("events", [])
        )
    ):
        raise ValueError("network fixture lost redirects, boundaries or gap metadata")
    results = {row["name"]: row["rust"] for row in value["cases"]}
    if results["policy-retention"] != retention:
        raise ValueError(
            "network retention result differs from the typed window policy"
        )
    if (
        results["policy-defaults"].get("retain_bodies") is not False
        or results["policy-defaults"].get("retain_url_query") is not False
    ):
        raise ValueError("network policy defaults must preserve opt-in privacy")
    typed = results["typed-window"]
    if (
        typed.get("window") != window
        or typed.get("document", {}).get("profile", {}).get("schema")
        != "yosoi_network_observation_v1"
        or typed.get("surface", {}).get("coverage", {}).get("complete") is not False
    ):
        raise ValueError(
            "typed network result lost its explicit profile or partial coverage"
        )
    for ref in refs:
        observed = results[f"payload-{ref['id']}"]
        if (
            observed.get("class") != "NetworkPayload"
            or observed.get("reference") != ref
            or observed.get("value") != bodies[ref["id"]]
            or observed.get("bytes") != bodies[ref["id"]]["bytes"]
        ):
            raise ValueError(
                "network payload result lacks the actual linked body value"
            )
    portable = results["portable-outcome"]
    if (
        portable.get("class") != "Outcome"
        or set(portable.get("source_keys", {}).get("source_keys", []))
        != {"network-window", *bodies}
        or portable.get("payloads") != [results[f"payload-{ref['id']}"] for ref in refs]
    ):
        raise ValueError("portable network Outcome lost its exact dependency closure")
    ordinary = results["ordinary-json"]
    if (
        ordinary.get("network") is not False
        or ordinary.get("surface", {}).get("coverage", {}).get("complete") is not True
    ):
        raise ValueError("ordinary JSON must remain ordinary complete JSON evidence")
    return value


def comparison(
    case: dict[str, Any], observed: Any, arguments: dict[str, Any]
) -> dict[str, Any]:
    """Digest actual network values and the arguments observed by each SDK."""
    row = _image_comparison(case, observed, arguments)
    for check in row["comparisons"]:
        check["name"] = check["name"].replace("image:", "network:", 1)
    return row


def evidence_cases(
    comparisons: list[dict[str, Any]], rust: dict[str, Any], ledger: dict[str, Any]
) -> list[dict[str, Any]]:
    """Check source aliases and actual arguments for executed network APIs."""
    rows = _image_evidence(comparisons, rust, ledger)
    for row in rows:
        row["testId"] = row["testId"].replace("image-surface:", "network:", 1)
    return rows
