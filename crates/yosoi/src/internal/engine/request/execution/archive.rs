use crate::internal::archive as yosoi_archive;

use crate::internal::archive::{
    Archive, AuthoredDocumentSelection, EffectivePolicyIdentityRecord, PolicyArchiveRef,
    RequestAttemptOutcome, RequestAttemptRecord, RequestNotStartedReason, RequestRunRecord,
    RequestRunTermination,
};
use crate::internal::policy::policy::DocumentSelectionKind;
use tokio_util::sync::CancellationToken;

use crate::internal::engine::{
    BoundPageRequest, PageRequest, PolicyResolver, PreparedAttempt, PreparedPageRequest,
    project_attempt,
};

use super::{
    ArchivedRequestError, ArchivedRequestProgress, ArchivedResponse, AttemptCaptureFacts,
    AttemptDiagnostic, AttemptFailureKind, AttemptOutcome, NotStartedReason, RequestExecutor,
    RequestSendError, Response, ResponseTermination, execution_failure_facts, standard,
};

mod diagnostic;
mod document;
use diagnostic::{diagnostic, failure_kind};
use document::records as document_records;

impl RequestExecutor {
    pub(super) async fn execute_prepared_archived(
        &self,
        prepared: PreparedPageRequest,
        cancellation: &CancellationToken,
        archive: &Archive,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let request_id = prepared.id();
        let policy_ref = archive
            .write(prepared.policy_snapshot().policy())
            .await
            .map_err(|source| ArchivedRequestError::PolicyPublication {
                request_id,
                source: Box::new(source),
            })?;
        let mut attempts = Vec::with_capacity(prepared.attempts().len());
        let mut progress = ArchivedRequestProgress::new(policy_ref.clone());
        let mut termination = if cancellation.is_cancelled() {
            ResponseTermination::Cancelled
        } else {
            ResponseTermination::Completed
        };
        let mut cancellation_observed = cancellation.is_cancelled();

        for (index, attempt) in prepared.attempts().iter().enumerate() {
            if cancellation_observed || cancellation.is_cancelled() {
                termination = ResponseTermination::Cancelled;
                cancellation_observed = true;
                attempts.push(AttemptOutcome::not_started_outcome(
                    &prepared,
                    attempt,
                    NotStartedReason::Cancelled,
                ));
                continue;
            }

            let outcome = self
                .execute_attempt_archived(
                    &prepared,
                    attempt,
                    cancellation,
                    archive,
                    u64::try_from(index).unwrap_or(u64::MAX),
                    &mut progress,
                )
                .await?;
            let observed_cancellation = outcome.observed_cancellation();
            attempts.push(outcome);
            if observed_cancellation {
                termination = ResponseTermination::Cancelled;
                cancellation_observed = true;
            }
        }

        let run_record = request_run_record(&prepared, &policy_ref, termination, &attempts)
            .map_err(|source| ArchivedRequestError::InvalidRequestRunRecord {
                request_id,
                progress: Box::new(progress.clone()),
                source: Box::new(source),
            })?;
        let response = Response::new(&prepared, attempts, termination);
        let request_run_ref = match archive.write(&run_record).await {
            Ok(reference) => reference,
            Err(source) => {
                return Err(ArchivedRequestError::RequestRunPublication {
                    response: Box::new(response),
                    pending_record: Box::new(run_record),
                    source: Box::new(source),
                });
            }
        };
        Ok(ArchivedResponse::new(response, policy_ref, request_run_ref))
    }

