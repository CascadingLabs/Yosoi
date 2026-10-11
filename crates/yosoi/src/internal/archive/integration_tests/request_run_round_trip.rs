use super::capture_round_trip_support as capture_support;

use std::error::Error;
use std::fs;
use std::num::NonZeroU32;
use std::path::{Path, PathBuf};

use crate::internal::archive::{
    Archive, ArchiveError, ArchivedDocumentInput, AuthoredDocumentSelection, BrowserFailureReason,
    CaptureArchiveRef, EffectivePolicyIdentityRecord, PolicyArchiveRef, RequestAttemptDiagnostic,
    RequestAttemptFailureKind, RequestAttemptOutcome, RequestAttemptRecord,
    RequestDirectHttpTransportDiagnostic, RequestDocumentOutcome, RequestDocumentPartialReason,
    RequestDocumentRecord, RequestDocumentUnavailableReason, RequestNotStartedReason,
    RequestRunArchiveRef, RequestRunRecord, RequestRunRecordError, RequestRunTermination,
};
use crate::internal::documents::Document;
use crate::internal::policy::{
    Policy,
    policy::{Acquisition, AcquisitionKind, BrowserMode, DocumentRequest},
};
use crate::internal::types::{ArtifactId, ArtifactRef, CaptureId, Sha256Digest};
use crate::internal::web_capture::{DecodedSourceArtifactRef, WebArtifactRef};
use tempfile::tempdir;

const POLICY_REF: &str = "policy:v1:123e4567-e89b-42d3-a456-426614174010";
const DOCUMENT_REF: &str = "document:v1:123e4567-e89b-42d3-a456-426614174011";
const REQUEST_ID: &str = "123e4567-e89b-42d3-a456-426614174100";
const CAPTURE_ONE: &str = "123e4567-e89b-42d3-a456-426614174101";
const CAPTURE_TWO: &str = "123e4567-e89b-42d3-a456-426614174102";
const CAPTURE_THREE: &str = "123e4567-e89b-42d3-a456-426614174103";
const CAPTURE_FOUR: &str = "123e4567-e89b-42d3-a456-426614174104";

#[test]
fn effective_policy_projection_rejects_zero_version() {
    assert_eq!(
        EffectivePolicyIdentityRecord::try_new(0, Sha256Digest::digest(b"policy")),
        Err(RequestRunRecordError::ZeroEffectivePolicyIdentityVersion)
    );
}

#[tokio::test]
async fn request_run_round_trips_exact_ordered_provenance() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let record = published_request_run(&archive).await?;

    let reference = archive.write(&record).await?;
    require_request_run_ref(&reference);
    let serialized = reference.to_string();
    drop(archive);

    let archive = Archive::open(&root).await?;
    let parsed: RequestRunArchiveRef = serialized.parse()?;
    if archive.read(&parsed).await? != record {
        return Err("request run changed across Archive round trip".into());
    }

    let record_json: serde_json::Value =
        serde_json::from_slice(&fs::read(record_path(&root, parsed.logical_key()))?)?;
    if record_json
        .pointer("/value/target_origin")
        .and_then(serde_json::Value::as_str)
        != Some("https://example.test")
    {
        return Err("request record retained more than the canonical target origin".into());
    }
    Ok(())
}

