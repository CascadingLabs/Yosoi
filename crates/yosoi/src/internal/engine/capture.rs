use crate::browser as browser_config;
use crate::internal::direct_http as internal_direct_http;
#[cfg(feature = "browser")]
use crate::internal::engine::session as internal_engine_session;
use crate::internal::web_capture as internal_web_capture;
use std::fmt;
#[cfg(feature = "browser")]
use std::time as std_time;
#[cfg(feature = "browser")]
use std::time::{Duration, SystemTime};
#[cfg(feature = "browser")]
use tokio::time as tokio_time;

use crate::internal::direct_http::{
    DirectHttpCapture, DirectHttpCaptureError, capture_direct_http_with_redirect_policy,
};
use crate::internal::web_capture::{
    BrowserAdapterResult, BrowserFinalizationError, CaptureBundle, CleanupState,
};
#[cfg(feature = "browser")]
use crate::internal::web_capture::{BrowserFinalizationInput, Observation};
use thiserror::Error;
use tokio_util::sync::CancellationToken;

use crate::internal::engine::resolution::{
    AppliedPolicy, ResolvedPolicyAttempt, ResolvedPolicySpec,
};

/// Completed outcome of one prepared policy capture.
pub enum PolicyCaptureOutcome {
    /// Full Direct HTTP result, including response and source-interpretation facts.
    DirectHttp(Box<DirectHttpCapture>),
    /// Finalized browser bundle and the observed unmanaged-session cleanup state.
    Browser {
        /// Browser capture metadata and retained artifact payloads.
        bundle: Box<CaptureBundle>,
        /// Cleanup state observed before browser finalization consumed its result.
        cleanup: CleanupState,
        /// Main-document response status observed by the browser, when available.
        status: Option<u16>,
    },
}

impl fmt::Debug for PolicyCaptureOutcome {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DirectHttp(capture) => formatter
                .debug_struct("PolicyCaptureOutcome::DirectHttp")
                .field("status", &capture.response().status())
                .field("completeness", &capture.bundle().capture().completeness())
                .field("payloads", &"<redacted>")
                .finish(),
            Self::Browser {
                bundle,
                cleanup,
                status,
            } => formatter
                .debug_struct("PolicyCaptureOutcome::Browser")
                .field("completeness", &bundle.capture().completeness())
                .field("cleanup", cleanup)
                .field("status", status)
                .field("payloads", &"<redacted>")
                .finish(),
        }
    }
}

/// Successful capture bundle together with its applied policy explanation.
pub struct PolicyCapture {
    applied_policy: AppliedPolicy,
    outcome: PolicyCaptureOutcome,
}

impl fmt::Debug for PolicyCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PolicyCapture")
            .field("applied_policy", &self.applied_policy)
            .field("outcome", &self.outcome)
            .finish()
    }
}

impl PolicyCapture {
    pub(in crate::internal::engine) const fn new(
        applied_policy: AppliedPolicy,
        outcome: PolicyCaptureOutcome,
    ) -> Self {
        Self {
            applied_policy,
            outcome,
        }
    }

    /// Returns the policy identity, decisions, and limits used for this capture.
    pub const fn applied_policy(&self) -> &AppliedPolicy {
        &self.applied_policy
    }

    /// Returns the full acquisition-specific success result.
    pub const fn outcome(&self) -> &PolicyCaptureOutcome {
        &self.outcome
    }

    /// Returns the common retained-payload bundle.
    pub const fn bundle(&self) -> &CaptureBundle {
        match &self.outcome {
            PolicyCaptureOutcome::DirectHttp(capture) => capture.bundle(),
            PolicyCaptureOutcome::Browser { bundle, .. } => bundle,
        }
    }

    /// Returns the Direct HTTP result and its response facts, when applicable.
    pub const fn direct_http_capture(&self) -> Option<&DirectHttpCapture> {
        match &self.outcome {
            PolicyCaptureOutcome::DirectHttp(capture) => Some(capture),
            PolicyCaptureOutcome::Browser { .. } => None,
        }
    }

