//! Event-driven confirmation on the existing owned tab and worker pool.

use serde::{Deserialize, Serialize};

use super::{SessionError, Work};
use crate::{automation_record::OperationReceipt, expect::Expectation, flow::Step};

/// Maximum encoded confirmation report, including retained source evidence.
pub const MAX_UNTIL_REPORT_BYTES: usize = 1024 * 1024;

/// Coordinates shared by every source used to confirm one waiting step.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UntilScope {
    pub session_id: String,
    pub tab_id: String,
    pub document_epoch: u64,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub frame_id: Option<String>,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub loader_id: Option<String>,
}

/// Why a waiting assertion stopped. A returned command is recorded separately.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UntilTermination {
    Satisfied,
    TimedOut,
    Cancelled,
    Rejected,
    Unavailable,
    TriggerFailed,
}

/// Current evaluation of one leaf assertion in a conjunction.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum UntilCheckState {
    Pending,
    Satisfied,
    Rejected,
    Unavailable,
}

/// Bounded evidence and diagnostics for one leaf check.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UntilCheck {
    pub index: u64,
    pub source: String,
    pub state: UntilCheckState,
    pub evidence: Option<serde_json::Value>,
    pub error: Option<String>,
}

/// Immutable confirmation evidence. Rust predicate code is never archived.
#[derive(Clone, Debug, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct UntilReport {
    pub version: u32,
    pub termination: UntilTermination,
    pub scope: UntilScope,
    /// The single trigger attempt, retained even if confirmation does not pass.
    pub trigger: Option<OperationReceipt>,
    pub evaluations: u64,
    pub checks: Vec<UntilCheck>,
    pub error: Option<String>,
}

/// Invalid or inconsistent saved confirmation evidence.
#[derive(Clone, Debug, thiserror::Error, Eq, PartialEq)]
#[error("invalid waiting assertion report: {0}")]
pub struct UntilReportError(pub &'static str);

impl UntilReport {
    /// Checks the report's bounded shape and the claims it makes about success.
    pub fn validate(&self) -> Result<(), UntilReportError> {
        self.encoded_size()?;
        let identities = [&self.scope.session_id, &self.scope.tab_id];
        if self.version != 1
            || identities
                .iter()
                .any(|value| value.is_empty() || value.len() > 4096)
        {
            return Err(UntilReportError("version or scope"));
        }
        if [&self.scope.frame_id, &self.scope.loader_id]
            .into_iter()
            .flatten()
            .any(|value| value.is_empty() || value.len() > 4096)
        {
            return Err(UntilReportError("frame or loader identity"));
        }
        if self.checks.is_empty() || self.checks.len() > crate::expect::MAX_EXPECTATIONS {
            return Err(UntilReportError("check count"));
        }
        for (position, check) in self.checks.iter().enumerate() {
            if u64::try_from(position).ok() != Some(check.index)
                || !matches!(check.source.as_str(), "dom" | "accessibility" | "network")
                || check
                    .error
                    .as_ref()
                    .is_some_and(|error| error.is_empty() || error.len() > 16_384)
                || (check.state == UntilCheckState::Satisfied
                    && (check.evidence.is_none() || check.error.is_some()))
            {
                return Err(UntilReportError("check identity or evidence"));
            }
        }
        if self
            .error
            .as_ref()
            .is_some_and(|error| error.is_empty() || error.len() > 16_384)
        {
            return Err(UntilReportError("diagnostic bound"));
        }
        if let Some(trigger) = &self.trigger {
            if trigger.id.is_empty()
                || trigger.id.len() > 4096
                || !matches!(
                    trigger.kind.as_str(),
                    "click" | "enter_text" | "evaluate" | "evaluate_file" | "evaluate_module"
                )
                || trigger.observation.is_some()
            {
                return Err(UntilReportError("trigger receipt"));
            }
            if trigger.status == crate::automation_record::OperationStatus::Observed
                && (trigger.error.is_some()
                    || trigger.result.as_ref().is_none_or(|result| {
                        !result.is_object()
                            || result.get("value").is_none()
                            || result
                                .get("started_at_unix_us")
                                .and_then(serde_json::Value::as_u64)
                                .is_none_or(|timestamp| timestamp == 0)
                    }))
            {
                return Err(UntilReportError("observed trigger dispatch start"));
            }
        }
        if self.termination == UntilTermination::Satisfied
            && (self.evaluations == 0
                || self.scope.frame_id.is_none()
                || self.scope.loader_id.is_none()
                || self.error.is_some()
                || self
                    .checks
                    .iter()
                    .any(|check| check.state != UntilCheckState::Satisfied)
                || self.trigger.as_ref().is_some_and(|trigger| {
                    trigger.status != crate::automation_record::OperationStatus::Observed
                }))
        {
            return Err(UntilReportError("satisfaction claim"));
        }
        if self.termination == UntilTermination::TriggerFailed
            && self.trigger.as_ref().is_none_or(|trigger| {
                trigger.status == crate::automation_record::OperationStatus::Observed
            })
        {
            return Err(UntilReportError("trigger failure claim"));
        }
        if self.termination == UntilTermination::Rejected
            && self
                .checks
                .iter()
                .all(|check| check.state != UntilCheckState::Rejected)
            && self.error.is_none()
        {
            return Err(UntilReportError("rejection claim"));
        }
        Ok(())
    }

    pub(crate) fn encoded_size(&self) -> Result<usize, UntilReportError> {
        struct Counter(usize);
        impl std::io::Write for Counter {
            fn write(&mut self, bytes: &[u8]) -> std::io::Result<usize> {
                let size = self
                    .0
                    .checked_add(bytes.len())
                    .filter(|size| *size <= MAX_UNTIL_REPORT_BYTES)
                    .ok_or_else(|| std::io::Error::other("confirmation report byte limit"))?;
                self.0 = size;
                Ok(bytes.len())
            }
            fn flush(&mut self) -> std::io::Result<()> {
                Ok(())
            }
        }
        let mut counter = Counter(0);
        serde_json::to_writer(&mut counter, self)
            .map_err(|_| UntilReportError("encoded evidence byte limit"))?;
        Ok(counter.0)
    }
}

impl Work {
    /// Installs observation before an optional trigger, then parks until confirmed.
    pub async fn until(
        &self,
        trigger: Option<&Step>,
        expectation: &Expectation,
    ) -> Result<OperationReceipt, SessionError> {
        #[cfg(feature = "browser")]
        {
            let deadline = crate::timing::deadline()
                .or_else(|| crate::timing::checked_deadline(self.timeout()))
                .ok_or(SessionError::InvalidInput)?;
            crate::timing::scope(deadline, Box::pin(self.until_owned(trigger, expectation))).await
        }
        #[cfg(not(feature = "browser"))]
        {
            let _ = (trigger, expectation);
            Err(SessionError::BrowserFeatureDisabled)
        }
    }
}

#[cfg(feature = "browser")]
mod browser;