    #[allow(
        clippy::too_many_arguments,
        reason = "the archived attempt boundary keeps ordering, cancellation, and persistence explicit"
    )]
    async fn execute_attempt_archived(
        &self,
        prepared: &PreparedPageRequest,
        attempt: &PreparedAttempt,
        cancellation: &CancellationToken,
        archive: &Archive,
        attempt_index: u64,
        progress: &mut ArchivedRequestProgress,
    ) -> Result<AttemptOutcome, ArchivedRequestError> {
        let Some(context) = self.context_for(attempt) else {
            return Ok(AttemptOutcome::failed(
                prepared,
                attempt,
                AttemptFailureKind::MissingExecutionContext,
                AttemptDiagnostic::MissingExecutionContext,
                None,
                None,
                None,
                None,
                None,
            ));
        };
        let resolved = match PolicyResolver::resolve(prepared, attempt, context) {
            Ok(resolved) => resolved,
            Err(error) => {
                return Ok(AttemptOutcome::failed(
                    prepared,
                    attempt,
                    AttemptFailureKind::PolicyResolution,
                    AttemptDiagnostic::PolicyResolutionFailed,
                    Some(error),
                    None,
                    None,
                    None,
                    None,
                ));
            }
        };
        let capture = match resolved.execute(cancellation).await {
            Ok(capture) => capture,
            Err(error) => {
                let (diagnostic, facts) = execution_failure_facts(&error);
                return Ok(AttemptOutcome::failed(
                    prepared,
                    attempt,
                    AttemptFailureKind::CaptureExecution,
                    diagnostic,
                    None,
                    Some(error.applied_policy().clone()),
                    None,
                    facts,
                    None,
                ));
            }
        };

        let capture_metadata = capture.bundle().capture().clone();
        let applied_policy = capture.applied_policy().clone();
        let response_status = capture
            .direct_http_capture()
            .map(|direct_http| direct_http.response().status());
        let capture_facts = AttemptCaptureFacts::from_capture(&capture_metadata, response_status);
        let capture_ref = archive.write(capture.bundle()).await.map_err(|source| {
            ArchivedRequestError::CapturePublication {
                request_id: prepared.id(),
                attempt_index,
                capture_id: attempt.capture_id(),
                progress: Box::new(progress.clone()),
                capture_facts: Box::new(capture_facts),
                source: Box::new(source),
            }
        })?;
        progress.commit_capture(capture_ref.clone());

        let Ok(projected) = project_attempt(capture, prepared, attempt) else {
            return Ok(AttemptOutcome::failed(
                prepared,
                attempt,
                AttemptFailureKind::Projection,
                AttemptDiagnostic::ProjectionFailed,
                None,
                Some(applied_policy),
                Some(capture_ref),
                None,
                Some(AttemptCaptureFacts::from_capture(
                    &capture_metadata,
                    response_status,
                )),
            ));
        };
        let mut document_refs = Vec::with_capacity(projected.documents().len());
        for (index, outcome) in projected.documents().iter().enumerate() {
            let Some(document) = outcome.document() else {
                document_refs.push(None);
                continue;
            };
            let reference = archive
                .write(document.archive_value())
                .await
                .map_err(|source| ArchivedRequestError::DocumentPublication {
                    request_id: prepared.id(),
                    attempt_index,
                    document_index: u64::try_from(index).unwrap_or(u64::MAX),
                    progress: Box::new(progress.clone()),
                    source: Box::new(source),
                })?;
            progress.commit_document(&capture_ref, reference.clone());
            document_refs.push(Some(reference));
        }
        Ok(AttemptOutcome::completed(
            prepared,
            attempt,
            projected,
            Some(capture_ref),
            Some(&document_refs),
        ))
    }
}

impl PageRequest {
    /// Executes and explicitly archives Policy, Capture, normalized Documents,
    /// and the final RequestRunRecord before returning.
    ///
    /// Publication is multi-step. Post-Policy failures expose every committed
    /// reference through [`ArchivedRequestProgress`].
    pub async fn send_archived(
        &self,
        archive: &Archive,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let cancellation = CancellationToken::new();
        self.send_archived_cancellable(archive, &cancellation).await
    }

    /// Archived send with caller-owned cancellation.
    pub async fn send_archived_cancellable(
        &self,
        archive: &Archive,
        cancellation: &CancellationToken,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let prepared = self.prepare().map_err(RequestSendError::from)?;
        let executor = standard::for_prepared(&prepared).map_err(RequestSendError::from)?;
        executor
            .execute_prepared_archived(prepared, cancellation, archive)
            .await
    }

