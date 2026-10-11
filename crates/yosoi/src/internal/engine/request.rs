//! Pure page-request authoring and preparation.
//!
//! Preparing a request validates its authored target, snapshots one complete
//! policy, and gives each effective acquisition a fresh capture identity. It
//! does not contact a provider or perform any other I/O.

use std::{borrow::Cow, fmt};

use crate::internal::policy::policy::{AcquisitionKind, DocumentRequest, DocumentSelectionKind};
use crate::internal::policy::{
    EffectivePolicy, EffectivePolicyIdentity, Policy, PolicyError, PolicySnapshot,
};
use crate::internal::types::{ActivityId, CaptureId};
use crate::internal::web_capture::{RequestedWebTarget, TupleWebOrigin, WebUrlParseError};
use thiserror::Error;

pub mod execution;
pub use execution::{
    ArchivedCaptureProgress, ArchivedRequestError, ArchivedRequestProgress, ArchivedResponse,
    ArtifactDisposition, ArtifactFamilyDisposition, AttemptCaptureFacts,
    AttemptCaptureFailureFacts, AttemptDiagnostic, AttemptDocumentOutcome, AttemptFailure,
    AttemptFailureKind, AttemptOutcome, AttemptResult, AttemptTransportOutcome,
    BrowserDocumentObservation, BrowserFailureReason, BrowserTerminalClassification,
    BrowserTerminalFacts, NotStartedAttempt, NotStartedReason, RequestExecutor, RequestSendError,
    Response, ResponseTermination, StandardExecutionSetupError,
};

/// An owned target string authored before URL validation.
///
/// Validation is intentionally deferred until request preparation, where the
/// shared [`RequestedWebTarget`] rules canonicalize HTTP(S) URLs and reject
/// missing hosts and credentials.
#[derive(Clone, Eq, Hash, PartialEq)]
pub struct WebTarget(String);

impl WebTarget {
    /// Stores a target string without parsing or validating it.
    pub fn new(value: impl Into<String>) -> Self {
        Self(value.into())
    }

    /// Returns the authored target string.
    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl From<String> for WebTarget {
    fn from(value: String) -> Self {
        Self(value)
    }
}

impl From<&str> for WebTarget {
    fn from(value: &str) -> Self {
        Self(value.to_owned())
    }
}

impl From<&String> for WebTarget {
    fn from(value: &String) -> Self {
        Self(value.clone())
    }
}

impl From<Box<str>> for WebTarget {
    fn from(value: Box<str>) -> Self {
        Self(value.into())
    }
}

impl<'value> From<Cow<'value, str>> for WebTarget {
    fn from(value: Cow<'value, str>) -> Self {
        Self(value.into_owned())
    }
}

impl AsRef<str> for WebTarget {
    fn as_ref(&self) -> &str {
        self.as_str()
    }
}

impl fmt::Debug for WebTarget {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_tuple("WebTarget")
            .field(&"<redacted>")
            .finish()
    }
}

/// Creates a page request from an owned or borrowed string-like target.
///
/// The target is not parsed until [`PageRequest::prepare`] or
/// [`BoundPageRequest::prepare`] is called.
pub fn new(target: impl Into<WebTarget>) -> PageRequest {
    PageRequest {
        id: RequestId::random(),
        target: target.into(),
    }
}

/// A page request authored independently of any policy or acquisition.
#[derive(Clone, Eq, PartialEq)]
pub struct PageRequest {
    id: RequestId,
    target: WebTarget,
}

impl fmt::Debug for PageRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PageRequest")
            .field("id", &self.id)
            .field("target", &self.target)
            .finish()
    }
}

impl PageRequest {
    /// Returns this authored request's logical identity.
    pub const fn id(&self) -> RequestId {
        self.id
    }

    /// Returns the unvalidated, authored target intent.
    pub const fn target(&self) -> &WebTarget {
        &self.target
    }

    /// Binds this request to one complete borrowed policy value.
    ///
    /// The policy remains borrowed for the bound request's lifetime. No policy
    /// merge or mutation occurs.
    pub fn bind(self, policy: &Policy) -> BoundPageRequest<'_> {
        BoundPageRequest {
            id: self.id,
            target: self.target,
            policy,
        }
    }

    /// Prepares this request using [`Policy::default`].
    ///
    /// Preparation borrows the authored request, so the same logical request
    /// identity is retained if preparation is repeated.
    pub fn prepare(&self) -> Result<PreparedPageRequest, RequestPreparationError> {
        let policy = Policy::default();
        prepare_with_policy(self.id, &self.target, &policy)
    }
}

/// A page request borrowing one complete policy value.
#[derive(Clone, Eq, PartialEq)]
pub struct BoundPageRequest<'policy> {
    id: RequestId,
    target: WebTarget,
    policy: &'policy Policy,
}

impl fmt::Debug for BoundPageRequest<'_> {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("BoundPageRequest")
            .field("id", &self.id)
            .field("target", &self.target)
            .field("policy", self.policy)
            .finish()
    }
}

impl<'policy> BoundPageRequest<'policy> {
    /// Returns this bound request's logical identity.
    pub const fn id(&self) -> RequestId {
        self.id
    }

    /// Returns the unvalidated, authored target intent.
    pub const fn target(&self) -> &WebTarget {
        &self.target
    }