#[tokio::test]
async fn request_run_rejects_dangling_and_mismatched_dependencies() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = Policy::default();
    let policy_ref = archive.write(&policy).await?;

    let mismatched = RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        policy_ref.clone(),
        effective_policy()?,
        RequestRunTermination::Completed,
        Vec::new(),
    )?;
    if format!("{mismatched:?}").contains("example.test") {
        return Err("RequestRun Debug exposed its target origin".into());
    }
    if !matches!(
        archive.write(&mismatched).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::EffectivePolicyIdentityMismatch { .. }
        ))
    ) {
        return Err("request run accepted a Policy with another effective identity".into());
    }

    let missing_capture_id = capture_id(CAPTURE_ONE)?;
    let failed = RequestAttemptRecord::try_new(
        missing_capture_id,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Failed {
            kind: RequestAttemptFailureKind::Projection,
            diagnostic: RequestAttemptDiagnostic::ProjectionFailed,
            capture: Some(capture_ref(missing_capture_id, 1)?),
            response_status: Some(200),
        },
    )?;
    let dangling = RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        policy_ref,
        EffectivePolicyIdentityRecord::from_identity(policy.effective_identity()?),
        RequestRunTermination::Completed,
        vec![failed],
    )?;
    if !matches!(
        archive.write(&dangling).await,
        Err(ArchiveError::RecordNotFound {
            kind: "capture",
            ..
        })
    ) {
        return Err("request run accepted a missing Capture dependency".into());
    }
    Ok(())
}

#[tokio::test]
async fn archived_v2_effective_identity_is_rejected_for_current_map_search_policy()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = Policy::default();
    let policy_ref = archive.write(&policy).await?;
    let legacy_identity = EffectivePolicyIdentityRecord::try_new(
        2,
        Sha256Digest::digest(b"legacy-default-policy-v2"),
    )?;
    let run = RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        policy_ref,
        legacy_identity,
        RequestRunTermination::Cancelled,
        vec![not_started_attempt(
            capture_id(CAPTURE_ONE)?,
            AcquisitionKind::DirectHttp,
        )?],
    )?;

    if !matches!(
        archive.write(&run).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::EffectivePolicyIdentityMismatch {
                expected_version: 5,
                found_version: 2,
                ..
            }
        ))
    ) {
        return Err(
            "Archive accepted a v2 effective identity for a Map and Search-aware Policy".into(),
        );
    }
    Ok(())
}

#[tokio::test]
async fn request_run_rejects_wrong_document_provenance_family() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let policy = Policy::default();
    let policy_ref = archive.write(&policy).await?;
    let capture = capture_support::mixed_bundle()?;
    let capture_ref = archive.write(&capture).await?;
    let source_artifact = capture_support::source_references(capture.capture())
        .first()
        .copied()
        .ok_or("capture fixture must contain a source artifact")?;
    let document = Document::html("response-document", capture_support::BINARY_BYTES.to_vec())?;
    let document_ref = archive.write(&document).await?;
    let completed = RequestAttemptRecord::try_new(
        capture_ref.capture_id(),
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Completed {
            capture: capture_ref,
            response_status: Some(200),
            documents: vec![RequestDocumentRecord::new(
                DocumentRequest::ResponseDocument,
                RequestDocumentOutcome::Produced {
                    document: ArchivedDocumentInput::new(document_ref, Some(source_artifact)),
                },
                None,
            )],
        },
    )?;
    let run = RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        policy_ref,
        EffectivePolicyIdentityRecord::from_identity(policy.effective_identity()?),
        RequestRunTermination::Completed,
        vec![completed],
    )?;
    if !matches!(
        archive.write(&run).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::DocumentArtifactFamilyMismatch { .. }
        ))
    ) {
        return Err("request run accepted raw Source provenance for a response Document".into());
    }
    Ok(())
}

