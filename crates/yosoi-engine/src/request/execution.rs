//! Serial execution of the acquisitions authored by one page request.

use std::fmt;

use tokio_util::sync::CancellationToken;
use yosoi_policy::policy::AcquisitionKind;
pub use yosoi_types::{BrowserMode, CaptureOffset, CaptureReceipt, ReasonCode};
pub use yosoi_web_capture::{
    BrowserDocumentScope, CaptureCompleteness, CaptureObservation, CaptureTermination,
    CleanupState, Observation, RedirectHop, ResolvedWebUrl, WebArtifactFamily,
};
pub use yosoi_web_capture_direct_http::{
    DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind,
};

pub use crate::resolution::{BrowserResolutionInputs, DirectHttpResolutionInputs};

use crate::{
    BoundPageRequest, PageRequest, PolicyCaptureExecutionError, PolicyResolver, PreparedAttempt,
    PreparedPageRequest, project_attempt, resolution::PolicyResolutionContext,
};

mod archive;
#[cfg(feature = "browser")]
mod browser_diagnostic;
#[cfg(feature = "browser")]
use browser_diagnostic::browser_error_diagnostic;
mod outcome;
mod standard;
pub use outcome::{
    ArchivedCaptureProgress, ArchivedRequestError, ArchivedRequestProgress, ArchivedResponse,
    ArtifactDisposition, ArtifactFamilyDisposition, AttemptCaptureFacts,
    AttemptCaptureFailureFacts, AttemptDiagnostic, AttemptDocumentOutcome, AttemptFailure,
    AttemptFailureKind, AttemptOutcome, AttemptResult, AttemptTransportOutcome,
    BrowserDocumentObservation, BrowserFailureReason, BrowserTerminalClassification,
    BrowserTerminalFacts, NotStartedAttempt, NotStartedReason, RequestSendError, Response,
    ResponseTermination,
};
pub use standard::StandardExecutionSetupError;

pub(crate) fn direct_http_executor_with_user_agent(
    user_agent: yosoi_web_capture::UserAgent,
) -> Result<RequestExecutor, StandardExecutionSetupError> {
    let mut inputs = standard::direct_http_inputs()?;
    inputs.acquisition = inputs.acquisition.with_user_agent(user_agent);
    Ok(RequestExecutor::new().with_direct_http(inputs))
}

/// Reusable capture contexts for explicit, advanced request execution.
///
/// This value configures the existing adapters; it does not own or create an
/// HTTP client, browser, or browser lifecycle. The standard [`PageRequest::send`]
/// path constructs package-owned contexts. Browser attempts through
/// [`PageRequest::send_with`] use caller-supplied navigation context and
/// certified capabilities.
#[derive(Clone, Default)]
pub struct RequestExecutor {
    direct_http: Option<DirectHttpResolutionInputs>,
    browser_headless: Option<BrowserResolutionInputs>,
    browser_headful: Option<BrowserResolutionInputs>,
}

impl RequestExecutor {
    /// Creates an executor with no acquisition-specific configuration.
    pub const fn new() -> Self {
        Self {
            direct_http: None,
            browser_headless: None,
            browser_headful: None,
        }
    }

    /// Supplies reusable inputs for Direct HTTP attempts.
    pub fn with_direct_http(mut self, inputs: DirectHttpResolutionInputs) -> Self {
        self.direct_http = Some(inputs);
        self
    }

    /// Supplies reusable navigation context and certification for one browser mode.
    pub fn with_browser(mut self, mode: BrowserMode, inputs: BrowserResolutionInputs) -> Self {
        match mode {
            BrowserMode::Headless => self.browser_headless = Some(inputs),
            BrowserMode::Headful => self.browser_headful = Some(inputs),
        }
        self
    }