    /// Returns the observed browser cleanup state for unmanaged browser capture.
    pub const fn browser_cleanup(&self) -> Option<CleanupState> {
        match &self.outcome {
            PolicyCaptureOutcome::DirectHttp(_) => None,
            PolicyCaptureOutcome::Browser { cleanup, .. } => Some(*cleanup),
        }
    }

    /// Returns the browser-observed main-document response status, when available.
    pub const fn browser_status(&self) -> Option<u16> {
        match &self.outcome {
            PolicyCaptureOutcome::DirectHttp(_) => None,
            PolicyCaptureOutcome::Browser { status, .. } => *status,
        }
    }

    /// Separates the applied policy from the acquisition-specific outcome.
    pub fn into_parts(self) -> (AppliedPolicy, PolicyCaptureOutcome) {
        (self.applied_policy, self.outcome)
    }
}

/// Acquisition-specific execution failure with the policy snapshot retained.
#[derive(Error)]
pub enum PolicyCaptureExecutionError {
    /// Direct HTTP failed while preserving its typed transport/body evidence.
    #[error("Direct HTTP capture failed")]
    DirectHttp(#[source] Box<DirectHttpCaptureError>),
    /// Browser adapter execution failed with its terminal execution evidence.
    #[cfg(feature = "browser")]
    #[error("browser capture failed")]
    Browser(#[source] Box<internal_web_capture::VoidCrawlAdapterError>),
    /// Browser finalization failed; the original adapter result remains available.
    #[error("browser capture finalization failed")]
    BrowserFinalization {
        #[source]
        source: BrowserFinalizationError,
        evidence: Box<BrowserAdapterResult>,
    },
    /// The selected spec requires a browser build feature that is disabled.
    #[error("browser capture requires the yosoi browser feature")]
    BrowserFeatureDisabled,
}

impl fmt::Debug for PolicyCaptureExecutionError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DirectHttp(_) => formatter
                .debug_tuple("PolicyCaptureExecutionError::DirectHttp")
                .field(&"<redacted evidence>")
                .finish(),
            #[cfg(feature = "browser")]
            Self::Browser(_) => formatter
                .debug_tuple("PolicyCaptureExecutionError::Browser")
                .field(&"<redacted evidence>")
                .finish(),
            Self::BrowserFinalization { source, .. } => formatter
                .debug_struct("PolicyCaptureExecutionError::BrowserFinalization")
                .field("source", &source.to_string())
                .field("evidence", &"<redacted>")
                .finish(),
            Self::BrowserFeatureDisabled => {
                formatter.write_str("PolicyCaptureExecutionError::BrowserFeatureDisabled")
            }
        }
    }
}

impl PolicyCaptureExecutionError {
    /// Returns the bounded browser adapter result retained after finalization failure.
    pub fn browser_evidence(&self) -> Option<&BrowserAdapterResult> {
        match self {
            Self::BrowserFinalization { evidence, .. } => Some(evidence),
            Self::DirectHttp(_) | Self::BrowserFeatureDisabled => None,
            #[cfg(feature = "browser")]
            Self::Browser(_) => None,
        }
    }
}

/// Execution failure after policy resolution produced a complete attempt spec.
#[derive(Error)]
pub enum PolicyCaptureError {
    /// The prepared attempt failed in its acquisition engine or finalizer.
    #[error("policy capture execution failed")]
    Execution {
        /// The policy identity and decisions used to prepare the engine spec.
        applied_policy: AppliedPolicy,
        #[source]
        source: Box<PolicyCaptureExecutionError>,
    },
}

impl fmt::Debug for PolicyCaptureError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Execution {
                applied_policy,
                source,
            } => formatter
                .debug_struct("PolicyCaptureError::Execution")
                .field("applied_policy", applied_policy)
                .field("source", source)
                .finish(),
        }
    }
}

impl PolicyCaptureError {
    /// Returns the policy identity and decisions attached to this failed execution.
    pub const fn applied_policy(&self) -> &AppliedPolicy {
        match self {
            Self::Execution { applied_policy, .. } => applied_policy,
        }
    }