#[tokio::test]
async fn request_run_must_match_archived_policy_attempt_order_and_authorship()
-> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let mut policy = Policy::default();
    policy.page.acquisitions = vec![
        Acquisition::DirectHttp,
        Acquisition::Browser(BrowserMode::Headless),
        Acquisition::Browser(BrowserMode::Headful),
    ];
    let policy_ref = archive.write(&policy).await?;
    let identity = EffectivePolicyIdentityRecord::from_identity(policy.effective_identity()?);
    let direct = not_started_attempt(capture_id(CAPTURE_ONE)?, AcquisitionKind::DirectHttp)?;
    let headless = not_started_attempt(
        capture_id(CAPTURE_TWO)?,
        AcquisitionKind::Browser {
            mode: BrowserMode::Headless,
        },
    )?;
    let headful = not_started_attempt(
        capture_id(CAPTURE_THREE)?,
        AcquisitionKind::Browser {
            mode: BrowserMode::Headful,
        },
    )?;
    let make_run = |attempts: Vec<RequestAttemptRecord>,
                    termination: RequestRunTermination|
     -> Result<RequestRunRecord, Box<dyn Error>> {
        Ok(RequestRunRecord::try_new(
            REQUEST_ID.parse()?,
            "https://example.test".parse()?,
            policy_ref.clone(),
            identity,
            termination,
            attempts,
        )?)
    };

    let omitted = make_run(
        vec![direct.clone(), headless.clone()],
        RequestRunTermination::Cancelled,
    )?;
    if !matches!(
        archive.write(&omitted).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::PolicyAttemptCountMismatch { .. }
        ))
    ) {
        return Err("request run accepted an omitted Policy attempt".into());
    }

    let reordered = make_run(
        vec![headless.clone(), direct.clone(), headful.clone()],
        RequestRunTermination::Cancelled,
    )?;
    if !matches!(
        archive.write(&reordered).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::PolicyAcquisitionMismatch { position: 0, .. }
        ))
    ) {
        return Err("request run accepted reordered Policy attempts".into());
    }

    let altered_documents = RequestAttemptRecord::try_new(
        capture_id(CAPTURE_ONE)?,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        Vec::new(),
        RequestAttemptOutcome::NotStarted {
            reason: RequestNotStartedReason::Cancelled,
        },
    )?;
    let altered = make_run(
        vec![altered_documents, headless.clone(), headful.clone()],
        RequestRunTermination::Cancelled,
    )?;
    if !matches!(
        archive.write(&altered).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::PolicyDocumentsMismatch { position: 0 }
        ))
    ) {
        return Err("request run accepted documents that differ from Policy".into());
    }

    let exact_authorship = RequestAttemptRecord::try_new(
        capture_id(CAPTURE_ONE)?,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Exact,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::NotStarted {
            reason: RequestNotStartedReason::Cancelled,
        },
    )?;
    let altered = make_run(
        vec![exact_authorship, headless, headful],
        RequestRunTermination::Cancelled,
    )?;
    if !matches!(
        archive.write(&altered).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::PolicyAuthorshipMismatch { position: 0, .. }
        ))
    ) {
        return Err("request run accepted authorship that differs from Policy".into());
    }

    let default_policy = Policy::default();
    let default_ref = archive.write(&default_policy).await?;
    let contradictory = RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        default_ref,
        EffectivePolicyIdentityRecord::from_identity(default_policy.effective_identity()?),
        RequestRunTermination::Completed,
        vec![not_started_attempt(
            capture_id(CAPTURE_FOUR)?,
            AcquisitionKind::DirectHttp,
        )?],
    )?;
    if !matches!(
        archive.write(&contradictory).await,
        Err(ArchiveError::InvalidRequestRun(
            RequestRunRecordError::CompletedRunContainsNotStarted { position: 0 }
        ))
    ) {
        return Err("completed request run accepted a cancelled NotStarted attempt".into());
    }
    Ok(())
}

#[tokio::test]
async fn future_schema_fails_before_request_value_decode() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let record = published_request_run(&archive).await?;
    let reference = archive.write(&record).await?;
    mutate_record(record_path(&root, reference.logical_key()), |record| {
        let object = record.as_object_mut().ok_or("record must be an object")?;
        object.insert("schema_version".to_owned(), serde_json::json!(2));
        object.insert("value".to_owned(), serde_json::json!({"invalid": true}));
        Ok(())
    })?;

    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::MigrationRequired {
            kind: "request-run",
            found_schema: 2,
            supported_schema: 1,
            ..
        })
    ) {
        return Err("future request-run schema decoded as the current record".into());
    }
    Ok(())
}

