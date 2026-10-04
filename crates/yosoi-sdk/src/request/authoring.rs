use super::{CancellationToken, RequestId, Response, WebTarget};
use crate::policy::Policy;
use std::{error::Error, fmt};
use yosoi::request as implementation;

/// Creates a request without performing I/O. URL validation occurs on send.
pub fn new(target: impl Into<WebTarget>) -> PageRequest {
    PageRequest {
        inner: implementation::new(target),
    }
}

/// A user-authored page request. Execution machinery remains private.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PageRequest {
    inner: yosoi::PageRequest,
}
impl PageRequest {
    /// Returns the request identity.
    pub const fn id(&self) -> RequestId {
        self.inner.id()
    }
    /// Returns the target as authored before canonicalization.
    pub const fn target(&self) -> &WebTarget {
        self.inner.target()
    }
    /// Associates this request with a borrowed policy.
    pub fn bind(self, policy: &Policy) -> BoundPageRequest<'_> {
        BoundPageRequest {
            inner: self.inner.bind(policy),
        }
    }
    /// Validates the target and policy without contacting a provider.
    pub fn validate(&self) -> Result<(), RequestPreparationError> {
        self.inner
            .prepare()
            .map(|_| ())
            .map_err(RequestPreparationError)
    }
    /// Executes through the package's standard adapters and default policy.
    pub async fn send(&self) -> Result<Response, RequestSendError> {
        self.inner
            .send()
            .await
            .map(Response::from_internal)
            .map_err(RequestSendError)
    }
    /// Executes with caller-controlled cancellation.
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        self.inner
            .send_cancellable(cancellation)
            .await
            .map(Response::from_internal)
            .map_err(RequestSendError)
    }
}

/// A request bound to a borrowed SDK policy.
#[derive(Debug)]
pub struct BoundPageRequest<'policy> {
    inner: yosoi::BoundPageRequest<'policy>,
}
impl BoundPageRequest<'_> {
    /// Returns the request identity.
    pub const fn id(&self) -> RequestId {
        self.inner.id()
    }
    /// Returns the target as authored.
    pub const fn target(&self) -> &WebTarget {
        self.inner.target()
    }
    /// Returns the policy used by this request.
    pub const fn policy(&self) -> &Policy {
        self.inner.policy()
    }
    /// Validates without contacting a provider.
    pub fn validate(&self) -> Result<(), RequestPreparationError> {
        self.inner
            .prepare()
            .map(|_| ())
            .map_err(RequestPreparationError)
    }
    /// Executes through the package's standard adapters and this policy.
    pub async fn send(&self) -> Result<Response, RequestSendError> {
        self.inner
            .send()
            .await
            .map(Response::from_internal)
            .map_err(RequestSendError)
    }
    /// Executes with caller-controlled cancellation.
    pub async fn send_cancellable(
        &self,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        self.inner
            .send_cancellable(cancellation)
            .await
            .map(Response::from_internal)
            .map_err(RequestSendError)
    }
}

/// A request's target or policy could not be prepared.
#[derive(Debug)]
pub struct RequestPreparationError(yosoi::RequestPreparationError);
impl fmt::Display for RequestPreparationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl Error for RequestPreparationError {}

/// The standard request execution could not be initialized.
#[derive(Debug)]
pub struct RequestSendError(yosoi::RequestSendError);
impl fmt::Display for RequestSendError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl Error for RequestSendError {}
