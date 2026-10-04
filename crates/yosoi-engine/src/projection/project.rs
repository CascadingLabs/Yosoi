use std::collections::BTreeMap;

use yosoi_policy::policy::{AcquisitionKind, DocumentRequest};
use yosoi_types::ArtifactAvailability;
use yosoi_web_capture::{
    ArtifactFamilyResult, CharacterDecodingOutcome, ClassificationExtent, DecodedExtent,
    SourceClassificationOutcome, SourceFormat as CapturedSourceFormat, SourceRepresentationFacts,
    WebArtifactRef, WebCapture,
};

use crate::{Document, PolicyCapture, PolicyCaptureOutcome, PreparedAttempt, PreparedPageRequest};

use super::browser::project_browser_documents;
use super::outcome::{
    DocumentOutcome, PartialReason, ProjectedAttempt, ProjectedAttemptTransport, ProjectionError,
    UnavailableReason, UnprojectableReason,
};

/// Consumes one capture and projects documents requested by its prepared attempt.
///
/// The exact prepared target, capture ID, policy identity, and authored document
/// selection and complete policy snapshot are retained. Artifact payloads are
/// moved out of the `CaptureBundle`; no retained payload buffer is cloned.
pub fn project_attempt(
    capture: PolicyCapture,
    prepared: &PreparedPageRequest,
    attempt: &PreparedAttempt,
) -> Result<ProjectedAttempt, ProjectionError> {
    if !prepared.attempts().contains(attempt) {
        return Err(ProjectionError::ForeignAttempt);
    }

    let (applied_policy, outcome) = capture.into_parts();
    if applied_policy.identity() != prepared.effective_policy_identity() {
        return Err(ProjectionError::PolicyIdentityMismatch);
    }
    let (bundle, transport, source_facts) = match (attempt.kind(), outcome) {
        (AcquisitionKind::DirectHttp, PolicyCaptureOutcome::DirectHttp(capture)) => {
            for document in attempt.documents() {
                if *document != DocumentRequest::ResponseDocument {
                    return Err(ProjectionError::UnsupportedDocumentRequest {
                        document: *document,
                    });
                }
            }
            let (bundle, response, source_facts, _identity) = capture.into_parts();
            (
                bundle,
                ProjectedAttemptTransport::DirectHttp(Box::new(response)),
                source_facts,
            )
        }
        (
            AcquisitionKind::Browser { .. },
            PolicyCaptureOutcome::Browser {
                bundle,
                cleanup,
                status,
            },
        ) => (
            *bundle,
            ProjectedAttemptTransport::Browser { cleanup, status },
            None,
        ),
        _ => return Err(ProjectionError::CaptureOutcomeMismatch),
    };
    let (capture_metadata, payloads) = bundle.into_parts();
    let capture_id = attempt.capture_id();
    if capture_metadata.id() != capture_id {
        return Err(ProjectionError::CaptureIdMismatch);
    }
    let mut payloads = payloads.into_iter().collect::<BTreeMap<_, _>>();

    let documents = match (&transport, attempt.kind()) {
        (ProjectedAttemptTransport::DirectHttp(_), AcquisitionKind::DirectHttp) => {
            project_direct_http_documents(
                &capture_metadata,
                source_facts.as_ref(),
                attempt.documents(),
                &mut payloads,
            )?
        }
        (ProjectedAttemptTransport::Browser { .. }, AcquisitionKind::Browser { .. }) => {
            project_browser_documents(
                &capture_metadata,
                attempt.documents(),
                prepared.policy_snapshot().policy(),
                &mut payloads,
            )?
        }
        _ => return Err(ProjectionError::CaptureOutcomeMismatch),
    };

    // Keep a complete unsupported representation for native metadata parsing.
    // Move the original bounded payload; do not fabricate a Document.
    let raw_response = if attempt.kind() == AcquisitionKind::DirectHttp
        && attempt
            .documents()
            .contains(&DocumentRequest::ResponseDocument)
        && documents.iter().all(|outcome| outcome.document().is_none())
    {
        capture_metadata
            .artifacts()
            .results()
            .source()
            .artifacts()
            .and_then(|artifacts| artifacts.first())
            .filter(|artifact| {
                matches!(
                    artifact.metadata().extent(),
                    yosoi_web_capture::ArtifactByteExtent::Complete { .. }
                )
            })
            .and_then(|artifact| payloads.remove(&WebArtifactRef::Source(artifact.reference())))
    } else {
        None
    };

    Ok(ProjectedAttempt::new(
        capture_id,
        applied_policy,
        prepared.policy_snapshot().clone(),
        attempt.authored_selection(),
        capture_metadata,
        transport,
        documents,
    )
    .with_raw_response(raw_response))
}

fn project_direct_http_documents(
    capture: &WebCapture,
    source_facts: Option<&SourceRepresentationFacts>,
    requested: &[DocumentRequest],
    payloads: &mut BTreeMap<WebArtifactRef, Vec<u8>>,
) -> Result<Vec<DocumentOutcome>, ProjectionError> {
    requested
        .iter()
        .map(|document| match document {
            DocumentRequest::ResponseDocument => {
                Ok(project_response_document(capture, source_facts, payloads))
            }
            other => Err(ProjectionError::UnsupportedDocumentRequest { document: *other }),
        })
        .collect()
}

