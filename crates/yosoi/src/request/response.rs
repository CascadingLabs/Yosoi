use super::{Attempt, RequestId, ResponseTermination};
use crate::policy::PolicySnapshot;

/// The result of executing a request, with no provider or archive handles.
#[derive(Debug)]
pub struct Response {
    inner: yosoi_engine::Response,
}
impl Response {
    pub(crate) const fn from_internal(inner: yosoi_engine::Response) -> Self {
        Self { inner }
    }
    /// Borrows this response without cloning captured data.
    pub const fn as_ref(&self) -> ResponseRef<'_> {
        ResponseRef { inner: &self.inner }
    }
    /// Returns the request identity.
    pub const fn request_id(&self) -> RequestId {
        self.as_ref().request_id()
    }
    /// Returns the canonical target requested.
    pub fn requested_target(&self) -> &str {
        self.as_ref().requested_target()
    }
    /// Returns the validated policy snapshot used during execution.
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        self.as_ref().policy_snapshot()
    }
    /// Iterates acquisition outcomes in authored policy order.
    pub fn attempts(&self) -> impl ExactSizeIterator<Item = Attempt<'_>> {
        self.as_ref().attempts()
    }
    /// Distinguishes completed execution from cancellation.
    pub const fn termination(&self) -> ResponseTermination {
        self.as_ref().termination()
    }
}

/// A borrowed SDK response, including responses retained by Map.
#[derive(Clone, Copy, Debug)]
pub struct ResponseRef<'response> {
    pub(crate) inner: &'response yosoi_engine::Response,
}
impl<'response> ResponseRef<'response> {
    /// Returns the request identity.
    pub const fn request_id(self) -> RequestId {
        self.inner.request_id()
    }
    /// Returns the canonical target requested.
    pub fn requested_target(self) -> &'response str {
        self.inner.requested_target()
    }
    /// Returns the execution's policy snapshot.
    pub const fn policy_snapshot(self) -> &'response PolicySnapshot {
        self.inner.policy_snapshot()
    }
    /// Iterates acquisition outcomes in authored policy order.
    pub fn attempts(self) -> impl ExactSizeIterator<Item = Attempt<'response>> {
        self.inner.attempts().iter().map(|inner| Attempt { inner })
    }
    /// Distinguishes completed execution from cancellation.
    pub const fn termination(self) -> ResponseTermination {
        self.inner.termination()
    }
}
