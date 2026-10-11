mod applied;
mod browser;
mod direct_http;
mod error;
mod inputs;

use std::fmt;

pub use applied::{AppliedPolicy, AppliedPolicyLimit, PolicyDecision};
pub use error::PolicyResolutionError;
pub use inputs::{
    BrowserResolutionInputs, DirectHttpResolutionInputs, PolicyResolutionContext,
    PolicyResolutionContextKind,
};

use crate::internal::direct_http::{DirectHttpRedirectTargetPolicy, ResolvedDirectHttpCaptureSpec};
use crate::internal::engine::{PreparedAttempt, PreparedPageRequest, policy::AcquisitionKind};
use crate::internal::web_capture::{
    ResolvedBrowserCaptureSpec, WebAcquisitionStrategy, WebCaptureRequest,
};

/// Resolved canonical capture specification selected by one prepared attempt.
#[derive(Eq, PartialEq)]
pub enum ResolvedPolicySpec {
    /// Direct HTTP spec and the separately consumed redirect-target policy.
    DirectHttp {
        /// Validated canonical Direct HTTP capture inputs.
        spec: Box<ResolvedDirectHttpCaptureSpec>,
        /// Engine-owned target admission rule used by CAS399 execution.
        redirect_targets: DirectHttpRedirectTargetPolicy,
    },
    /// Validated, certified browser capture inputs.
    Browser(Box<ResolvedBrowserCaptureSpec>),
}

impl fmt::Debug for ResolvedPolicySpec {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::DirectHttp {
                redirect_targets, ..
            } => formatter
                .debug_struct("ResolvedPolicySpec::DirectHttp")
                .field("target", &"<redacted>")
                .field("redirect_targets", redirect_targets)
                .finish_non_exhaustive(),
            Self::Browser(_) => formatter
                .debug_struct("ResolvedPolicySpec::Browser")
                .field("target", &"<redacted>")
                .finish_non_exhaustive(),
        }
    }
}

/// Canonical attempt spec and content-free policy decisions prepared together.
#[derive(Eq, PartialEq)]
pub struct ResolvedPolicyAttempt {
    spec: ResolvedPolicySpec,
    applied_policy: AppliedPolicy,
}

impl fmt::Debug for ResolvedPolicyAttempt {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResolvedPolicyAttempt")
            .field("spec", &self.spec)
            .field("applied_policy", &self.applied_policy)
            .finish()
    }
}

impl ResolvedPolicyAttempt {
    pub(in crate::internal::engine) const fn new(
        spec: ResolvedPolicySpec,
        applied_policy: AppliedPolicy,
    ) -> Self {
        Self {
            spec,
            applied_policy,
        }
    }

    /// Returns the canonical spec ready for its selected capture engine.
    pub const fn spec(&self) -> &ResolvedPolicySpec {
        &self.spec
    }

    /// Returns identity and content-free decisions for the resolved policy.
    pub const fn applied_policy(&self) -> &AppliedPolicy {
        &self.applied_policy
    }

    /// Separates the execution spec from its applied-policy explanation.
    pub fn into_parts(self) -> (ResolvedPolicySpec, AppliedPolicy) {
        (self.spec, self.applied_policy)
    }
}

/// Resolves one prepared attempt into an existing capture spec.
#[derive(Clone, Copy, Debug, Default)]
pub struct PolicyResolver;

impl PolicyResolver {
    /// Validates attempt ownership and acquisition/context agreement, then constructs one spec.
    pub fn resolve(
        prepared: &PreparedPageRequest,
        attempt: &PreparedAttempt,
        context: PolicyResolutionContext,
    ) -> Result<ResolvedPolicyAttempt, PolicyResolutionError> {
        if !prepared.attempts().contains(attempt) {
            return Err(PolicyResolutionError::PreparedAttemptNotInRequest);
        }

        let policy = prepared.effective_policy();
        let identity = prepared.effective_policy_identity();
        match (attempt.kind(), context) {
            (AcquisitionKind::DirectHttp, PolicyResolutionContext::DirectHttp(inputs)) => {
                direct_http::resolve(identity, policy, attempt, *inputs)
            }
            (AcquisitionKind::Browser { mode }, PolicyResolutionContext::Browser(inputs)) => {
                browser::resolve(identity, policy, attempt, mode, *inputs)
            }
            (policy_acquisition, supplied) => {
                Err(PolicyResolutionError::AcquisitionContextMismatch {
                    policy_acquisition,
                    supplied_context: supplied.kind(),
                })
            }
        }
    }
}

fn capture_request(
    attempt: &PreparedAttempt,
    strategy: WebAcquisitionStrategy,
) -> WebCaptureRequest {
    WebCaptureRequest::new(
        attempt.capture_id(),
        attempt.requested_target().clone(),
        strategy,
    )
}

fn applied_decisions(attempt: &PreparedAttempt) -> Vec<PolicyDecision> {
    let mut decisions = Vec::with_capacity(attempt.documents().len().saturating_add(2));
    decisions.push(PolicyDecision::AcquisitionSelected {
        acquisition: attempt.kind(),
    });
    decisions.push(PolicyDecision::DocumentSelection {
        selection: attempt.authored_selection(),
    });
    for document in attempt.documents() {
        decisions.push(PolicyDecision::DocumentRequested {
            document: *document,
        });
    }
    decisions
}