#[test]
fn request_run_rejects_too_many_or_duplicate_attempts() -> Result<(), Box<dyn Error>> {
    let attempts = vec![
        not_started_attempt(capture_id(CAPTURE_ONE)?, AcquisitionKind::DirectHttp)?,
        not_started_attempt(
            capture_id(CAPTURE_TWO)?,
            AcquisitionKind::Browser {
                mode: BrowserMode::Headless,
            },
        )?,
        not_started_attempt(
            capture_id(CAPTURE_THREE)?,
            AcquisitionKind::Browser {
                mode: BrowserMode::Headful,
            },
        )?,
        not_started_attempt(capture_id(CAPTURE_FOUR)?, AcquisitionKind::DirectHttp)?,
    ];
    if !matches!(
        RequestRunRecord::try_new(
            REQUEST_ID.parse()?,
            "https://example.test".parse()?,
            POLICY_REF.parse()?,
            effective_policy()?,
            RequestRunTermination::Cancelled,
            attempts,
        ),
        Err(RequestRunRecordError::TooManyAttempts {
            maximum: 3,
            observed: 4
        })
    ) {
        return Err("request run accepted more than three attempts".into());
    }

    let duplicate = not_started_attempt(capture_id(CAPTURE_ONE)?, AcquisitionKind::DirectHttp)?;
    if !matches!(
        RequestRunRecord::try_new(
            REQUEST_ID.parse()?,
            "https://example.test".parse()?,
            POLICY_REF.parse()?,
            effective_policy()?,
            RequestRunTermination::Cancelled,
            vec![duplicate.clone(), duplicate],
        ),
        Err(RequestRunRecordError::DuplicateCaptureId { .. })
    ) {
        return Err("request run accepted duplicate CaptureIds".into());
    }
    Ok(())
}

#[test]
fn attempt_rejects_foreign_capture_and_document_artifact() -> Result<(), Box<dyn Error>> {
    let first = capture_id(CAPTURE_ONE)?;
    let second = capture_id(CAPTURE_TWO)?;
    let second_ref = capture_ref(second, 1)?;
    let mismatch = RequestAttemptRecord::try_new(
        first,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Completed {
            capture: second_ref,
            response_status: Some(200),
            documents: Vec::new(),
        },
    );
    if !matches!(
        mismatch,
        Err(RequestRunRecordError::CaptureReferenceMismatch { .. })
    ) {
        return Err("attempt accepted a CaptureArchiveRef for another CaptureId".into());
    }

    let foreign_document =
        ArchivedDocumentInput::new(DOCUMENT_REF.parse()?, Some(decoded_artifact(second, 1)?));
    let mismatch = RequestAttemptRecord::try_new(
        first,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Completed {
            capture: capture_ref(first, 1)?,
            response_status: Some(200),
            documents: vec![RequestDocumentRecord::new(
                DocumentRequest::ResponseDocument,
                RequestDocumentOutcome::Produced {
                    document: foreign_document,
                },
                None,
            )],
        },
    );
    if !matches!(
        mismatch,
        Err(RequestRunRecordError::DocumentArtifactOwnershipMismatch { .. })
    ) {
        return Err("attempt accepted a Document artifact from another capture".into());
    }
    Ok(())
}

