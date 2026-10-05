use std::collections::BTreeMap;

use yosoi_types::ArtifactAvailability;
use yosoi_web_capture::{
    ArtifactFamilyResult, ClassificationExtent, DurableCharacterDecoding,
    SourceClassificationOutcome, SourceFormat, SourceRepresentationEvidence, WebArtifactRef,
    WebCapture,
};

use crate::Document;

use super::{DocumentOutcome, PartialReason, UnavailableReason, UnprojectableReason};

pub(super) fn project_browser_response_document(
    capture: &WebCapture,
    payloads: &mut BTreeMap<WebArtifactRef, Vec<u8>>,
) -> DocumentOutcome {
    let source_results = capture.artifacts().results().source();
    let Some(source_artifacts) = source_results.artifacts() else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::SourceArtifactUnavailable,
        };
    };
    let [source] = source_artifacts else {
        return reference_mismatch();
    };

    let representation_results = capture.artifacts().results().source_representation();
    let Some(representation_artifacts) = representation_results.artifacts() else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::BrowserDecodedSourceNotRetained,
        };
    };
    let [representation] = representation_artifacts else {
        return reference_mismatch();
    };
    let representation_ref: WebArtifactRef = representation.reference().into();
    let Some(representation_payload) = payloads.remove(&representation_ref) else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::BrowserDecodedSourceNotRetained,
        };
    };
    let Ok(evidence) = SourceRepresentationEvidence::from_json(&representation_payload) else {
        return DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::SourceFactsUnavailable,
        };
    };
    if evidence.source() != source.reference() {
        return reference_mismatch();
    }

    let (source_format, classification_extent) = match evidence.classification() {
        SourceClassificationOutcome::Classified(classification) => {
            (classification.format(), classification.extent())
        }
        SourceClassificationOutcome::Unknown { reason, .. } => {
            return DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::UnknownSourceFormat { reason: *reason },
            };
        }
        SourceClassificationOutcome::Unsupported { .. } => {
            return DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::UnsupportedSourceFormat,
            };
        }
        SourceClassificationOutcome::Ambiguous { .. } => {
            return DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::AmbiguousSourceFormat,
            };
        }
    };

    let (decoded_ref, output_truncated, source_truncated, incomplete_terminal) =
        match evidence.decoding() {
            DurableCharacterDecoding::Complete(view) => (
                view.decoded_source(),
                false,
                view.source_truncated(),
                view.incomplete_terminal_sequence(),
            ),
            DurableCharacterDecoding::OutputTruncated(view) => (
                view.decoded_source(),
                true,
                view.source_truncated(),
                view.incomplete_terminal_sequence(),
            ),
            DurableCharacterDecoding::UnsupportedEncoding { code } => {
                return DocumentOutcome::Unprojectable {
                    reason: UnprojectableReason::UnsupportedEncoding { code: *code },
                };
            }
            DurableCharacterDecoding::Undecodable { code } => {
                return DocumentOutcome::Unprojectable {
                    reason: UnprojectableReason::Undecodable { code: *code },
                };
            }
            DurableCharacterDecoding::NotApplicable { code } => {
                return DocumentOutcome::Unprojectable {
                    reason: UnprojectableReason::DecodingNotApplicable { code: *code },
                };
            }
        };
    let Some(decoded_ref) = decoded_ref else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::BrowserDecodedSourceNotRetained,
        };
    };

    let decoded_results = capture.artifacts().results().decoded_source();
    let Some(decoded_artifacts) = decoded_results.artifacts() else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::BrowserDecodedSourceNotRetained,
        };
    };
    let Some(decoded) = decoded_artifacts
        .iter()
        .find(|artifact| artifact.reference() == decoded_ref)
    else {
        return reference_mismatch();
    };
    let decoded_web_ref: WebArtifactRef = decoded_ref.into();
    let Some(decoded_payload) = payloads.remove(&decoded_web_ref) else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::DecodedSourcePayloadUnavailable,
        };
    };

    let mut reasons = Vec::with_capacity(6);
    if matches!(source_results, ArtifactFamilyResult::Partial { .. }) {
        reasons.push(PartialReason::SourceFamilyPartial);
    }
    if source.metadata().record().availability() == ArtifactAvailability::Truncated
        || source_truncated
    {
        reasons.push(PartialReason::SourceArtifactTruncated);
    }
    if classification_extent == ClassificationExtent::RetainedPrefix {
        reasons.push(PartialReason::ClassificationFromRetainedPrefix);
    }
    if output_truncated
        || decoded.metadata().record().availability() == ArtifactAvailability::Truncated
    {
        reasons.push(PartialReason::DecodedOutputTruncated);
    }
    if incomplete_terminal {
        reasons.push(PartialReason::IncompleteTerminalSequence);
    }
    if matches!(decoded_results, ArtifactFamilyResult::Partial { .. }) {
        reasons.push(PartialReason::DecodedSourceFamilyPartial);
    }
    if !reasons.is_empty() {
        return DocumentOutcome::Partial {
            document: None,
            artifact: Some(decoded_web_ref),
            reasons,
        };
    }

    let untyped = decoded_web_ref.as_untyped();
    let document_id = format!("{}:{}", untyped.activity_id(), untyped.artifact_id());
    let document = match source_format {
        SourceFormat::Html => Document::html(document_id, decoded_payload),
        SourceFormat::Xml(_) => Document::xml(document_id, decoded_payload),
        SourceFormat::Json => Document::json(document_id, decoded_payload),
        SourceFormat::PlainText => Document::text(document_id, decoded_payload),
    };
    document.map_or(
        DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::DocumentRejected,
        },
        |document| DocumentOutcome::Produced {
            document,
            artifact: decoded_web_ref,
        },
    )
}

const fn reference_mismatch() -> DocumentOutcome {
    DocumentOutcome::Unprojectable {
        reason: UnprojectableReason::DecodedSourceReferenceMismatch,
    }
}
