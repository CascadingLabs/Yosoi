//! Emit real public SDK serde values for Python diagnostic parity fixtures.

use std::{
    error::Error,
    io::{self, Write},
};

use serde::Serialize;
use serde_json::{Value, json};
use yosoi::{
    request::{
        AttemptDiagnostic, AttemptFailureKind, BrowserFailureReason, DecodingErrorCode,
        DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind, NotStartedReason, PartialReason,
        UnavailableReason, UnknownReason, UnprojectableReason, WebArtifactFamily,
    },
    search::SearchAttemptDiagnostic,
};

fn record<T: Serialize>(
    output: &mut Vec<Value>,
    rust_type: &str,
    variant: &str,
    value: &T,
) -> Result<(), serde_json::Error> {
    output.push(json!({
        "rust_type": rust_type,
        "variant": variant,
        "value": serde_json::to_value(value)?,
    }));
    Ok(())
}

fn main() -> Result<(), Box<dyn Error>> {
    let mut output = Vec::new();
    use yosoi::map::Rejection;
    for (name, rejection) in [
        ("InvalidUrl", Rejection::InvalidUrl),
        ("UnsupportedScheme", Rejection::UnsupportedScheme),
        ("Credentials", Rejection::Credentials),
        ("HostScope", Rejection::HostScope),
        ("OriginScope", Rejection::OriginScope),
        ("PathScope", Rejection::PathScope),
        ("Filtered", Rejection::Filtered),
        ("UrlLength", Rejection::UrlLength),
        ("InvalidHost", Rejection::InvalidHost),
        ("UnsupportedDomainScope", Rejection::UnsupportedDomainScope),
        ("HostnameLength", Rejection::HostnameLength),
    ] {
        output.push(json!({
            "rust_type": "Rejection", "variant": name,
            "value": serde_json::to_value(rejection)?, "message": rejection.to_string(),
        }));
    }

    for (name, value) in [
        ("Source", WebArtifactFamily::Source),
        (
            "SourceRepresentation",
            WebArtifactFamily::SourceRepresentation,
        ),
        ("DecodedSource", WebArtifactFamily::DecodedSource),
        ("RenderedDom", WebArtifactFamily::RenderedDom),
        ("AccessibilityTree", WebArtifactFamily::AccessibilityTree),
        ("Network", WebArtifactFamily::Network),
        ("Cookies", WebArtifactFamily::Cookies),
        ("Storage", WebArtifactFamily::Storage),
        ("Layout", WebArtifactFamily::Layout),
        ("Visual", WebArtifactFamily::Visual),
        ("RuntimeDiagnostics", WebArtifactFamily::RuntimeDiagnostics),
    ] {
        record(&mut output, "WebArtifactFamily", name, &value)?;
    }
    for (name, value) in [
        ("Empty", UnknownReason::Empty),
        ("NoStrongSignature", UnknownReason::NoStrongSignature),
    ] {
        record(&mut output, "UnknownReason", name, &value)?;
    }
    for (name, value) in [
        ("NotClassified", DecodingErrorCode::NotClassified),
        ("InvalidCharset", DecodingErrorCode::InvalidCharset),
        ("ConflictingCharset", DecodingErrorCode::ConflictingCharset),
        ("UnsupportedCharset", DecodingErrorCode::UnsupportedCharset),
        ("UnsupportedUtf32", DecodingErrorCode::UnsupportedUtf32),
        (
            "UnsupportedJsonUnicode",
            DecodingErrorCode::UnsupportedJsonUnicode,
        ),
        ("InvalidSequence", DecodingErrorCode::InvalidSequence),
        ("ArtifactMetadata", DecodingErrorCode::ArtifactMetadata),
    ] {
        record(&mut output, "DecodingErrorCode", name, &value)?;
    }
    for (name, value) in [
        ("Launch", BrowserFailureReason::Launch),
        ("Connection", BrowserFailureReason::Connection),
        ("Navigation", BrowserFailureReason::Navigation),
        ("Timeout", BrowserFailureReason::Timeout),
        (
            "DisplayUnavailable",
            BrowserFailureReason::DisplayUnavailable,
        ),
        (
            "EnvironmentMismatch",
            BrowserFailureReason::EnvironmentMismatch,
        ),
        (
            "ProfileUnavailable",
            BrowserFailureReason::ProfileUnavailable,
        ),
        ("Unavailable", BrowserFailureReason::Unavailable),
        ("CapacityExhausted", BrowserFailureReason::CapacityExhausted),
        ("Closed", BrowserFailureReason::Closed),
        ("RendererCrashed", BrowserFailureReason::RendererCrashed),
        (
            "UnsupportedConfiguration",
            BrowserFailureReason::UnsupportedConfiguration,
        ),
    ] {
        record(&mut output, "BrowserFailureReason", name, &value)?;
    }
    for (name, value) in [
        (
            "MissingLocation",
            DirectHttpRedirectErrorKind::MissingLocation,
        ),
        (
            "MalformedLocation",
            DirectHttpRedirectErrorKind::MalformedLocation,
        ),
        (
            "CredentialsNotAllowed",
            DirectHttpRedirectErrorKind::CredentialsNotAllowed,
        ),
        (
            "UnsupportedScheme",
            DirectHttpRedirectErrorKind::UnsupportedScheme,
        ),
        ("TargetRefused", DirectHttpRedirectErrorKind::TargetRefused),
        ("Loop", DirectHttpRedirectErrorKind::Loop),
        ("HopLimit", DirectHttpRedirectErrorKind::HopLimit),
    ] {
        record(&mut output, "DirectHttpRedirectErrorKind", name, &value)?;
    }

    for (name, value) in [
        ("SourceFamilyPartial", PartialReason::SourceFamilyPartial),
        (
            "SourceArtifactTruncated",
            PartialReason::SourceArtifactTruncated,
        ),
        (
            "ClassificationFromRetainedPrefix",
            PartialReason::ClassificationFromRetainedPrefix,
        ),
        (
            "DecodedOutputTruncated",
            PartialReason::DecodedOutputTruncated,
        ),
        (
            "IncompleteTerminalSequence",
            PartialReason::IncompleteTerminalSequence,
        ),
        (
            "DecodedSourceFamilyPartial",
            PartialReason::DecodedSourceFamilyPartial,
        ),
        (
            "RenderedDomFamilyPartial",
            PartialReason::RenderedDomFamilyPartial,
        ),
        (
            "AccessibilityTreeFamilyPartial",
            PartialReason::AccessibilityTreeFamilyPartial,
        ),
        (
            "AccessibilityDepthLimited",
            PartialReason::AccessibilityDepthLimited,
        ),
        (
            "AccessibilityNodeLoss",
            PartialReason::AccessibilityNodeLoss,
        ),
        (
            "AccessibilityNodeLossUnknown",
            PartialReason::AccessibilityNodeLossUnknown,
        ),
        (
            "AccessibilityByteLoss",
            PartialReason::AccessibilityByteLoss,
        ),
        (
            "AccessibilityByteLossUnknown",
            PartialReason::AccessibilityByteLossUnknown,
        ),
        (
            "BrowserArtifactTruncated",
            PartialReason::BrowserArtifactTruncated {
                family: WebArtifactFamily::RuntimeDiagnostics,
            },
        ),
    ] {
        record(&mut output, "PartialReason", name, &value)?;
    }
    for (name, value) in [
        (
            "SourceArtifactUnavailable",
            UnavailableReason::SourceArtifactUnavailable,
        ),
        (
            "DecodedSourceNotRetained",
            UnavailableReason::DecodedSourceNotRetained,
        ),
        (
            "DecodedSourcePayloadUnavailable",
            UnavailableReason::DecodedSourcePayloadUnavailable,
        ),
        (
            "BrowserDecodedSourceNotRetained",
            UnavailableReason::BrowserDecodedSourceNotRetained,
        ),
        (
            "CaptureArtifactNotRetained",
            UnavailableReason::CaptureArtifactNotRetained {
                family: WebArtifactFamily::Source,
            },
        ),
        (
            "CaptureArtifactPayloadUnavailable",
            UnavailableReason::CaptureArtifactPayloadUnavailable {
                family: WebArtifactFamily::DecodedSource,
            },
        ),
        (
            "CaptureArtifactFailed",
            UnavailableReason::CaptureArtifactFailed {
                family: WebArtifactFamily::Network,
            },
        ),
        (
            "CaptureArtifactUnavailable",
            UnavailableReason::CaptureArtifactUnavailable {
                family: WebArtifactFamily::Cookies,
            },
        ),
    ] {
        record(&mut output, "UnavailableReason", name, &value)?;
    }
    for (name, value) in [
        (
            "SourceFactsUnavailable",
            UnprojectableReason::SourceFactsUnavailable,
        ),
        (
            "UnknownSourceFormatEmpty",
            UnprojectableReason::UnknownSourceFormat {
                reason: UnknownReason::Empty,
            },
        ),
        (
            "UnknownSourceFormatNoStrongSignature",
            UnprojectableReason::UnknownSourceFormat {
                reason: UnknownReason::NoStrongSignature,
            },
        ),
        (
            "UnsupportedSourceFormat",
            UnprojectableReason::UnsupportedSourceFormat,
        ),
        (
            "AmbiguousSourceFormat",
            UnprojectableReason::AmbiguousSourceFormat,
        ),
        (
            "DecodedSourceReferenceMismatch",
            UnprojectableReason::DecodedSourceReferenceMismatch,
        ),
        (
            "UnsupportedEncodingNotClassified",
            UnprojectableReason::UnsupportedEncoding {
                code: DecodingErrorCode::NotClassified,
            },
        ),
        (
            "UndecodableInvalidCharset",
            UnprojectableReason::Undecodable {
                code: DecodingErrorCode::InvalidCharset,
            },
        ),
        (
            "DecodingNotApplicableArtifactMetadata",
            UnprojectableReason::DecodingNotApplicable {
                code: DecodingErrorCode::ArtifactMetadata,
            },
        ),
        ("DocumentRejected", UnprojectableReason::DocumentRejected),
        (
            "NetworkTreeSchemaUnavailable",
            UnprojectableReason::NetworkTreeSchemaUnavailable,
        ),
        (
            "BrowserDocumentEpochUnavailable",
            UnprojectableReason::BrowserDocumentEpochUnavailable,
        ),
        (
            "BrowserDocumentNormalizationFailed",
            UnprojectableReason::BrowserDocumentNormalizationFailed,
        ),
        (
            "CaptureArtifactNotRequested",
            UnprojectableReason::CaptureArtifactNotRequested {
                family: WebArtifactFamily::Visual,
            },
        ),
        (
            "CaptureArtifactUnsupported",
            UnprojectableReason::CaptureArtifactUnsupported {
                family: WebArtifactFamily::Storage,
            },
        ),
    ] {
        record(&mut output, "UnprojectableReason", name, &value)?;
    }

    for (name, value) in [
        (
            "MissingExecutionContext",
            AttemptFailureKind::MissingExecutionContext,
        ),
        ("PolicyResolution", AttemptFailureKind::PolicyResolution),
        ("CaptureExecution", AttemptFailureKind::CaptureExecution),
        ("Projection", AttemptFailureKind::Projection),
    ] {
        record(&mut output, "AttemptFailureKind", name, &value)?;
    }
    for (name, value) in [
        ("Dns", DirectHttpTransportErrorKind::Dns),
        ("Connect", DirectHttpTransportErrorKind::Connect),
        ("Tls", DirectHttpTransportErrorKind::Tls),
        ("Timeout", DirectHttpTransportErrorKind::Timeout),
        ("Protocol", DirectHttpTransportErrorKind::Protocol),
        ("Client", DirectHttpTransportErrorKind::Client),
        ("Cancelled", DirectHttpTransportErrorKind::Cancelled),
        (
            "UnsupportedProfile",
            DirectHttpTransportErrorKind::UnsupportedProfile,
        ),
        (
            "UnsupportedSession",
            DirectHttpTransportErrorKind::UnsupportedSession,
        ),
        (
            "UnsupportedRedirects",
            DirectHttpTransportErrorKind::UnsupportedRedirects,
        ),
        (
            "RedirectMissingLocation",
            DirectHttpTransportErrorKind::Redirect(DirectHttpRedirectErrorKind::MissingLocation),
        ),
        (
            "RedirectHopLimit",
            DirectHttpTransportErrorKind::Redirect(DirectHttpRedirectErrorKind::HopLimit),
        ),
    ] {
        record(&mut output, "DirectHttpTransportErrorKind", name, &value)?;
    }
    for (name, value) in [
        (
            "MissingExecutionContext",
            AttemptDiagnostic::MissingExecutionContext,
        ),
        (
            "PolicyResolutionFailed",
            AttemptDiagnostic::PolicyResolutionFailed,
        ),
        (
            "DirectHttpTransportRedirect",
            AttemptDiagnostic::DirectHttpTransport(DirectHttpTransportErrorKind::Redirect(
                DirectHttpRedirectErrorKind::HopLimit,
            )),
        ),
        (
            "DirectHttpBodyFailed",
            AttemptDiagnostic::DirectHttpBodyFailed,
        ),
        (
            "DirectHttpFinalizationFailed",
            AttemptDiagnostic::DirectHttpFinalizationFailed,
        ),
        ("BrowserCancelled", AttemptDiagnostic::BrowserCancelled),
        (
            "BrowserCancelledCleanupFailed",
            AttemptDiagnostic::BrowserCancelledCleanupFailed,
        ),
        (
            "BrowserCleanupFailed",
            AttemptDiagnostic::BrowserCleanupFailed,
        ),
        (
            "BrowserCaptureFailed",
            AttemptDiagnostic::BrowserCaptureFailed,
        ),
        (
            "BrowserFailure",
            AttemptDiagnostic::BrowserFailure(BrowserFailureReason::RendererCrashed),
        ),
        (
            "BrowserFinalizationFailed",
            AttemptDiagnostic::BrowserFinalizationFailed,
        ),
        (
            "BrowserFeatureDisabled",
            AttemptDiagnostic::BrowserFeatureDisabled,
        ),
        ("ProjectionFailed", AttemptDiagnostic::ProjectionFailed),
    ] {
        record(&mut output, "AttemptDiagnostic", name, &value)?;
    }
    record(
        &mut output,
        "NotStartedReason",
        "Cancelled",
        &NotStartedReason::Cancelled,
    )?;

    for (name, value) in [
        (
            "MissingExecutionContext",
            SearchAttemptDiagnostic::MissingExecutionContext,
        ),
        (
            "PolicyResolutionFailed",
            SearchAttemptDiagnostic::PolicyResolutionFailed,
        ),
        (
            "DirectHttpTransport",
            SearchAttemptDiagnostic::DirectHttpTransport,
        ),
        (
            "DirectHttpBodyFailed",
            SearchAttemptDiagnostic::DirectHttpBodyFailed,
        ),
        (
            "DirectHttpFinalizationFailed",
            SearchAttemptDiagnostic::DirectHttpFinalizationFailed,
        ),
        (
            "BrowserCancelled",
            SearchAttemptDiagnostic::BrowserCancelled,
        ),
        (
            "BrowserCancelledCleanupFailed",
            SearchAttemptDiagnostic::BrowserCancelledCleanupFailed,
        ),
        (
            "BrowserCleanupFailed",
            SearchAttemptDiagnostic::BrowserCleanupFailed,
        ),
        (
            "BrowserCaptureFailed",
            SearchAttemptDiagnostic::BrowserCaptureFailed,
        ),
        (
            "BrowserFailure",
            SearchAttemptDiagnostic::BrowserFailure(BrowserFailureReason::RendererCrashed),
        ),
        (
            "BrowserFinalizationFailed",
            SearchAttemptDiagnostic::BrowserFinalizationFailed,
        ),
        (
            "BrowserFeatureDisabled",
            SearchAttemptDiagnostic::BrowserFeatureDisabled,
        ),
        (
            "ProjectionFailed",
            SearchAttemptDiagnostic::ProjectionFailed,
        ),
    ] {
        record(&mut output, "SearchAttemptDiagnostic", name, &value)?;
    }

    let bytes = serde_json::to_vec_pretty(&output)?;
    let mut stdout = io::stdout().lock();
    stdout.write_all(&bytes)?;
    stdout.write_all(b"\n")?;
    Ok(())
}