fn project_response_document(
    capture: &WebCapture,
    source_facts: Option<&SourceRepresentationFacts>,
    payloads: &mut BTreeMap<WebArtifactRef, Vec<u8>>,
) -> DocumentOutcome {
    let source_results = capture.artifacts().results().source();
    let Some(source_artifacts) = source_results.artifacts() else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::SourceArtifactUnavailable,
        };
    };
    let [source_artifact] = source_artifacts else {
        return DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::DecodedSourceReferenceMismatch,
        };
    };
    let Some(source_facts) = source_facts else {
        return DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::SourceFactsUnavailable,
        };
    };
    let (source_format, classification_extent) = match source_facts.classification() {
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

    let (
        decoded_reference,
        decoded_source_reference,
        decoding_partial,
        source_truncated,
        incomplete_terminal,
    ) = match source_facts.decoding() {
        CharacterDecodingOutcome::Complete(view) => (
            view.artifact().reference(),
            view.source(),
            false,
            view.source_truncated(),
            view.incomplete_terminal_sequence(),
        ),
        CharacterDecodingOutcome::OutputTruncated(view) => (
            view.artifact().reference(),
            view.source(),
            true,
            view.source_truncated(),
            view.incomplete_terminal_sequence(),
        ),
        CharacterDecodingOutcome::UnsupportedEncoding(code) => {
            return DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::UnsupportedEncoding { code: *code },
            };
        }
        CharacterDecodingOutcome::Undecodable(code) => {
            return DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::Undecodable { code: *code },
            };
        }
        CharacterDecodingOutcome::NotApplicable(code) => {
            return DocumentOutcome::Unprojectable {
                reason: UnprojectableReason::DecodingNotApplicable { code: *code },
            };
        }
    };

    if source_artifact.reference() != decoded_source_reference {
        return DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::DecodedSourceReferenceMismatch,
        };
    }

    let decoded_results = capture.artifacts().results().decoded_source();
    let Some(decoded_artifacts) = decoded_results.artifacts() else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::DecodedSourceNotRetained,
        };
    };
    if !decoded_artifacts
        .iter()
        .any(|artifact| artifact.reference() == decoded_reference)
    {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::DecodedSourceNotRetained,
        };
    }

    let expected_artifact: WebArtifactRef = decoded_reference.into();
    let Some(decoded_payload) = payloads.remove(&expected_artifact) else {
        return DocumentOutcome::Unavailable {
            reason: UnavailableReason::DecodedSourcePayloadUnavailable,
        };
    };

    let mut partial_reasons = Vec::with_capacity(7);
    if matches!(source_results, ArtifactFamilyResult::Partial { .. }) {
        partial_reasons.push(PartialReason::SourceFamilyPartial);
    }
    if matches!(
        source_artifact.metadata().record().availability(),
        ArtifactAvailability::Truncated
    ) || source_truncated
    {
        partial_reasons.push(PartialReason::SourceArtifactTruncated);
    }
    if classification_extent == ClassificationExtent::RetainedPrefix {
        partial_reasons.push(PartialReason::ClassificationFromRetainedPrefix);
    }
    if decoding_partial
        || matches!(
            decoded_reference_metadata(capture, decoded_reference),
            Some(ArtifactAvailability::Truncated)
        )
    {
        partial_reasons.push(PartialReason::DecodedOutputTruncated);
    }
    if incomplete_terminal {
        partial_reasons.push(PartialReason::IncompleteTerminalSequence);
    }
    if matches!(decoded_results, ArtifactFamilyResult::Partial { .. }) {
        partial_reasons.push(PartialReason::DecodedSourceFamilyPartial);
    }
    let decoded_complete = decoded_artifact_is_complete(decoded_artifacts, decoded_reference);
    if !decoded_complete && !partial_reasons.contains(&PartialReason::DecodedOutputTruncated) {
        partial_reasons.push(PartialReason::DecodedOutputTruncated);
    }
    if !partial_reasons.is_empty() {
        return DocumentOutcome::Partial {
            document: None,
            artifact: Some(expected_artifact),
            reasons: partial_reasons,
        };
    }

    let untyped_reference = expected_artifact.as_untyped();
    let document_id = format!(
        "{}:{}",
        untyped_reference.activity_id(),
        untyped_reference.artifact_id()
    );
    let document = match source_format {
        CapturedSourceFormat::Html => Document::html(document_id, decoded_payload),
        CapturedSourceFormat::Xml(_) => Document::xml(document_id, decoded_payload),
        CapturedSourceFormat::Json => Document::json(document_id, decoded_payload),
        CapturedSourceFormat::PlainText => Document::text(document_id, decoded_payload),
    };
    let Ok(document) = document else {
        return DocumentOutcome::Unprojectable {
            reason: UnprojectableReason::DocumentRejected,
        };
    };
    DocumentOutcome::Produced {
        document,
        artifact: expected_artifact,
    }
}

fn decoded_reference_metadata(
    capture: &WebCapture,
    reference: yosoi_web_capture::DecodedSourceArtifactRef,
) -> Option<ArtifactAvailability> {
    capture
        .artifacts()
        .results()
        .decoded_source()
        .artifacts()?
        .iter()
        .find(|artifact| artifact.reference() == reference)
        .map(|artifact| artifact.metadata().record().availability())
}

fn decoded_artifact_is_complete(
    artifacts: &[yosoi_web_capture::DecodedSourceArtifact],
    reference: yosoi_web_capture::DecodedSourceArtifactRef,
) -> bool {
    artifacts.iter().any(|artifact| {
        artifact.reference() == reference
            && artifact.metadata().record().availability() == ArtifactAvailability::Retained
            && matches!(
                artifact.interpretation().source_extent(),
                DecodedExtent::Complete
            )
            && matches!(
                artifact.interpretation().unicode_extent(),
                DecodedExtent::Complete
            )
    })
}
