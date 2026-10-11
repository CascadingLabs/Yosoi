//! Serial execution of the acquisitions authored by one page request.

use std::fmt;

pub use crate::internal::direct_http::{DirectHttpRedirectErrorKind, DirectHttpTransportErrorKind};
use crate::internal::policy::policy::AcquisitionKind;
pub use crate::internal::types::{BrowserMode, CaptureOffset, CaptureReceipt, ReasonCode};
pub use crate::internal::web_capture::{
    BrowserDocumentScope, CaptureCompleteness, CaptureObservation, CaptureTermination,
    CleanupState, Observation, RedirectHop, ResolvedWebUrl, WebArtifactFamily,
};
use tokio_util::sync::CancellationToken;

pub use crate::internal::engine::resolution::{
    BrowserResolutionInputs, DirectHttpResolutionInputs,
};

use crate::internal::engine::{
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

pub(in crate::internal::engine) fn direct_http_executor_with_user_agent(
    user_agent: crate::internal::web_capture::UserAgent,
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

    pub(in crate::internal::engine) async fn execute_prepared(
        &self,
        prepared: PreparedPageRequest,
        cancellation: &CancellationToken,
    ) -> Response {
        self.execute_prepared_using(
            prepared,
            cancellation,
            #[cfg(feature = "browser")]
            None,
        )
        .await
    }

    #[cfg(feature = "browser")]
    async fn execute_prepared_on_control(
        &self,
        prepared: PreparedPageRequest,
        cancellation: &CancellationToken,
        control: &crate::internal::web_capture::RuntimeBrowserControl,
    ) -> Response {
        self.execute_prepared_using(prepared, cancellation, Some(control))
            .await
    }

    async fn execute_prepared_using(
        &self,
        prepared: PreparedPageRequest,
        cancellation: &CancellationToken,
        #[cfg(feature = "browser")] control: Option<
            &crate::internal::web_capture::RuntimeBrowserControl,
        >,
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

            let outcome = self
                .execute_attempt(
                    &prepared,
                    attempt,
                    cancellation,
                    #[cfg(feature = "browser")]
                    control,
                )
                .await;
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
        #[cfg(feature = "browser")] control: Option<
            &crate::internal::web_capture::RuntimeBrowserControl,
        >,
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

        #[cfg(feature = "browser")]
        let executed = match control {
            Some(control) => {
                resolved
                    .execute_on_browser_control(control, cancellation)
                    .await
            }
            None => resolved.execute(cancellation).await,
        };
        #[cfg(not(feature = "browser"))]
        let executed = resolved.execute(cancellation).await;
        let capture = match executed {
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
    #[cfg(feature = "browser")]
    pub async fn send_on_browser_control(
        &self,
        control: &crate::internal::web_capture::RuntimeBrowserControl,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        let prepared = self.prepare()?;
        let executor = standard::for_prepared(&prepared)?;
        Ok(executor
            .execute_prepared_on_control(prepared, cancellation, control)
            .await)
    }

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
    error: &crate::internal::engine::PolicyCaptureError,
) -> (AttemptDiagnostic, Option<AttemptCaptureFailureFacts>) {
    match error.execution_error() {
        PolicyCaptureExecutionError::DirectHttp(source) => match source.as_ref() {
            crate::internal::direct_http::DirectHttpCaptureError::Transport(failure) => (
                AttemptDiagnostic::DirectHttpTransport(failure.error().kind()),
                Some(AttemptCaptureFailureFacts::direct_http(
                    failure.resolution().cloned(),
                    failure.lifecycle().termination().cloned(),
                    failure.response_status(),
                    Some(failure.error().kind()),
                )),
            ),
            crate::internal::direct_http::DirectHttpCaptureError::Body(failure) => (
                AttemptDiagnostic::DirectHttpBodyFailed,
                Some(AttemptCaptureFailureFacts::direct_http(
                    Some(failure.resolution().clone()),
                    failure.lifecycle().termination().cloned(),
                    Some(failure.facts().status()),
                    None,
                )),
            ),
            crate::internal::direct_http::DirectHttpCaptureError::Finalization {
                evidence, ..
            } => (
                AttemptDiagnostic::DirectHttpFinalizationFailed,
                Some(AttemptCaptureFailureFacts::direct_http(
                    evidence.resolution().cloned(),
                    None,
                    evidence
                        .response()
                        .map(crate::internal::direct_http::DirectHttpResponseFacts::status),
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
