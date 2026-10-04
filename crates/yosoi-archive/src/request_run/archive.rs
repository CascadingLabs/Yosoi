use super::{
    AuthoredDocumentSelection, RequestAttemptOutcome, RequestDocumentOutcome, RequestRunRecord,
    RequestRunRecordError, RequestRunTermination,
};
use crate::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::policy::{ArchivedPolicyRecord, read_policy_record};
use crate::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::{Archive, ArchiveError, RequestRunArchiveRef};
use yosoi_policy::policy::{DocumentRequest, DocumentSelectionKind};

const REQUEST_RUN_SCHEMA_VERSION: u32 = 1;

impl sealed::Value for RequestRunRecord {}

impl ArchiveValue for RequestRunRecord {
    type Reference = RequestRunArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        value.validate().map_err(ArchiveError::InvalidRequestRun)?;
        validate_references(archive, value).await?;
        let reference = RequestRunArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::RequestRun,
                REQUEST_RUN_SCHEMA_VERSION,
                reference.key(),
                value,
            )
            .await?;
        Ok(reference)
    }
}

async fn validate_references(
    archive: &Archive,
    value: &RequestRunRecord,
) -> Result<(), ArchiveError> {
    let policy = read_policy_record(archive, value.policy()).await?;
    let expected = policy.effective_identity;
    let found = value.effective_policy();
    if expected != found {
        return Err(ArchiveError::InvalidRequestRun(
            super::RequestRunRecordError::EffectivePolicyIdentityMismatch {
                expected_version: expected.version(),
                expected_digest: expected.digest(),
                found_version: found.version(),
                found_digest: found.digest(),
            },
        ));
    }
    validate_attempts_against_policy(value, &policy)?;

    for attempt in value.attempts() {
        if let Some(reference) = attempt.outcome().capture() {
            let capture: yosoi_web_capture::CaptureBundle = archive.read(reference).await?;
            if let RequestAttemptOutcome::Completed { documents, .. } = attempt.outcome() {
                for document in documents {
                    validate_document(archive, &capture, document).await?;
                }
            }
        }
    }
    Ok(())
}

fn validate_attempts_against_policy(
    value: &RequestRunRecord,
    policy: &ArchivedPolicyRecord,
) -> Result<(), ArchiveError> {
    let effective = &policy.effective_policy;
    if value.attempts().len() != effective.page.acquisitions.len() {
        return Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::PolicyAttemptCountMismatch {
                expected: effective.page.acquisitions.len(),
                observed: value.attempts().len(),
            },
        ));
    }
    for (position, (recorded, expected)) in value
        .attempts()
        .iter()
        .zip(&effective.page.acquisitions)
        .enumerate()
    {
        if recorded.acquisition() != expected.acquisition {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::PolicyAcquisitionMismatch {
                    position,
                    expected: expected.acquisition,
                    found: recorded.acquisition(),
                },
            ));
        }
        let recorded_selection = match recorded.authored_selection() {
            AuthoredDocumentSelection::Current => DocumentSelectionKind::Current,
            AuthoredDocumentSelection::Exact => DocumentSelectionKind::Exact,
        };
        if recorded_selection != expected.authored_selection {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::PolicyAuthorshipMismatch {
                    position,
                    expected: expected.authored_selection,
                    found: recorded_selection,
                },
            ));
        }
        if recorded.requested_documents() != expected.documents {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::PolicyDocumentsMismatch { position },
            ));
        }
        if value.termination() == RequestRunTermination::Completed
            && matches!(recorded.outcome(), RequestAttemptOutcome::NotStarted { .. })
        {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::CompletedRunContainsNotStarted { position },
            ));
        }
        if value.termination() == RequestRunTermination::Completed
            && attempt_failed_by_cancellation(recorded.outcome())
        {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::CompletedRunContainsCancellationFailure { position },
            ));
        }
    }
    Ok(())
}

const fn attempt_failed_by_cancellation(outcome: &RequestAttemptOutcome) -> bool {
    use super::{
        RequestAttemptDiagnostic, RequestDirectHttpTransportDiagnostic as DirectHttpDiagnostic,
    };
    matches!(
        outcome,
        RequestAttemptOutcome::Failed {
            diagnostic: RequestAttemptDiagnostic::DirectHttpTransport(
                DirectHttpDiagnostic::Cancelled
            ) | RequestAttemptDiagnostic::BrowserCancelled
                | RequestAttemptDiagnostic::BrowserCancelledCleanupFailed,
            ..
        }
    )
}