#[test]
fn completed_attempt_requires_one_ordered_outcome_per_requested_document()
-> Result<(), Box<dyn Error>> {
    let capture_id = capture_id(CAPTURE_ONE)?;
    let missing = RequestAttemptRecord::try_new(
        capture_id,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Completed {
            capture: capture_ref(capture_id, 1)?,
            response_status: Some(200),
            documents: Vec::new(),
        },
    );
    if !matches!(
        missing,
        Err(RequestRunRecordError::DocumentOutcomeCountMismatch {
            expected: 1,
            observed: 0
        })
    ) {
        return Err("completed attempt omitted a requested document outcome".into());
    }

    let unavailable = |requested| {
        RequestDocumentRecord::new(
            requested,
            RequestDocumentOutcome::Unavailable {
                reason: RequestDocumentUnavailableReason::SourceArtifactUnavailable,
            },
            None,
        )
    };
    let reordered = RequestAttemptRecord::try_new(
        capture_id,
        AcquisitionKind::Browser {
            mode: BrowserMode::Headless,
        },
        AuthoredDocumentSelection::Exact,
        vec![
            DocumentRequest::ResponseDocument,
            DocumentRequest::RenderedDom,
        ],
        RequestAttemptOutcome::Completed {
            capture: capture_ref(capture_id, 1)?,
            response_status: Some(200),
            documents: vec![
                unavailable(DocumentRequest::RenderedDom),
                unavailable(DocumentRequest::ResponseDocument),
            ],
        },
    );
    if !matches!(
        reordered,
        Err(RequestRunRecordError::DocumentOutcomeOrderMismatch {
            position: 0,
            expected: DocumentRequest::ResponseDocument,
            recorded: DocumentRequest::RenderedDom,
        })
    ) {
        return Err("completed attempt accepted reordered document outcomes".into());
    }

    let duplicate_artifact = decoded_artifact(capture_id, 2)?;
    let noncanonical = RequestAttemptRecord::try_new(
        capture_id,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Completed {
            capture: capture_ref(capture_id, 1)?,
            response_status: Some(200),
            documents: vec![RequestDocumentRecord::new(
                DocumentRequest::ResponseDocument,
                RequestDocumentOutcome::Partial {
                    document: Some(ArchivedDocumentInput::new(
                        DOCUMENT_REF.parse()?,
                        Some(decoded_artifact(capture_id, 1)?),
                    )),
                    artifact: Some(duplicate_artifact),
                    reasons: vec![RequestDocumentPartialReason::DecodedOutputTruncated],
                },
                None,
            )],
        },
    );
    if !matches!(
        noncanonical,
        Err(RequestRunRecordError::NonCanonicalPartialDocument { .. })
    ) {
        return Err("partial outcome accepted two competing artifact references".into());
    }
    Ok(())
}

#[tokio::test]
async fn completed_run_rejects_every_cancellation_failure_diagnostic() -> Result<(), Box<dyn Error>>
{
    let temporary = tempdir()?;
    let archive = Archive::open(temporary.path().join(".yosoi")).await?;
    let cases = [
        (
            Acquisition::DirectHttp,
            AcquisitionKind::DirectHttp,
            RequestAttemptDiagnostic::DirectHttpTransport(
                RequestDirectHttpTransportDiagnostic::Cancelled,
            ),
        ),
        (
            Acquisition::Browser(BrowserMode::Headless),
            AcquisitionKind::Browser {
                mode: BrowserMode::Headless,
            },
            RequestAttemptDiagnostic::BrowserCancelled,
        ),
        (
            Acquisition::Browser(BrowserMode::Headful),
            AcquisitionKind::Browser {
                mode: BrowserMode::Headful,
            },
            RequestAttemptDiagnostic::BrowserCancelledCleanupFailed,
        ),
    ];
    for (index, (acquisition, kind, diagnostic)) in cases.into_iter().enumerate() {
        let mut policy = Policy::default();
        policy.page.acquisitions = vec![acquisition];
        let policy_ref = archive.write(&policy).await?;
        let attempt = RequestAttemptRecord::try_new(
            [CAPTURE_ONE, CAPTURE_TWO, CAPTURE_THREE]
                .get(index)
                .ok_or("cancellation case omitted a CaptureId")?
                .parse()?,
            kind,
            AuthoredDocumentSelection::Current,
            vec![DocumentRequest::ResponseDocument],
            RequestAttemptOutcome::Failed {
                kind: RequestAttemptFailureKind::CaptureExecution,
                diagnostic,
                capture: None,
                response_status: None,
            },
        )?;
        let run = RequestRunRecord::try_new(
            REQUEST_ID.parse()?,
            "https://example.test".parse()?,
            policy_ref,
            EffectivePolicyIdentityRecord::from_identity(policy.effective_identity()?),
            RequestRunTermination::Completed,
            vec![attempt],
        )?;
        if !matches!(
            archive.write(&run).await,
            Err(ArchiveError::InvalidRequestRun(
                RequestRunRecordError::CompletedRunContainsCancellationFailure { position: 0 }
            ))
        ) {
            return Err("completed request run accepted a cancellation failure".into());
        }
    }
    Ok(())
}

