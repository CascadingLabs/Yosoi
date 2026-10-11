use crate::internal::archive::{
    ArchivedDocumentInput, RequestBrowserDocumentObservation, RequestDocumentOutcome,
    RequestDocumentPartialReason, RequestDocumentRecord, RequestDocumentUnavailableReason,
    RequestDocumentUnprojectableReason, RequestRunRecordError,
};

use crate::internal::engine::{
    DocumentOutcome, PartialReason, UnavailableReason, UnprojectableReason, WebArtifactRef,
};

use super::super::AttemptDocumentOutcome;

pub(super) fn records(
    documents: &[AttemptDocumentOutcome],
) -> Result<Vec<RequestDocumentRecord>, RequestRunRecordError> {
    documents.iter().map(record).collect()
}

fn record(value: &AttemptDocumentOutcome) -> Result<RequestDocumentRecord, RequestRunRecordError> {
    let requested = value.requested();
    let outcome = match value.outcome() {
        DocumentOutcome::Produced { artifact, .. } => RequestDocumentOutcome::Produced {
            document: archived_document(value, *artifact)?,
        },
        DocumentOutcome::Partial {
            document,
            artifact,
            reasons,
        } => {
            let archived_document = match (document, artifact) {
                (Some(_), Some(artifact)) => Some(archived_document(value, *artifact)?),
                (Some(_), None) => {
                    return Err(RequestRunRecordError::PartialDocumentArtifactMissing {
                        requested,
                    });
                }
                (None, _) => None,
            };
            RequestDocumentOutcome::Partial {
                artifact: archived_document.is_none().then_some(*artifact).flatten(),
                document: archived_document,
                reasons: reasons.iter().copied().map(partial_reason).collect(),
            }
        }
        DocumentOutcome::Unavailable { reason } => RequestDocumentOutcome::Unavailable {
            reason: unavailable_reason(*reason),
        },
        DocumentOutcome::Unprojectable { reason } => RequestDocumentOutcome::Unprojectable {
            reason: unprojectable_reason(*reason),
        },
    };
    let browser_observation = value.browser_observation().map(|observation| {
        RequestBrowserDocumentObservation::new(observation.scope(), observation.captured_at())
    });
    Ok(RequestDocumentRecord::new(
        requested,
        outcome,
        browser_observation,
    ))
}

fn archived_document(
    outcome: &AttemptDocumentOutcome,
    artifact: WebArtifactRef,
) -> Result<ArchivedDocumentInput, RequestRunRecordError> {
    let document = outcome.document_archive_ref().cloned().ok_or_else(|| {
        RequestRunRecordError::CompletedDocumentReferenceMissing {
            requested: outcome.requested(),
        }
    })?;
    Ok(ArchivedDocumentInput::new(document, Some(artifact)))
}

const fn partial_reason(value: PartialReason) -> RequestDocumentPartialReason {
    match value {
        PartialReason::SourceFamilyPartial => RequestDocumentPartialReason::SourceFamilyPartial,
        PartialReason::SourceArtifactTruncated => {
            RequestDocumentPartialReason::SourceArtifactTruncated
        }
        PartialReason::ClassificationFromRetainedPrefix => {
            RequestDocumentPartialReason::ClassificationFromRetainedPrefix
        }
        PartialReason::DecodedOutputTruncated => {
            RequestDocumentPartialReason::DecodedOutputTruncated
        }
        PartialReason::IncompleteTerminalSequence => {
            RequestDocumentPartialReason::IncompleteTerminalSequence
        }
        PartialReason::DecodedSourceFamilyPartial => {
            RequestDocumentPartialReason::DecodedSourceFamilyPartial
        }
        PartialReason::RenderedDomFamilyPartial => {
            RequestDocumentPartialReason::RenderedDomFamilyPartial
        }
        PartialReason::AccessibilityTreeFamilyPartial => {
            RequestDocumentPartialReason::AccessibilityTreeFamilyPartial
        }
        PartialReason::AccessibilityDepthLimited => {
            RequestDocumentPartialReason::AccessibilityDepthLimited
        }
        PartialReason::AccessibilityNodeLoss => RequestDocumentPartialReason::AccessibilityNodeLoss,
        PartialReason::AccessibilityNodeLossUnknown => {
            RequestDocumentPartialReason::AccessibilityNodeLossUnknown
        }
        PartialReason::AccessibilityByteLoss => RequestDocumentPartialReason::AccessibilityByteLoss,
        PartialReason::AccessibilityByteLossUnknown => {
            RequestDocumentPartialReason::AccessibilityByteLossUnknown
        }
        PartialReason::BrowserArtifactTruncated { family } => {
            RequestDocumentPartialReason::BrowserArtifactTruncated { family }
        }
    }
}

