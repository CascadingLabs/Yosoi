"""Rust serde enum payloads remain typed and lossless in Python result views."""

from typing import Any

import pytest
from pydantic import TypeAdapter, ValidationError

from yosoi.diagnostics import (
    BrowserFailureReason,
    DecodingErrorCode,
    DirectHttpRedirectErrorKind,
    TransportDiagnostic,
    UnknownReason,
    WebArtifactFamily,
)
from yosoi.request import Attempt
from yosoi.request import AttemptDiagnostic as AttemptDiagnostic
from yosoi.request import AttemptFailureKind as AttemptFailureKind
from yosoi.request import Diagnostic as Diagnostic
from yosoi.request import NotStartedReason as NotStartedReason
from yosoi.request import PartialReason as PartialReason
from yosoi.request import ProjectionReason as ProjectionReason
from yosoi.request import UnavailableReason as UnavailableReason
from yosoi.request import UnprojectableReason as UnprojectableReason
from yosoi.search import RequestAttemptSummary
from yosoi.search import SearchAttemptDiagnostic as SearchAttemptDiagnostic


def _round_trip(adapter: TypeAdapter[Any], wire: Any) -> None:
    value = adapter.validate_python(wire)
    assert adapter.dump_python(value, mode="json") == wire


@pytest.mark.parametrize(
    "family",
    [
        "source",
        "source_representation",
        "decoded_source",
        "rendered_dom",
        "accessibility_tree",
        "network",
        "cookies",
        "storage",
        "layout",
        "visual",
        "runtime_diagnostics",
    ],
)
def test_web_artifact_family_values_match_public_rust_enum(family: str) -> None:
    assert TypeAdapter(WebArtifactFamily).validate_python(family) == family


@pytest.mark.parametrize(
    "wire",
    [
        {"kind": "source_family_partial"},
        {"kind": "source_artifact_truncated"},
        {"kind": "classification_from_retained_prefix"},
        {"kind": "decoded_output_truncated"},
        {"kind": "incomplete_terminal_sequence"},
        {"kind": "decoded_source_family_partial"},
        {"kind": "rendered_dom_family_partial"},
        {"kind": "accessibility_tree_family_partial"},
        {"kind": "accessibility_depth_limited"},
        {"kind": "accessibility_node_loss"},
        {"kind": "accessibility_node_loss_unknown"},
        {"kind": "accessibility_byte_loss"},
        {"kind": "accessibility_byte_loss_unknown"},
        {"kind": "browser_artifact_truncated", "family": "runtime_diagnostics"},
    ],
)
def test_partial_reason_payloads_round_trip(wire: dict[str, str]) -> None:
    _round_trip(TypeAdapter(PartialReason), wire)
    _round_trip(TypeAdapter(ProjectionReason), wire)


@pytest.mark.parametrize(
    "wire",
    [
        {"kind": "source_artifact_unavailable"},
        {"kind": "decoded_source_not_retained"},
        {"kind": "decoded_source_payload_unavailable"},
        {"kind": "browser_decoded_source_not_retained"},
        {"kind": "capture_artifact_not_retained", "family": "source"},
        {"kind": "capture_artifact_payload_unavailable", "family": "network"},
        {"kind": "capture_artifact_failed", "family": "cookies"},
        {"kind": "capture_artifact_unavailable", "family": "layout"},
    ],
)
def test_unavailable_reason_payloads_round_trip(wire: dict[str, str]) -> None:
    _round_trip(TypeAdapter(UnavailableReason), wire)
    _round_trip(TypeAdapter(ProjectionReason), wire)


@pytest.mark.parametrize(
    "wire",
    [
        {"kind": "source_facts_unavailable"},
        {"kind": "unknown_source_format", "reason": "empty"},
        {"kind": "unknown_source_format", "reason": "no_strong_signature"},
        {"kind": "unsupported_source_format"},
        {"kind": "ambiguous_source_format"},
        {"kind": "decoded_source_reference_mismatch"},
        {"kind": "unsupported_encoding", "code": "not_classified"},
        {"kind": "undecodable", "code": "invalid_charset"},
        {"kind": "decoding_not_applicable", "code": "artifact_metadata"},
        {"kind": "document_rejected"},
        {"kind": "network_tree_schema_unavailable"},
        {"kind": "browser_document_epoch_unavailable"},
        {"kind": "browser_document_normalization_failed"},
        {"kind": "capture_artifact_not_requested", "family": "visual"},
        {"kind": "capture_artifact_unsupported", "family": "storage"},
    ],
)
def test_unprojectable_reason_payloads_round_trip(wire: dict[str, str]) -> None:
    _round_trip(TypeAdapter(UnprojectableReason), wire)
    _round_trip(TypeAdapter(ProjectionReason), wire)


@pytest.mark.parametrize("value", ["empty", "no_strong_signature"])
def test_unknown_source_reason_vocabulary(value: str) -> None:
    assert TypeAdapter(UnknownReason).validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "not_classified",
        "invalid_charset",
        "conflicting_charset",
        "unsupported_charset",
        "unsupported_utf32",
        "unsupported_json_unicode",
        "invalid_sequence",
        "artifact_metadata",
    ],
)
def test_decoding_error_code_vocabulary(value: str) -> None:
    assert TypeAdapter(DecodingErrorCode).validate_python(value) == value


@pytest.mark.parametrize(
    "value",
    [
        "launch",
        "connection",
        "navigation",
        "timeout",
        "display_unavailable",
        "environment_mismatch",
        "profile_unavailable",
        "unavailable",
        "capacity_exhausted",
        "closed",
        "renderer_crashed",
        "unsupported_configuration",
    ],
)
def test_browser_failure_reason_vocabulary(value: str) -> None:
    assert TypeAdapter(BrowserFailureReason).validate_python(value) == value