#[test]
fn request_run_requires_current_reference_formats() -> Result<(), Box<dyn Error>> {
    let attempts = vec![not_started_attempt(
        capture_id(CAPTURE_ONE)?,
        AcquisitionKind::DirectHttp,
    )?];
    let future_policy: PolicyArchiveRef =
        "policy:v2:123e4567-e89b-42d3-a456-426614174010".parse()?;
    let result = RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        future_policy,
        effective_policy()?,
        RequestRunTermination::Cancelled,
        attempts,
    );
    if !matches!(
        result,
        Err(RequestRunRecordError::ReferenceFormatMismatch {
            reference_kind: "policy",
            found: 2,
            expected: 1
        })
    ) {
        return Err("request run accepted a Policy reference from another format".into());
    }

    let future_capture: CaptureArchiveRef = format!("capture:v2:{CAPTURE_ONE}").parse()?;
    let result = RequestAttemptRecord::try_new(
        capture_id(CAPTURE_ONE)?,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Failed {
            kind: RequestAttemptFailureKind::CaptureExecution,
            diagnostic: RequestAttemptDiagnostic::DirectHttpFinalizationFailed,
            capture: Some(future_capture),
            response_status: None,
        },
    );
    if !matches!(
        result,
        Err(RequestRunRecordError::ReferenceFormatMismatch {
            reference_kind: "capture",
            found: 2,
            expected: 1
        })
    ) {
        return Err("attempt accepted a Capture reference from another format".into());
    }
    Ok(())
}

#[tokio::test]
async fn completed_attempt_cannot_decode_without_capture_reference() -> Result<(), Box<dyn Error>> {
    let temporary = tempdir()?;
    let root = temporary.path().join(".yosoi");
    let archive = Archive::open(&root).await?;
    let record = published_request_run(&archive).await?;
    let reference = archive.write(&record).await?;
    mutate_record(record_path(&root, reference.logical_key()), |record| {
        let outcome = record
            .pointer_mut("/value/attempts/0/outcome")
            .and_then(serde_json::Value::as_object_mut)
            .ok_or("completed outcome must be an object")?;
        outcome.remove("capture");
        Ok(())
    })?;
    if !matches!(
        archive.read(&reference).await,
        Err(ArchiveError::InvalidRecordValue {
            kind: "request-run",
            ..
        })
    ) {
        return Err("completed attempt decoded without a CaptureArchiveRef".into());
    }
    Ok(())
}

async fn published_request_run(archive: &Archive) -> Result<RequestRunRecord, Box<dyn Error>> {
    let policy = Policy::default();
    let policy_ref = archive.write(&policy).await?;
    let capture = capture_support::mixed_bundle()?;
    let capture_ref = archive.write(&capture).await?;
    let first = capture_ref.capture_id();
    let completed = RequestAttemptRecord::try_new(
        first,
        AcquisitionKind::DirectHttp,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::Completed {
            capture: capture_ref,
            response_status: Some(200),
            documents: vec![RequestDocumentRecord::new(
                DocumentRequest::ResponseDocument,
                RequestDocumentOutcome::Unavailable {
                    reason: RequestDocumentUnavailableReason::SourceArtifactUnavailable,
                },
                None,
            )],
        },
    )?;
    Ok(RequestRunRecord::try_new(
        REQUEST_ID.parse()?,
        "https://example.test".parse()?,
        policy_ref,
        EffectivePolicyIdentityRecord::from_identity(policy.effective_identity()?),
        RequestRunTermination::Completed,
        vec![completed],
    )?)
}

