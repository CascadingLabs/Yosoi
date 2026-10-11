use std::fmt;

use crate::internal::engine::{PolicySnapshot, PreparedPageRequest, RequestId};

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
    pub(in crate::internal::engine) fn new(
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

    /// Returns the identity of the prepared request that produced these outcomes.
    pub const fn request_id(&self) -> RequestId {
        self.request_id
    }

    /// Returns the canonical target requested by this response.
    pub fn requested_target(&self) -> &str {
        &self.requested_target
    }

    /// Borrows the policy snapshot fixed during request preparation.
    ///
    /// The snapshot belongs to this response; later policy changes do not alter it.
    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }

    /// Returns one outcome for each authored acquisition, in policy order.
    pub fn attempts(&self) -> &[AttemptOutcome] {
        &self.attempts
    }

    /// Returns whether execution observed cancellation, independently of attempt success.
    ///
    /// Inspect [`Self::attempts`] for individual successes, failures, and acquisitions
    /// that never started.
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
#[derive(Clone, Copy, Debug, Eq, PartialEq, serde::Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ResponseTermination {
    /// Execution finished without observing caller cancellation.
    ///
    /// This does not imply that every acquisition attempt succeeded. Inspect
    /// [`Response::attempts`] for typed failures and partial outcomes. An empty
    /// acquisition sequence also completes. Cancellation arriving after the last
    /// observation does not retroactively change this result.
    Completed,
    /// Execution observed caller cancellation before or during an acquisition.
    ///
    /// Outcomes already recorded remain available in [`Response::attempts`];
    /// they are not rolled back. Every subsequent acquisition is represented as
    /// not started with [`super::NotStartedReason::Cancelled`]. A token already
    /// cancelled when execution begins produces this result even for an empty
    /// acquisition sequence. This describes observed cancellation, not a promise
    /// that every underlying external side effect was undone.
    Cancelled,
}