    pub(crate) async fn execute_prepared(
        &self,
        prepared: PreparedPageRequest,
        cancellation: &CancellationToken,
    ) -> Response {
        let mut attempts = Vec::with_capacity(prepared.attempts().len());
        let mut termination = if cancellation.is_cancelled() {
            ResponseTermination::Cancelled
        } else {
            ResponseTermination::Completed
        };
        let mut cancellation_observed = cancellation.is_cancelled();

        for attempt in prepared.attempts() {
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

            let outcome = self.execute_attempt(&prepared, attempt, cancellation).await;
            let observed_cancellation = outcome.observed_cancellation();
            attempts.push(outcome);
            if observed_cancellation {
                termination = ResponseTermination::Cancelled;
                cancellation_observed = true;
            }
        }

        Response::new(&prepared, attempts, termination)
    }

    async fn execute_attempt(
        &self,
        prepared: &PreparedPageRequest,
        attempt: &PreparedAttempt,
        cancellation: &CancellationToken,
    ) -> AttemptOutcome {
        let Some(context) = self.context_for(attempt) else {
            return AttemptOutcome::failed(
                prepared,
                attempt,
                AttemptFailureKind::MissingExecutionContext,
                AttemptDiagnostic::MissingExecutionContext,
                None,
                None,
                None,
                None,
                None,
            );
        };

        let resolved = match PolicyResolver::resolve(prepared, attempt, context) {
            Ok(resolved) => resolved,
            Err(error) => {
                return AttemptOutcome::failed(
                    prepared,
                    attempt,
                    AttemptFailureKind::PolicyResolution,
                    AttemptDiagnostic::PolicyResolutionFailed,
                    Some(error),
                    None,
                    None,
                    None,
                    None,
                );
            }
        };

        let capture = match resolved.execute(cancellation).await {
            Ok(capture) => capture,
            Err(error) => {
                let (diagnostic, facts) = execution_failure_facts(&error);
                return AttemptOutcome::failed(
                    prepared,
                    attempt,
                    AttemptFailureKind::CaptureExecution,
                    diagnostic,
                    None,
                    Some(error.applied_policy().clone()),
                    None,
                    facts,
                    None,
                );
            }
        };

        let capture_metadata = capture.bundle().capture().clone();
        let applied_policy = capture.applied_policy().clone();
        let response_status = capture
            .direct_http_capture()
            .map(|direct_http| direct_http.response().status());
        let Ok(projected) = project_attempt(capture, prepared, attempt) else {
            return AttemptOutcome::failed(
                prepared,
                attempt,
                AttemptFailureKind::Projection,
                AttemptDiagnostic::ProjectionFailed,
                None,
                Some(applied_policy),
                None,
                None,
                Some(AttemptCaptureFacts::from_capture(
                    &capture_metadata,
                    response_status,
                )),
            );
        };

        AttemptOutcome::completed(prepared, attempt, projected, None, None)
    }

    fn context_for(&self, attempt: &PreparedAttempt) -> Option<PolicyResolutionContext> {
        match attempt.kind() {
            AcquisitionKind::DirectHttp => self
                .direct_http
                .clone()
                .map(PolicyResolutionContext::direct_http),
            AcquisitionKind::Browser { mode } => self.browser_for_mode(mode).map(|mut inputs| {
                inputs.identity_plan = inputs
                    .identity_plan
                    .with_activity(attempt.capture_id().activity_id());
                PolicyResolutionContext::browser(inputs)
            }),
        }
    }

    fn browser_for_mode(&self, mode: BrowserMode) -> Option<BrowserResolutionInputs> {
        match mode {
            BrowserMode::Headless => self.browser_headless.clone(),
            BrowserMode::Headful => self.browser_headful.clone(),
        }
    }
}

impl fmt::Debug for RequestExecutor {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("RequestExecutor")
            .field("direct_http_configured", &self.direct_http.is_some())
            .field("headless_configured", &self.browser_headless.is_some())
            .field("headful_configured", &self.browser_headful.is_some())
            .finish()
    }
}

impl PageRequest {
    /// Executes each authored acquisition using the standard package adapters.
    pub async fn send(&self) -> Result<Response, RequestSendError> {
        let cancellation = CancellationToken::new();
        self.send_cancellable(&cancellation).await
    }