    /// Returns the acquisition-specific cause for an execution failure.
    pub fn execution_error(&self) -> &PolicyCaptureExecutionError {
        match self {
            Self::Execution { source, .. } => source.as_ref(),
        }
    }
}

impl ResolvedPolicyAttempt {
    #[cfg(feature = "browser")]
    pub async fn execute_on_browser_control(
        self,
        control: &internal_web_capture::RuntimeBrowserControl,
        cancellation: &CancellationToken,
    ) -> Result<PolicyCapture, PolicyCaptureError> {
        let (spec, applied_policy) = self.into_parts();
        match spec {
            ResolvedPolicySpec::DirectHttp {
                spec,
                redirect_targets,
            } => {
                Box::pin(execute_direct_http(
                    spec,
                    redirect_targets,
                    applied_policy,
                    cancellation,
                ))
                .await
            }
            ResolvedPolicySpec::Browser(spec) => {
                Box::pin(execute_browser_on_control(
                    spec,
                    applied_policy,
                    cancellation,
                    control,
                ))
                .await
            }
        }
    }

    /// Executes this prepared canonical spec without rereading policy or context.
    pub async fn execute(
        self,
        cancellation: &CancellationToken,
    ) -> Result<PolicyCapture, PolicyCaptureError> {
        #[cfg(feature = "browser")]
        let browser = self.browser_config().clone();
        let (spec, applied_policy) = self.into_parts();
        match spec {
            ResolvedPolicySpec::DirectHttp {
                spec,
                redirect_targets,
            } => {
                Box::pin(execute_direct_http(
                    spec,
                    redirect_targets,
                    applied_policy,
                    cancellation,
                ))
                .await
            }
            ResolvedPolicySpec::Browser(spec) => {
                #[cfg(feature = "browser")]
                {
                    Box::pin(execute_browser(spec, applied_policy, browser, cancellation)).await
                }
                #[cfg(not(feature = "browser"))]
                {
                    let _ = (spec, cancellation);
                    Err(PolicyCaptureError::Execution {
                        applied_policy,
                        source: Box::new(PolicyCaptureExecutionError::BrowserFeatureDisabled),
                    })
                }
            }
        }
    }
}

async fn execute_direct_http(
    spec: Box<internal_direct_http::ResolvedDirectHttpCaptureSpec>,
    redirect_targets: internal_direct_http::DirectHttpRedirectTargetPolicy,
    applied_policy: AppliedPolicy,
    cancellation: &CancellationToken,
) -> Result<PolicyCapture, PolicyCaptureError> {
    let capture = Box::pin(capture_direct_http_with_redirect_policy(
        *spec,
        cancellation,
        redirect_targets,
    ))
    .await;
    match capture {
        Ok(capture) => Ok(PolicyCapture::new(
            applied_policy,
            PolicyCaptureOutcome::DirectHttp(Box::new(capture)),
        )),
        Err(source) => Err(PolicyCaptureError::Execution {
            applied_policy,
            source: Box::new(PolicyCaptureExecutionError::DirectHttp(Box::new(source))),
        }),
    }
}

