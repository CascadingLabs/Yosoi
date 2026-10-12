use super::{CancellationToken, RequestId, Response, WebTarget};
use crate::internal::engine as internal_engine;
use crate::internal::engine::request as implementation;
#[cfg(feature = "browser")]
use crate::internal::web_capture as internal_web_capture;
use crate::policy::Policy;
use crate::session;
use std::{error::Error, fmt};

/// Creates a request without performing I/O. URL validation occurs on send.
pub fn new(target: impl Into<WebTarget>) -> PageRequest {
    PageRequest {
        inner: implementation::new(target),
    }
}

/// A user-authored page request. Execution machinery remains private.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PageRequest {
    inner: internal_engine::PageRequest,
}
impl PageRequest {
    /// Acquire managed control from an explicitly retained Session.
    pub fn in_session<'session>(
        &self,
        session: &'session session::Session,
    ) -> session::SessionRequest<'session> {
        crate::session::SessionRequest::new(self.clone(), session)
    }

    /// Reuse caller-held control without reacquiring its tab mutex.
    pub fn with_work<'work>(&self, work: &'work session::Work) -> session::SessionRequest<'work> {
        crate::session::SessionRequest::on_work(self.clone(), work)
    }

    #[cfg(feature = "browser")]
    pub(crate) async fn send_on_browser_control(
        &self,
        policy: &Policy,
        control: &internal_web_capture::RuntimeBrowserControl,
        cancellation: &CancellationToken,
    ) -> Result<Response, RequestSendError> {
        self.inner
            .clone()
            .bind(policy)
            .send_on_browser_control(control, cancellation)
            .await
            .map(Response::from_internal)
            .map_err(RequestSendError)
    }

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
        let request = self.clone();
        BoundPageRequest {
            inner: self.inner.bind(policy),
            request,
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
    inner: internal_engine::BoundPageRequest<'policy>,
    request: PageRequest,
}
impl BoundPageRequest<'_> {
    /// Borrows a caller-owned Session while retaining this request's complete Policy.
    /// Sending acquires temporary Work without closing the caller's browser owner.
    pub fn in_session<'session>(
        &self,
        session: &'session session::Session,
    ) -> session::SessionRequest<'session> {
        crate::session::SessionRequest::new(self.request.clone(), session).bind(self.inner.policy())
    }
    /// Borrows caller-held tab control with this bound request's complete Policy.
    /// No new tab control is acquired and the caller remains responsible for releasing Work.
    pub fn with_work<'work>(&self, work: &'work session::Work) -> session::SessionRequest<'work> {
        crate::session::SessionRequest::on_work(self.request.clone(), work)
            .bind(self.inner.policy())
    }
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
pub struct RequestPreparationError(internal_engine::RequestPreparationError);
impl fmt::Display for RequestPreparationError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl Error for RequestPreparationError {}

/// The standard request execution could not be initialized.
#[derive(Debug)]
pub struct RequestSendError(internal_engine::RequestSendError);
impl fmt::Display for RequestSendError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(f)
    }
}
impl Error for RequestSendError {}