fn effective_policy() -> Result<EffectivePolicyIdentityRecord, RequestRunRecordError> {
    EffectivePolicyIdentityRecord::try_new(2, Sha256Digest::digest(b"effective-policy"))
}

fn not_started_attempt(
    capture_id: CaptureId,
    acquisition: AcquisitionKind,
) -> Result<RequestAttemptRecord, RequestRunRecordError> {
    RequestAttemptRecord::try_new(
        capture_id,
        acquisition,
        AuthoredDocumentSelection::Current,
        vec![DocumentRequest::ResponseDocument],
        RequestAttemptOutcome::NotStarted {
            reason: RequestNotStartedReason::Cancelled,
        },
    )
}

fn capture_id(value: &str) -> Result<CaptureId, Box<dyn Error>> {
    Ok(value.parse()?)
}

fn capture_ref(capture_id: CaptureId, format: u32) -> Result<CaptureArchiveRef, Box<dyn Error>> {
    Ok(format!("capture:v{format}:{capture_id}").parse()?)
}

fn decoded_artifact(capture_id: CaptureId, ordinal: u32) -> Result<WebArtifactRef, Box<dyn Error>> {
    let artifact_id =
        ArtifactId::new(NonZeroU32::new(ordinal).ok_or("artifact ID cannot be zero")?);
    let reference = ArtifactRef::new(capture_id.activity_id(), artifact_id);
    Ok(DecodedSourceArtifactRef::from_untyped(reference).into())
}

const fn require_request_run_ref(_reference: &RequestRunArchiveRef) {}

fn record_path(root: &Path, key: &str) -> PathBuf {
    let shard: String = key.chars().take(2).collect();
    root.join("archive/v1/records/request-run")
        .join(shard)
        .join(format!("{key}.json"))
}

fn mutate_record(
    path: PathBuf,
    mutate: impl FnOnce(&mut serde_json::Value) -> Result<(), Box<dyn Error>>,
) -> Result<(), Box<dyn Error>> {
    let mut record: serde_json::Value = serde_json::from_slice(&fs::read(&path)?)?;
    mutate(&mut record)?;
    fs::write(path, serde_json::to_vec(&record)?)?;
    Ok(())
}

#[tokio::test]
async fn browser_failure_reasons_round_trip_in_v1_request_records() -> Result<(), Box<dyn Error>> {
    for reason in [
        BrowserFailureReason::Launch,
        BrowserFailureReason::EnvironmentMismatch,
        BrowserFailureReason::CapacityExhausted,
    ] {
        let temporary = tempdir()?;
        let root = temporary.path().join(".yosoi");
        let archive = Archive::open(&root).await?;
        let mut policy = Policy::default();
        policy.page.acquisitions = vec![Acquisition::Browser(BrowserMode::Headless)];
        let policy_ref = archive.write(&policy).await?;
        let attempt = RequestAttemptRecord::try_new(
            CAPTURE_ONE.parse()?,
            AcquisitionKind::Browser {
                mode: BrowserMode::Headless,
            },
            AuthoredDocumentSelection::Current,
            vec![DocumentRequest::ResponseDocument],
            RequestAttemptOutcome::Failed {
                kind: RequestAttemptFailureKind::CaptureExecution,
                diagnostic: RequestAttemptDiagnostic::BrowserFailure(reason),
                capture: None,
                response_status: None,
            },
        )?;
        let record = RequestRunRecord::try_new(
            REQUEST_ID.parse()?,
            "https://example.test".parse()?,
            policy_ref,
            EffectivePolicyIdentityRecord::from_identity(policy.effective_identity()?),
            RequestRunTermination::Completed,
            vec![attempt],
        )?;
        let reference = archive.write(&record).await?;
        if reference.format_version() != 1 {
            return Err("browser diagnostic unexpectedly changed the Archive format".into());
        }
        drop(archive);
        let reopened = Archive::open(&root).await?;
        if reopened.read(&reference).await? != record {
            return Err("browser reason was lost during a v1 Request-run round trip".into());
        }
    }
    Ok(())
}