#[cfg(feature = "browser")]
async fn execute_browser(
    spec: Box<internal_web_capture::ResolvedBrowserCaptureSpec>,
    applied_policy: AppliedPolicy,
    browser: browser_config::BrowserConfig,
    cancellation: &CancellationToken,
) -> Result<PolicyCapture, PolicyCaptureError> {
    let mode = spec.environment().mode();
    let started = std_time::Instant::now();
    let started_at: chrono::DateTime<chrono::Utc> = SystemTime::now().into();
    let maximum = Duration::from_micros(
        spec.observation()
            .limits()
            .maximum_elapsed()
            .as_microseconds(),
    );
    let acquiring = cancellation.child_token();
    let _cancel_acquisition = acquiring.clone().drop_guard();
    let acquired = tokio_time::timeout(
        maximum,
        internal_engine_session::BrowserSession::acquire(
            browser,
            mode,
            1,
            false,
            &spec.network,
            &acquiring,
        ),
    )
    .await
    .map_err(|_| PolicyCaptureError::Execution {
        applied_policy: applied_policy.clone(),
        source: Box::new(PolicyCaptureExecutionError::Browser(Box::new(
            internal_web_capture::VoidCrawlAdapterError::DeadlineBeforeOwnership,
        ))),
    })?;
    let session = acquired.map_err(|source| PolicyCaptureError::Execution {
        applied_policy: applied_policy.clone(),
        source: Box::new(PolicyCaptureExecutionError::Browser(Box::new(source))),
    })?;
    let remaining = maximum.saturating_sub(started.elapsed());
    let result = match session.control(&session.initial_tab(), remaining).await {
        Ok(control) => {
            execute_browser_on_control_started(
                spec,
                applied_policy.clone(),
                cancellation,
                &control,
                started,
                started_at,
            )
            .await
        }
        Err(error) => Err(PolicyCaptureError::Execution {
            applied_policy: applied_policy.clone(),
            source: Box::new(PolicyCaptureExecutionError::Browser(Box::new(
                internal_engine_session::control_error(&error),
            ))),
        }),
    };
    let cleanup = session.close().await;
    drop(session);
    match (result, cleanup) {
        (Ok(capture), Ok(())) => Ok(capture),
        (Err(error), _) => Err(error),
        (Ok(_), Err(error)) => Err(PolicyCaptureError::Execution {
            applied_policy,
            source: Box::new(PolicyCaptureExecutionError::Browser(Box::new(error.into()))),
        }),
    }
}

#[cfg(feature = "browser")]
async fn execute_browser_on_control(
    spec: Box<internal_web_capture::ResolvedBrowserCaptureSpec>,
    applied_policy: AppliedPolicy,
    cancellation: &CancellationToken,
    control: &internal_web_capture::RuntimeBrowserControl,
) -> Result<PolicyCapture, PolicyCaptureError> {
    execute_browser_on_control_started(
        spec,
        applied_policy,
        cancellation,
        control,
        std_time::Instant::now(),
        SystemTime::now().into(),
    )
    .await
}

#[cfg(feature = "browser")]
async fn execute_browser_on_control_started(
    spec: Box<internal_web_capture::ResolvedBrowserCaptureSpec>,
    applied_policy: AppliedPolicy,
    cancellation: &CancellationToken,
    control: &internal_web_capture::RuntimeBrowserControl,
    started: std_time::Instant,
    started_at: chrono::DateTime<chrono::Utc>,
) -> Result<PolicyCapture, PolicyCaptureError> {
    let result = match Box::pin(internal_web_capture::capture_attempt_on_control_started(
        control,
        &spec,
        cancellation,
        started,
        started_at,
    ))
    .await
    {
        Ok(result) => result,
        Err(source) => {
            return Err(PolicyCaptureError::Execution {
                applied_policy,
                source: Box::new(PolicyCaptureExecutionError::Browser(Box::new(source))),
            });
        }
    };
    let cleanup = result.facts().cleanup();
    let status = result.facts().main_document_status();
    let evidence = result.clone();
    let finished_at: chrono::DateTime<chrono::Utc> = SystemTime::now().into();
    let input = BrowserFinalizationInput {
        finished_at,
        resource_origin: Observation::Unobserved,
        initiator_origin: Observation::Unobserved,
    };
    match internal_web_capture::finalize_browser_capture(result, input) {
        Ok(bundle) => Ok(PolicyCapture::new(
            applied_policy,
            PolicyCaptureOutcome::Browser {
                bundle: Box::new(bundle),
                cleanup,
                status,
            },
        )),
        Err(source) => Err(PolicyCaptureError::Execution {
            applied_policy,
            source: Box::new(PolicyCaptureExecutionError::BrowserFinalization {
                source,
                evidence: Box::new(evidence),
            }),
        }),
    }
}
