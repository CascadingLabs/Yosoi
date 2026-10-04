use std::fmt;

use crate::{PolicySnapshot, PreparedPageRequest, RequestId};

use super::AttemptOutcome;

/// Result of executing a prepared page request.
pub struct Response {
    request_id: RequestId,
    requested_target: String,
    policy_snapshot: PolicySnapshot,
    attempts: Vec<AttemptOutcome>,
    termination: ResponseTermination,
}

impl Response {
    pub(crate) fn new(
        prepared: &PreparedPageRequest,
        attempts: Vec<AttemptOutcome>,
        termination: ResponseTermination,
    ) -> Self {
        Self {
            request_id: prepared.id(),
            requested_target: prepared.target().to_owned(),
            policy_snapshot: prepared.policy_snapshot().clone(),
            attempts,
            termination,
        }
    }

    pub const fn request_id(&self) -> RequestId {
        self.request_id
    }

    /// Returns the canonical target requested by this response.
    pub fn requested_target(&self) -> &str {
        &self.requested_target
    }

    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }

    /// Returns one outcome for each authored acquisition, in policy order.
    pub fn attempts(&self) -> &[AttemptOutcome] {
        &self.attempts
    }

    pub const fn termination(&self) -> ResponseTermination {
        self.termination
    }
}

impl fmt::Debug for Response {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("Response")
            .field("request_id", &self.request_id)
            .field("requested_target", &"[redacted]")
            .field("attempt_count", &self.attempts.len())
            .field("termination", &self.termination)
            .finish_non_exhaustive()
    }
}

/// Whether the sequence ended without cancellation or observed caller cancellation.
///
/// `Completed` does not imply every attempt succeeded; typed attempt failures
/// remain in `Response::attempts`.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum ResponseTermination {
    Completed,
    Cancelled,
}