    /// Archived send with explicit execution contexts and cancellation.
    pub async fn send_archived_with(
        &self,
        archive: &Archive,
        executor: &RequestExecutor,
        cancellation: &CancellationToken,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let prepared = self.prepare().map_err(RequestSendError::from)?;
        executor
            .execute_prepared_archived(prepared, cancellation, archive)
            .await
    }
}

impl BoundPageRequest<'_> {
    /// Executes this explicitly bound request and archives its durable evidence.
    ///
    /// Publication is multi-step. Post-Policy failures expose every committed
    /// reference through [`ArchivedRequestProgress`].
    pub async fn send_archived(
        &self,
        archive: &Archive,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let cancellation = CancellationToken::new();
        self.send_archived_cancellable(archive, &cancellation).await
    }

    /// Archived bound send with caller-owned cancellation.
    pub async fn send_archived_cancellable(
        &self,
        archive: &Archive,
        cancellation: &CancellationToken,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let prepared = self.prepare().map_err(RequestSendError::from)?;
        let executor = standard::for_prepared(&prepared).map_err(RequestSendError::from)?;
        executor
            .execute_prepared_archived(prepared, cancellation, archive)
            .await
    }

    /// Archived bound send with explicit execution contexts and cancellation.
    pub async fn send_archived_with(
        &self,
        archive: &Archive,
        executor: &RequestExecutor,
        cancellation: &CancellationToken,
    ) -> Result<ArchivedResponse, ArchivedRequestError> {
        let prepared = self.prepare().map_err(RequestSendError::from)?;
        executor
            .execute_prepared_archived(prepared, cancellation, archive)
            .await
    }
}

fn request_run_record(
    prepared: &PreparedPageRequest,
    policy: &PolicyArchiveRef,
    termination: ResponseTermination,
    attempts: &[AttemptOutcome],
) -> Result<RequestRunRecord, yosoi_archive::RequestRunRecordError> {
    let records = prepared
        .attempts()
        .iter()
        .zip(attempts)
        .map(|(prepared_attempt, outcome)| attempt_record(prepared_attempt, outcome))
        .collect::<Result<Vec<_>, _>>()?;
    RequestRunRecord::try_new(
        prepared.id().activity_id(),
        prepared.target_origin(),
        policy.clone(),
        EffectivePolicyIdentityRecord::from_identity(prepared.effective_policy_identity()),
        match termination {
            ResponseTermination::Completed => RequestRunTermination::Completed,
            ResponseTermination::Cancelled => RequestRunTermination::Cancelled,
        },
        records,
    )
}

fn attempt_record(
    prepared: &PreparedAttempt,
    outcome: &AttemptOutcome,
) -> Result<RequestAttemptRecord, yosoi_archive::RequestRunRecordError> {
    let durable_outcome = match outcome {
        AttemptOutcome::Completed(result) => RequestAttemptOutcome::Completed {
            capture: result
                .capture_archive_ref()
                .cloned()
                .ok_or(yosoi_archive::RequestRunRecordError::CompletedCaptureMissing)?,
            response_status: result.transport().status(),
            documents: document_records(result.documents())?,
        },
        AttemptOutcome::Failed(failure) => RequestAttemptOutcome::Failed {
            kind: failure_kind(failure.kind()),
            diagnostic: diagnostic(failure.diagnostic()),
            capture: failure.capture_archive_ref().cloned(),
            response_status: failure
                .capture_facts()
                .and_then(AttemptCaptureFacts::response_status)
                .or_else(|| {
                    failure
                        .capture_failure_facts()
                        .and_then(super::AttemptCaptureFailureFacts::response_status)
                }),
        },
        AttemptOutcome::NotStarted(_) => RequestAttemptOutcome::NotStarted {
            reason: RequestNotStartedReason::Cancelled,
        },
    };
    RequestAttemptRecord::try_new(
        prepared.capture_id(),
        prepared.kind(),
        match prepared.authored_selection() {
            DocumentSelectionKind::Current => AuthoredDocumentSelection::Current,
            DocumentSelectionKind::Exact => AuthoredDocumentSelection::Exact,
        },
        prepared.documents().to_vec(),
        durable_outcome,
    )
}