async fn validate_document(
    archive: &Archive,
    capture: &yosoi_web_capture::CaptureBundle,
    record: &super::RequestDocumentRecord,
) -> Result<(), ArchiveError> {
    let (document, artifact) = match record.outcome() {
        RequestDocumentOutcome::Produced { document }
        | RequestDocumentOutcome::Partial {
            document: Some(document),
            ..
        } => (Some(document.document()), document.source_artifact()),
        RequestDocumentOutcome::Partial { artifact, .. } => (None, *artifact),
        RequestDocumentOutcome::Unavailable { .. }
        | RequestDocumentOutcome::Unprojectable { .. } => (None, None),
    };
    let archived_document = if let Some(reference) = document {
        let archived: yosoi_documents::Document = archive.read(reference).await?;
        if !document_class_matches(record.requested(), archived.class()) {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::DocumentClassMismatch {
                    requested: record.requested(),
                    actual: archived.class(),
                },
            ));
        }
        Some(archived)
    } else {
        None
    };
    if let Some(artifact) = artifact {
        let expected = expected_artifact_family(record.requested());
        if artifact.family() != expected {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::DocumentArtifactFamilyMismatch {
                    requested: record.requested(),
                    expected,
                    found: artifact.family(),
                },
            ));
        }
        if capture.payload(artifact).is_none() {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::DocumentSourcePayloadUnavailable {
                    requested: record.requested(),
                    artifact,
                },
            ));
        }
        if let Some(document) = archived_document.as_ref()
            && matches!(
                record.requested(),
                DocumentRequest::RenderedDom | DocumentRequest::AccessibilityTree
            )
            && document
                .profile()
                .epoch()
                .map(yosoi_documents::DocumentEpoch::get)
                != artifact_document_epoch(capture, artifact)
        {
            return Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::DocumentEpochMismatch {
                    requested: record.requested(),
                },
            ));
        }
    }
    Ok(())
}

const fn expected_artifact_family(
    requested: DocumentRequest,
) -> yosoi_web_capture::WebArtifactFamily {
    use yosoi_web_capture::WebArtifactFamily;
    match requested {
        DocumentRequest::ResponseDocument => WebArtifactFamily::DecodedSource,
        DocumentRequest::RenderedDom => WebArtifactFamily::RenderedDom,
        DocumentRequest::AccessibilityTree => WebArtifactFamily::AccessibilityTree,
        DocumentRequest::NetworkTree => WebArtifactFamily::Network,
    }
}

fn artifact_document_epoch(
    capture: &yosoi_web_capture::CaptureBundle,
    reference: yosoi_web_capture::WebArtifactRef,
) -> Option<u64> {
    use yosoi_web_capture::BrowserArtifactContext;
    capture
        .capture()
        .artifacts()
        .results()
        .all_artifacts()
        .into_iter()
        .find(|artifact| artifact.reference() == reference)
        .and_then(|artifact| artifact.metadata().browser_context().copied())
        .and_then(|context| match context {
            BrowserArtifactContext::DocumentSnapshot { scope, .. } => Some(scope.epoch.0),
            BrowserArtifactContext::Visual(_) => None,
        })
}

const fn document_class_matches(
    requested: DocumentRequest,
    actual: yosoi_documents::DocumentClass,
) -> bool {
    use yosoi_documents::DocumentClass;
    match requested {
        DocumentRequest::ResponseDocument => matches!(
            actual,
            DocumentClass::SourceHtml
                | DocumentClass::SourceXml
                | DocumentClass::SourceJson
                | DocumentClass::SourceText
        ),
        DocumentRequest::RenderedDom => matches!(actual, DocumentClass::RenderedDom),
        DocumentRequest::AccessibilityTree => {
            matches!(actual, DocumentClass::AccessibilityTree)
        }
        DocumentRequest::NetworkTree => false,
    }
}

impl sealed::Reference for RequestRunArchiveRef {}

impl ArchiveReference for RequestRunArchiveRef {
    type Value = RequestRunRecord;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        if reference.format_version() != ARCHIVE_FORMAT_VERSION {
            return Err(ArchiveError::UnsupportedFormat {
                found: reference.format_version(),
                supported: ARCHIVE_FORMAT_VERSION,
            });
        }
        let record = archive
            .read_record(
                RecordKind::RequestRun,
                REQUEST_RUN_SCHEMA_VERSION,
                reference.key(),
            )
            .await?;
        validate_references(archive, &record).await?;
        Ok(record)
    }
}

#[cfg(test)]
#[path = "archive_tests.rs"]
mod migration_tests;