    /// Returns the exact policy value borrowed by this request.
    pub const fn policy(&self) -> &'policy Policy {
        self.policy
    }

    /// Validates and prepares the request against its borrowed policy.
    ///
    /// Preparation borrows the bound request, preserving its logical identity
    /// for later diagnostic preparations.
    pub fn prepare(&self) -> Result<PreparedPageRequest, RequestPreparationError> {
        prepare_with_policy(self.id, &self.target, self.policy)
    }
}

/// Logical identity for one prepared page request.
///
/// This remains distinct from [`CaptureId`], which identifies each separate
/// acquisition attempt belonging to the request.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RequestId(ActivityId);

impl RequestId {
    fn random() -> Self {
        Self(ActivityId::random())
    }

    /// Returns this request's general activity identity for durable records.
    pub const fn activity_id(self) -> ActivityId {
        self.0
    }
}

impl fmt::Display for RequestId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        fmt::Display::fmt(&self.0, formatter)
    }
}

/// One ordered acquisition prepared from the effective policy snapshot.
#[derive(Eq, PartialEq)]
pub struct PreparedAttempt {
    capture_id: CaptureId,
    kind: AcquisitionKind,
    authored_selection: DocumentSelectionKind,
    documents: Vec<DocumentRequest>,
    target: RequestedWebTarget,
}

impl fmt::Debug for PreparedAttempt {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedAttempt")
            .field("capture_id", &self.capture_id)
            .field("kind", &self.kind)
            .field("authored_selection", &self.authored_selection)
            .field("documents", &self.documents)
            .field("target", &"<redacted>")
            .finish()
    }
}

impl PreparedAttempt {
    /// Returns this acquisition attempt's distinct capture identity.
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }

    /// Returns the selected acquisition mechanism.
    pub const fn kind(&self) -> AcquisitionKind {
        self.kind
    }

    /// Returns the caller-authored Current or Exact document selection.
    pub const fn authored_selection(&self) -> DocumentSelectionKind {
        self.authored_selection
    }

    /// Returns the canonical effective documents resolved for this attempt.
    pub fn documents(&self) -> &[DocumentRequest] {
        &self.documents
    }

    /// Returns the canonical validated target shared by this request.
    pub fn target(&self) -> &str {
        self.target.as_str()
    }

    /// Returns the origin-only target projection safe for request run records.
    pub fn target_origin(&self) -> TupleWebOrigin {
        self.target.origin()
    }

    pub(in crate::internal::engine) const fn requested_target(&self) -> &RequestedWebTarget {
        &self.target
    }
}

/// Immutable request intent after target and policy preparation.
#[derive(Eq, PartialEq)]
pub struct PreparedPageRequest {
    id: RequestId,
    target: RequestedWebTarget,
    policy_snapshot: PolicySnapshot,
    attempts: Vec<PreparedAttempt>,
}

impl fmt::Debug for PreparedPageRequest {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedPageRequest")
            .field("id", &self.id)
            .field("target", &"<redacted>")
            .field(
                "effective_policy_identity",
                &self.policy_snapshot.identity(),
            )
            .field("attempt_count", &self.attempts.len())
            .finish()
    }
}

impl PreparedPageRequest {
    /// Returns this prepared request's logical identity.
    pub const fn id(&self) -> RequestId {
        self.id
    }

    /// Returns the canonical validated request target.
    pub fn target(&self) -> &str {
        self.target.as_str()
    }

    /// Returns the origin-only target projection safe for request run records.
    pub fn target_origin(&self) -> TupleWebOrigin {
        self.target.origin()
    }

    /// Returns the ordered prepared acquisition attempts.
    pub fn attempts(&self) -> &[PreparedAttempt] {
        &self.attempts
    }

    /// Returns the one immutable policy snapshot used by preparation.
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }

    /// Returns the effective behavior held by the policy snapshot.
    pub fn effective_policy(&self) -> &EffectivePolicy {
        self.policy_snapshot.effective_policy()
    }

    /// Returns the deterministic effective-policy identity.
    pub const fn effective_policy_identity(&self) -> EffectivePolicyIdentity {
        self.policy_snapshot.identity()
    }
}

/// Failure while validating or snapshotting a page request.
#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum RequestPreparationError {
    /// The authored target failed the canonical HTTP(S) web-target rules.
    #[error("invalid request target")]
    InvalidTarget(#[source] WebUrlParseError),

    /// The complete authored policy failed validation or snapshot creation.
    #[error("invalid request policy")]
    InvalidPolicy(#[source] PolicyError),
}

fn prepare_with_policy(
    id: RequestId,
    authored_target: &WebTarget,
    policy: &Policy,
) -> Result<PreparedPageRequest, RequestPreparationError> {
    let target = RequestedWebTarget::parse(authored_target.as_str())
        .map_err(RequestPreparationError::InvalidTarget)?;
    let policy_snapshot =
        PolicySnapshot::from_policy(policy).map_err(RequestPreparationError::InvalidPolicy)?;
    let mut attempts =
        Vec::with_capacity(policy_snapshot.effective_policy().page.acquisitions.len());

    for effective in &policy_snapshot.effective_policy().page.acquisitions {
        attempts.push(PreparedAttempt {
            capture_id: CaptureId::random(),
            kind: effective.acquisition,
            authored_selection: effective.authored_selection,
            documents: effective.documents.clone(),
            target: target.clone(),
        });
    }

    Ok(PreparedPageRequest {
        id,
        target,
        policy_snapshot,
        attempts,
    })
}
