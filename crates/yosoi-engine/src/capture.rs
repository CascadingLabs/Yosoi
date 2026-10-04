use std::fmt;
#[cfg(feature = "browser")]
use std::time::SystemTime;

use thiserror::Error;
use tokio_util::sync::CancellationToken;
use yosoi_web_capture::{
    BrowserAdapterResult, BrowserFinalizationError, CaptureBundle, CleanupState,
};
#[cfg(feature = "browser")]
use yosoi_web_capture::{BrowserFinalizationInput, Observation};
use yosoi_web_capture_direct_http::{
    DirectHttpCapture, DirectHttpCaptureError, capture_direct_http_with_redirect_policy,
};

use crate::resolution::{AppliedPolicy, ResolvedPolicyAttempt, ResolvedPolicySpec};

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
    pub(crate) const fn new(applied_policy: AppliedPolicy, outcome: PolicyCaptureOutcome) -> Self {
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
    Browser(#[source] Box<yosoi_web_capture::VoidCrawlAdapterError>),
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
    /// Executes this prepared canonical spec without rereading policy or context.
    pub async fn execute(
        self,
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
                #[cfg(feature = "browser")]
                {
                    Box::pin(execute_browser(spec, applied_policy, cancellation)).await
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
    spec: Box<yosoi_web_capture_direct_http::ResolvedDirectHttpCaptureSpec>,
    redirect_targets: yosoi_web_capture_direct_http::DirectHttpRedirectTargetPolicy,
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
    spec: Box<yosoi_web_capture::ResolvedBrowserCaptureSpec>,
    applied_policy: AppliedPolicy,
    cancellation: &CancellationToken,
) -> Result<PolicyCapture, PolicyCaptureError> {
    let result = match Box::pin(yosoi_web_capture::capture_attempt(&spec, cancellation)).await {
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
    match yosoi_web_capture::finalize_browser_capture(result, input) {
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