@pytest.mark.parametrize(
    "wire",
    [
        {"kind": "dns"},
        {"kind": "connect"},
        {"kind": "tls"},
        {"kind": "timeout"},
        {"kind": "protocol"},
        {"kind": "client"},
        {"kind": "cancelled"},
        {"kind": "unsupported_profile"},
        {"kind": "unsupported_session"},
        {"kind": "unsupported_redirects"},
        {"kind": "redirect", "value": "missing_location"},
    ],
)
def test_direct_http_transport_payloads_round_trip(wire: dict[str, str]) -> None:
    _round_trip(TypeAdapter(TransportDiagnostic), wire)


@pytest.mark.parametrize(
    "value",
    [
        "missing_location",
        "malformed_location",
        "credentials_not_allowed",
        "unsupported_scheme",
        "target_refused",
        "loop",
        "hop_limit",
    ],
)
def test_redirect_diagnostic_vocabulary(value: str) -> None:
    assert TypeAdapter(DirectHttpRedirectErrorKind).validate_python(value) == value


@pytest.mark.parametrize(
    "wire",
    [
        {"kind": "missing_execution_context"},
        {"kind": "policy_resolution_failed"},
        {
            "kind": "direct_http_transport",
            "value": {"kind": "redirect", "value": "hop_limit"},
        },
        {"kind": "direct_http_body_failed"},
        {"kind": "direct_http_finalization_failed"},
        {"kind": "browser_cancelled"},
        {"kind": "browser_cancelled_cleanup_failed"},
        {"kind": "browser_cleanup_failed"},
        {"kind": "browser_capture_failed"},
        {"kind": "browser_failure", "value": "renderer_crashed"},
        {"kind": "browser_finalization_failed"},
        {"kind": "browser_feature_disabled"},
        {"kind": "projection_failed"},
    ],
)
def test_request_diagnostic_payloads_round_trip(wire: dict[str, Any]) -> None:
    _round_trip(TypeAdapter(AttemptDiagnostic), wire)
    _round_trip(TypeAdapter(Diagnostic), wire)


@pytest.mark.parametrize(
    "value",
    [
        "missing_execution_context",
        "policy_resolution",
        "capture_execution",
        "projection",
    ],
)
def test_attempt_failure_kind_vocabulary(value: str) -> None:
    assert TypeAdapter(AttemptFailureKind).validate_python(value) == value


def test_not_started_reason_vocabulary() -> None:
    assert TypeAdapter(NotStartedReason).validate_python("cancelled") == "cancelled"


@pytest.mark.parametrize(
    "value",
    [
        "missing_execution_context",
        "policy_resolution_failed",
        "direct_http_transport",
        "direct_http_body_failed",
        "direct_http_finalization_failed",
        "browser_cancelled",
        "browser_cancelled_cleanup_failed",
        "browser_cleanup_failed",
        "browser_capture_failed",
        "browser_finalization_failed",
        "browser_feature_disabled",
        "projection_failed",
    ],
)
def test_search_attempt_unit_diagnostics_round_trip(value: str) -> None:
    _round_trip(TypeAdapter(SearchAttemptDiagnostic), value)


@pytest.mark.parametrize(
    "reason",
    [
        "launch",
        "connection",
        "navigation",
        "timeout",
        "display_unavailable",
        "environment_mismatch",
        "profile_unavailable",
        "unavailable",
        "capacity_exhausted",
        "closed",
        "renderer_crashed",
        "unsupported_configuration",
    ],
)
def test_search_browser_failure_diagnostic_round_trip(reason: str) -> None:
    _round_trip(TypeAdapter(SearchAttemptDiagnostic), {"browser_failure": reason})


def test_request_and_search_attempt_result_views_decode_native_shapes() -> None:
    attempt = Attempt.model_validate(
        {
            "capture_id": "00000000-0000-4000-8000-000000000001",
            "acquisition": {"kind": "direct_http"},
            "authored_selection": "exact",
            "requested_target": "https://example.org/",
            "http_status": None,
            "state": "failed",
            "failure_kind": "capture_execution",
            "not_started_reason": None,
            "diagnostic": {
                "kind": "direct_http_transport",
                "value": {"kind": "redirect", "value": "hop_limit"},
            },
            "documents": [],
        }
    )
    assert attempt.failure_kind == "capture_execution"
    assert attempt.diagnostic is not None
    assert attempt.diagnostic.model_dump(mode="json") == {
        "kind": "direct_http_transport",
        "value": {"kind": "redirect", "value": "hop_limit"},
    }

    summary = RequestAttemptSummary.model_validate(
        {
            "request_id": "00000000-0000-4000-8000-000000000002",
            "capture_id": "00000000-0000-4000-8000-000000000003",
            "acquisition": {"kind": "direct_http"},
            "http_status": None,
            "source_bytes": None,
            "diagnostic": {"browser_failure": "timeout"},
            "terminal": "failed",
        }
    )
    assert summary.diagnostic is not None
    assert summary.model_dump(mode="json")["diagnostic"] == {
        "browser_failure": "timeout"
    }


def test_closed_diagnostic_models_reject_missing_or_unknown_payloads() -> None:
    with pytest.raises(ValidationError):
        TypeAdapter(ProjectionReason).validate_python(
            {"kind": "browser_artifact_truncated"}
        )
    with pytest.raises(ValidationError):
        TypeAdapter(Diagnostic).validate_python(
            {"kind": "direct_http_transport", "value": {"kind": "redirect"}}
        )
    with pytest.raises(ValidationError):
        TypeAdapter(SearchAttemptDiagnostic).validate_python(
            {"browser_failure": "secret_provider_message"}
        )