    /// Executes with standard package adapters and caller-controlled cancellation.
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        let prepared = self.prepare()?;
        let executor = standard::for_prepared(&prepared)?;
        Ok(executor.execute_prepared(prepared, cancellation).await)
    }

    /// Executes each authored acquisition through caller-supplied reusable contexts.
    pub async fn send_with(
        &self,
        executor: &RequestExecutor,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        let prepared = self.prepare()?;
        Ok(executor.execute_prepared(prepared, cancellation).await)
    }
}

impl BoundPageRequest<'_> {
    /// Executes each authored acquisition using the standard package adapters.
    pub async fn send(&self) -> Result<Response, RequestSendError> {
        let cancellation = CancellationToken::new();
        self.send_cancellable(&cancellation).await
    }

    /// Executes with standard package adapters and caller-controlled cancellation.
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        let prepared = self.prepare()?;
        let executor = standard::for_prepared(&prepared)?;
        Ok(executor.execute_prepared(prepared, cancellation).await)
    }

    /// Executes each authored acquisition through caller-supplied reusable contexts.
    pub async fn send_with(
        &self,
        executor: &RequestExecutor,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        let prepared = self.prepare()?;
        Ok(executor.execute_prepared(prepared, cancellation).await)
    }
}

fn execution_failure_facts(
    error: &crate::PolicyCaptureError,
) -> (AttemptDiagnostic, Option<AttemptCaptureFailureFacts>) {
    match error.execution_error() {
        PolicyCaptureExecutionError::DirectHttp(source) => match source.as_ref() {
            yosoi_web_capture_direct_http::DirectHttpCaptureError::Transport(failure) => (
                AttemptDiagnostic::DirectHttpTransport(failure.error().kind()),
                Some(AttemptCaptureFailureFacts::direct_http(
                    failure.resolution().cloned(),
                    failure.lifecycle().termination().cloned(),
                    failure.response_status(),
                    Some(failure.error().kind()),
                )),
            ),
            yosoi_web_capture_direct_http::DirectHttpCaptureError::Body(failure) => (
                AttemptDiagnostic::DirectHttpBodyFailed,
                Some(AttemptCaptureFailureFacts::direct_http(
                    Some(failure.resolution().clone()),
                    failure.lifecycle().termination().cloned(),
                    Some(failure.facts().status()),
                    None,
                )),
            ),
            yosoi_web_capture_direct_http::DirectHttpCaptureError::Finalization {
                evidence,
                ..
            } => (
                AttemptDiagnostic::DirectHttpFinalizationFailed,
                Some(AttemptCaptureFailureFacts::direct_http(
                    evidence.resolution().cloned(),
                    None,
                    evidence
                        .response()
                        .map(yosoi_web_capture_direct_http::DirectHttpResponseFacts::status),
                    None,
                )),
            ),
        },
        #[cfg(feature = "browser")]
        PolicyCaptureExecutionError::Browser(source) => {
            let (diagnostic, cleanup) = browser_error_diagnostic(source);
            (
                diagnostic,
                cleanup.map(|cleanup| {
                    AttemptCaptureFailureFacts::browser_before_finalization(Some(cleanup))
                }),
            )
        }
        PolicyCaptureExecutionError::BrowserFinalization { evidence, .. } => {
            let terminal = BrowserTerminalFacts::from_adapter(
                evidence.terminal().at(),
                evidence.terminal().kind(),
            );
            let termination = evidence
                .lifecycle()
                .and_then(|lifecycle| lifecycle.termination().cloned());
            (
                AttemptDiagnostic::BrowserFinalizationFailed,
                Some(AttemptCaptureFailureFacts::browser(
                    termination,
                    terminal,
                    evidence.facts().cleanup(),
                    evidence.facts().main_document_status(),
                )),
            )
        }
        PolicyCaptureExecutionError::BrowserFeatureDisabled => {
            (AttemptDiagnostic::BrowserFeatureDisabled, None)
        }
    }
}

#[cfg(all(test, feature = "browser"))]
mod browser_diagnostic_tests;
