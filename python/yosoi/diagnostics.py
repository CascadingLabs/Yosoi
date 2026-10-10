"""Typed, payload-preserving views of Rust request and projection diagnostics."""

from __future__ import annotations

from typing import Annotated, Literal

from pydantic import Field

from ._models import ImmutableModel

WebArtifactFamily = Literal[
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
]
UnknownReason = Literal["empty", "no_strong_signature"]
DecodingErrorCode = Literal[
    "not_classified",
    "invalid_charset",
    "conflicting_charset",
    "unsupported_charset",
    "unsupported_utf32",
    "unsupported_json_unicode",
    "invalid_sequence",
    "artifact_metadata",
]
BrowserFailureReason = Literal[
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
]
DirectHttpRedirectErrorKind = Literal[
    "missing_location",
    "malformed_location",
    "credentials_not_allowed",
    "unsupported_scheme",
    "target_refused",
    "loop",
    "hop_limit",
]


class _PartialReasonUnit(ImmutableModel):
    kind: Literal[
        "source_family_partial",
        "source_artifact_truncated",
        "classification_from_retained_prefix",
        "decoded_output_truncated",
        "incomplete_terminal_sequence",
        "decoded_source_family_partial",
        "rendered_dom_family_partial",
        "accessibility_tree_family_partial",
        "accessibility_depth_limited",
        "accessibility_node_loss",
        "accessibility_node_loss_unknown",
        "accessibility_byte_loss",
        "accessibility_byte_loss_unknown",
    ]


class _BrowserArtifactTruncated(ImmutableModel):
    kind: Literal["browser_artifact_truncated"]
    family: WebArtifactFamily


type PartialReason = Annotated[
    _PartialReasonUnit | _BrowserArtifactTruncated, Field(discriminator="kind")
]


class _UnavailableReasonUnit(ImmutableModel):
    kind: Literal[
        "source_artifact_unavailable",
        "decoded_source_not_retained",
        "decoded_source_payload_unavailable",
        "browser_decoded_source_not_retained",
    ]


class _UnavailableArtifactReason(ImmutableModel):
    kind: Literal[
        "capture_artifact_not_retained",
        "capture_artifact_payload_unavailable",
        "capture_artifact_failed",
        "capture_artifact_unavailable",
    ]
    family: WebArtifactFamily


type UnavailableReason = Annotated[
    _UnavailableReasonUnit | _UnavailableArtifactReason,
    Field(discriminator="kind"),
]


class _UnprojectableReasonUnit(ImmutableModel):
    kind: Literal[
        "source_facts_unavailable",
        "unsupported_source_format",
        "ambiguous_source_format",
        "decoded_source_reference_mismatch",
        "document_rejected",
        "network_tree_schema_unavailable",
        "browser_document_epoch_unavailable",
        "browser_document_normalization_failed",
    ]


class _UnknownSourceFormat(ImmutableModel):
    kind: Literal["unknown_source_format"]
    reason: UnknownReason


class _DecodingReason(ImmutableModel):
    kind: Literal["unsupported_encoding", "undecodable", "decoding_not_applicable"]
    code: DecodingErrorCode


class _CaptureArtifactUnprojectable(ImmutableModel):
    kind: Literal["capture_artifact_not_requested", "capture_artifact_unsupported"]
    family: WebArtifactFamily


type UnprojectableReason = Annotated[
    _UnprojectableReasonUnit
    | _UnknownSourceFormat
    | _DecodingReason
    | _CaptureArtifactUnprojectable,
    Field(discriminator="kind"),
]


type ProjectionReason = Annotated[
    PartialReason | UnavailableReason | UnprojectableReason,
    Field(discriminator="kind"),
]


class _DirectHttpTransportUnit(ImmutableModel):
    kind: Literal[
        "dns",
        "connect",
        "tls",
        "timeout",
        "protocol",
        "client",
        "cancelled",
        "unsupported_profile",
        "unsupported_session",
        "unsupported_redirects",
    ]


class _DirectHttpRedirect(ImmutableModel):
    kind: Literal["redirect"]
    value: DirectHttpRedirectErrorKind


type TransportDiagnostic = Annotated[
    _DirectHttpTransportUnit | _DirectHttpRedirect, Field(discriminator="kind")
]


class _RequestDiagnosticUnit(ImmutableModel):
    kind: Literal[
        "missing_execution_context",
        "policy_resolution_failed",
        "direct_http_body_failed",
        "direct_http_finalization_failed",
        "browser_cancelled",
        "browser_cancelled_cleanup_failed",
        "browser_cleanup_failed",
        "browser_capture_failed",
        "browser_finalization_failed",
        "browser_feature_disabled",
        "projection_failed",
    ]


class _DirectHttpTransportDiagnostic(ImmutableModel):
    kind: Literal["direct_http_transport"]
    value: TransportDiagnostic


class _BrowserFailureDiagnostic(ImmutableModel):
    kind: Literal["browser_failure"]
    value: BrowserFailureReason


type Diagnostic = Annotated[
    _RequestDiagnosticUnit | _DirectHttpTransportDiagnostic | _BrowserFailureDiagnostic,
    Field(discriminator="kind"),
]
type AttemptDiagnostic = Diagnostic


AttemptFailureKind = Literal[
    "missing_execution_context",
    "policy_resolution",
    "capture_execution",
    "projection",
]
NotStartedReason = Literal["cancelled"]


class _SearchBrowserFailure(ImmutableModel):
    browser_failure: BrowserFailureReason


type SearchAttemptDiagnostic = (
    Literal[
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
    ]
    | _SearchBrowserFailure
)
