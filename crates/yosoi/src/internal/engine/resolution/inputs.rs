use crate::internal::direct_http::{
    AcceptedSourceFormats, DirectHttpAcquisition, DirectHttpOutputSchemas, SourceRetentionPolicy,
    UnsupportedSourceFormatBehavior,
};
use crate::internal::types::{OperationId, Producer};
use crate::internal::web_capture::{
    BrowserArtifactIdentityPlan, BrowserEnvironmentOverrides, BrowserEvidenceAdmissionPolicy,
    BrowserNavigationPolicy, BrowserOutputSchemas, CertifiedBrowserCapabilities, NavigationContext,
    SettlementPolicy, WebArtifactFamily,
};

use crate::internal::engine::policy::DocumentRequest;

pub(super) const fn family_for_document(document: DocumentRequest) -> WebArtifactFamily {
    match document {
        DocumentRequest::ResponseDocument => WebArtifactFamily::Source,
        DocumentRequest::RenderedDom => WebArtifactFamily::RenderedDom,
        DocumentRequest::AccessibilityTree => WebArtifactFamily::AccessibilityTree,
        DocumentRequest::NetworkTree => WebArtifactFamily::Network,
    }
}

/// Provider-owned values needed to construct a Direct HTTP capture spec.
///
/// The output schemas are candidate values. The resolver selects only schemas
/// used by this attempt's effective document selection.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DirectHttpResolutionInputs {
    /// Validated Direct HTTP transport and session semantics.
    pub acquisition: DirectHttpAcquisition,
    /// Accepted source formats for the Direct HTTP decoder.
    pub accepted_formats: AcceptedSourceFormats,
    /// Behavior for a classified source format outside the accepted set.
    pub unsupported_format: UnsupportedSourceFormatBehavior,
    /// Source representation retention required by the execution layer.
    pub retention: SourceRetentionPolicy,
    /// Producer responsible for this attempt.
    pub producer: Producer,
    /// Operation recorded on the attempt receipt.
    pub operation: OperationId,
    /// Candidate schemas for source-derived outputs.
    pub output_schemas: DirectHttpOutputSchemas,
}

/// Provider-owned values needed to construct a certified browser capture spec.
///
/// Capability certification is supplied by the execution layer. The resolver
/// never guesses or manufactures a browser profile or capability claim.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserResolutionInputs {
    /// Browser navigation context selected by the execution owner.
    ///
    /// The current VoidCrawl adapter supports `FreshTopLevel`; existing browser
    /// and frame references fail resolution instead of being silently replaced.
    pub navigation_context: NavigationContext,
    /// Existing browser navigation completion behavior.
    pub navigation_policy: BrowserNavigationPolicy,
    /// Caller-selected rendering overrides; mode comes from the policy snapshot.
    pub environment_overrides: BrowserEnvironmentOverrides,
    /// Already-validated provider certification and instrumentation state.
    pub capabilities: CertifiedBrowserCapabilities,
    /// Producer responsible for this attempt.
    pub producer: Producer,
    /// Operation recorded on the attempt receipt.
    pub operation: OperationId,
    /// Candidate output schemas, pruned to the prepared attempt's documents.
    pub output_schemas: BrowserOutputSchemas,
    /// Caller-owned stable activity-local artifact identity plan.
    pub identity_plan: BrowserArtifactIdentityPlan,
    /// Existing browser evidence-admission policy.
    pub admission: BrowserEvidenceAdmissionPolicy,
    /// Existing observation settlement behavior.
    pub settlement: SettlementPolicy,
}

/// Explicit context supplied by the selected acquisition executor.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum PolicyResolutionContext {
    /// Inputs owned by the Direct HTTP execution layer.
    DirectHttp(Box<DirectHttpResolutionInputs>),
    /// Inputs owned by the browser execution and certification layer.
    Browser(Box<BrowserResolutionInputs>),
}

impl PolicyResolutionContext {
    /// Owns Direct HTTP provider inputs without enlarging every context value.
    pub fn direct_http(inputs: DirectHttpResolutionInputs) -> Self {
        Self::DirectHttp(Box::new(inputs))
    }

    /// Owns certified browser inputs without enlarging every context value.
    pub fn browser(inputs: BrowserResolutionInputs) -> Self {
        Self::Browser(Box::new(inputs))
    }

    pub(in crate::internal::engine) const fn kind(&self) -> PolicyResolutionContextKind {
        match self {
            Self::DirectHttp(_) => PolicyResolutionContextKind::DirectHttp,
            Self::Browser(_) => PolicyResolutionContextKind::Browser,
        }
    }
}

/// Acquisition context kind for typed mismatch reporting.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum PolicyResolutionContextKind {
    /// Direct HTTP provider inputs.
    DirectHttp,
    /// Certified browser provider inputs.
    Browser,
}