const fn unavailable_reason(value: UnavailableReason) -> RequestDocumentUnavailableReason {
    match value {
        UnavailableReason::SourceArtifactUnavailable => {
            RequestDocumentUnavailableReason::SourceArtifactUnavailable
        }
        UnavailableReason::DecodedSourceNotRetained => {
            RequestDocumentUnavailableReason::DecodedSourceNotRetained
        }
        UnavailableReason::DecodedSourcePayloadUnavailable => {
            RequestDocumentUnavailableReason::DecodedSourcePayloadUnavailable
        }
        UnavailableReason::BrowserDecodedSourceNotRetained => {
            RequestDocumentUnavailableReason::BrowserDecodedSourceNotRetained
        }
        UnavailableReason::CaptureArtifactNotRetained { family } => {
            RequestDocumentUnavailableReason::CaptureArtifactNotRetained { family }
        }
        UnavailableReason::CaptureArtifactPayloadUnavailable { family } => {
            RequestDocumentUnavailableReason::CaptureArtifactPayloadUnavailable { family }
        }
        UnavailableReason::CaptureArtifactFailed { family } => {
            RequestDocumentUnavailableReason::CaptureArtifactFailed { family }
        }
        UnavailableReason::CaptureArtifactUnavailable { family } => {
            RequestDocumentUnavailableReason::CaptureArtifactUnavailable { family }
        }
    }
}

const fn unprojectable_reason(value: UnprojectableReason) -> RequestDocumentUnprojectableReason {
    match value {
        UnprojectableReason::SourceFactsUnavailable => {
            RequestDocumentUnprojectableReason::SourceFactsUnavailable
        }
        UnprojectableReason::UnknownSourceFormat { reason } => {
            RequestDocumentUnprojectableReason::UnknownSourceFormat { reason }
        }
        UnprojectableReason::UnsupportedSourceFormat => {
            RequestDocumentUnprojectableReason::UnsupportedSourceFormat
        }
        UnprojectableReason::AmbiguousSourceFormat => {
            RequestDocumentUnprojectableReason::AmbiguousSourceFormat
        }
        UnprojectableReason::DecodedSourceReferenceMismatch => {
            RequestDocumentUnprojectableReason::DecodedSourceReferenceMismatch
        }
        UnprojectableReason::UnsupportedEncoding { code } => {
            RequestDocumentUnprojectableReason::UnsupportedEncoding { code }
        }
        UnprojectableReason::Undecodable { code } => {
            RequestDocumentUnprojectableReason::Undecodable { code }
        }
        UnprojectableReason::DecodingNotApplicable { code } => {
            RequestDocumentUnprojectableReason::DecodingNotApplicable { code }
        }
        UnprojectableReason::DocumentRejected => {
            RequestDocumentUnprojectableReason::DocumentRejected
        }
        UnprojectableReason::NetworkTreeSchemaUnavailable => {
            RequestDocumentUnprojectableReason::NetworkTreeSchemaUnavailable
        }
        UnprojectableReason::BrowserDocumentEpochUnavailable => {
            RequestDocumentUnprojectableReason::BrowserDocumentEpochUnavailable
        }
        UnprojectableReason::BrowserDocumentNormalizationFailed => {
            RequestDocumentUnprojectableReason::BrowserDocumentNormalizationFailed
        }
        UnprojectableReason::CaptureArtifactNotRequested { family } => {
            RequestDocumentUnprojectableReason::CaptureArtifactNotRequested { family }
        }
        UnprojectableReason::CaptureArtifactUnsupported { family } => {
            RequestDocumentUnprojectableReason::CaptureArtifactUnsupported { family }
        }
    }
}
