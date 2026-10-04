use yosoi_types::Sha256Digest;
use yosoi_web_capture::{BrowserBudgetScope, BrowserByteDomain, BrowserLimitEnforcement};
use yosoi_web_capture_direct_http::{
    DirectHttpContentLimits, DirectHttpRedirectPolicy, DirectHttpRedirectTargetPolicy,
};

use crate::{
    EffectivePolicyIdentity,
    policy::{
        AccessibilityNodeLimit, AcquisitionKind, AddressableByteLimit, DocumentRequest,
        DocumentSelectionKind, EventLimit, ResourceLimit,
    },
};

/// One content-free explanation of how the policy affected an attempt.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyDecision {
    /// Acquisition selected by the immutable policy snapshot.
    AcquisitionSelected { acquisition: AcquisitionKind },
    /// Current or Exact document-selection authorship retained by preparation.
    DocumentSelection { selection: DocumentSelectionKind },
    /// A public document request mapped to the selected capture engine.
    DocumentRequested { document: DocumentRequest },
    /// Exact redirect behavior, including the hop budget when follow is enabled.
    DirectHttpRedirects { policy: DirectHttpRedirectPolicy },
    /// Direct HTTP redirect target policy forwarded to its execution path.
    DirectHttpRedirectTargets {
        policy: DirectHttpRedirectTargetPolicy,
    },
}

/// Quantitative bounds copied into the canonical capture specification.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum AppliedPolicyLimit {
    /// Shared attempt deadline in microseconds.
    MaximumElapsed { microseconds: u64 },
    /// Independent Direct HTTP response-body byte bounds.
    DirectHttpSourceBytes { limits: DirectHttpContentLimits },
    /// Browser byte bound with the capture domain's enforcement and scope.
    BrowserBytes {
        domain: BrowserByteDomain,
        limit: AddressableByteLimit,
        enforcement: BrowserLimitEnforcement,
        scope: BrowserBudgetScope,
    },
    /// Browser observation-event bound.
    BrowserEvents { limit: EventLimit },
    /// Browser-resource count bound.
    BrowserResources { limit: ResourceLimit },
    /// Accessibility-node count bound.
    AccessibilityNodes { limit: AccessibilityNodeLimit },
}

/// Policy identity and content-free decisions applied while resolving one attempt.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct AppliedPolicy {
    identity: EffectivePolicyIdentity,
    decisions: Vec<PolicyDecision>,
    limits: Vec<AppliedPolicyLimit>,
}

impl AppliedPolicy {
    pub(crate) const fn new(
        identity: EffectivePolicyIdentity,
        decisions: Vec<PolicyDecision>,
        limits: Vec<AppliedPolicyLimit>,
    ) -> Self {
        Self {
            identity,
            decisions,
            limits,
        }
    }

    /// Returns the effective policy identity used by this resolution.
    pub const fn identity(&self) -> EffectivePolicyIdentity {
        self.identity
    }

    /// Returns content-free decisions without the target URL or captured source.
    pub fn decisions(&self) -> &[PolicyDecision] {
        &self.decisions
    }

    /// Returns the exact quantitative policy bounds wired into the spec.
    pub fn limits(&self) -> &[AppliedPolicyLimit] {
        &self.limits
    }

    /// Returns the digest component without exposing any request or evidence values.
    pub const fn identity_digest(&self) -> Sha256Digest {
        self.identity.digest()
    }
}
