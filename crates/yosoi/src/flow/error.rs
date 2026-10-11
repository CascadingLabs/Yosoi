//! Recipe validation errors.

use super::FlowOutcome;
use crate::assertions::AssertionError;
use crate::{policy::PolicyError, session::SessionError};
use std::{error::Error, fmt};
use thiserror::Error;

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FlowValidationError {
    JavaScript(String),
    Assertion(AssertionError),
    UnboundCancellation,
    InvalidTimeout,
    NestedTimeout,
    NestedFailureCaptureUnsupported,
    TooManySteps {
        actual: u128,
        maximum: u64,
    },
    TooDeep {
        actual: u32,
        maximum: u32,
    },
    SerializedInputTooLarge {
        actual: usize,
        maximum: usize,
    },
    Serialization(String),
    EmptySelector {
        step_index: u64,
    },
    SelectorTooLong {
        step_index: u64,
        actual: usize,
        maximum: usize,
    },
    ZeroTimeout {
        step_index: u64,
    },
    EmptySource {
        step_index: u64,
    },
    SourceTooLong {
        step_index: u64,
        actual: usize,
        maximum: usize,
    },
    InvalidUntilTrigger {
        step_index: u64,
        kind: String,
    },
    EmptyExpectation {
        step_index: u64,
        field: &'static str,
    },
    ExpectationValueTooLong {
        step_index: u64,
        field: &'static str,
        actual: usize,
        maximum: usize,
    },
    TooManyExpectations {
        actual: u128,
        maximum: usize,
    },
    ExpectationTooDeep {
        actual: u32,
        maximum: u32,
    },
    InvalidExpectation {
        step_index: u64,
        reason: String,
    },
}

impl fmt::Display for FlowValidationError {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::JavaScript(error) => write!(formatter, "invalid JavaScript action: {error}"),
            Self::InvalidTimeout => formatter.write_str("timeout must be positive and fit a monotonic deadline"),
            Self::Assertion(error) => error.fmt(formatter),
            Self::UnboundCancellation => formatter.write_str(
                "step-local cancellation token must be rebound before invoking this Flow",
            ),
            Self::NestedTimeout => formatter.write_str("nested action timeout wrappers are invalid"),
            Self::NestedFailureCaptureUnsupported => formatter.write_str(
                "failure capture is not supported on nested Flows because child capture provenance is not recorded",
            ),
            Self::TooManySteps { actual, maximum } => write!(
                formatter,
                "flow contains {actual} steps; maximum is {maximum}"
            ),
            Self::TooDeep { actual, maximum } => write!(
                formatter,
                "nested Flow depth is {actual}; maximum is {maximum}"
            ),
            Self::SerializedInputTooLarge { actual, maximum } => write!(
                formatter,
                "serialized Flow is {actual} bytes; maximum is {maximum}"
            ),
            Self::Serialization(message) => {
                write!(formatter, "Flow could not be serialized for validation: {message}")
            }
            Self::EmptySelector { step_index } => {
                write!(formatter, "flow step {step_index} has an empty selector")
            }
            Self::SelectorTooLong {
                step_index,
                actual,
                maximum,
            } => write!(
                formatter,
                "flow step {step_index} selector is {actual} bytes; maximum is {maximum}"
            ),
            Self::ZeroTimeout { step_index } => write!(
                formatter,
                "flow step {step_index} wait_until timeout must be positive"
            ),
            Self::EmptySource { step_index } => {
                write!(formatter, "flow step {step_index} has an empty script")
            }
            Self::SourceTooLong {
                step_index,
                actual,
                maximum,
            } => write!(
                formatter,
                "flow step {step_index} script is {actual} bytes; maximum is {maximum}"
            ),
            Self::InvalidUntilTrigger { step_index, kind } => write!(
                formatter,
                "flow step {step_index} uses unsupported Until trigger `{kind}`"
            ),
            Self::EmptyExpectation { step_index, field } => write!(
                formatter,
                "flow step {step_index} has an empty Until expectation {field}"
            ),
            Self::ExpectationValueTooLong {
                step_index,
                field,
                actual,
                maximum,
            } => write!(
                formatter,
                "flow step {step_index} Until {field} is {actual} bytes; maximum is {maximum}"
            ),
            Self::TooManyExpectations { actual, maximum } => write!(
                formatter,
                "Until contains {actual} expectation clauses; maximum is {maximum}"
            ),
            Self::ExpectationTooDeep { actual, maximum } => write!(
                formatter,
                "Until expectation depth is {actual}; maximum is {maximum}"
            ),
            Self::InvalidExpectation { step_index, reason } => write!(
                formatter,
                "flow step {step_index} has an invalid Until expectation: {reason}"
            ),
        }
    }
}

impl Error for FlowValidationError {}
/// A flow failed validation or could not start/clean up its managed Session.
#[derive(Debug, Error)]
pub enum FlowInvokeError {
    #[error("flow validation failed: {0}")]
    InvalidFlow(#[source] FlowValidationError),
    #[error("policy validation failed: {0}")]
    Policy(#[source] PolicyError),
    #[error("session operation failed: {source}")]
    Session {
        source: SessionError,
        outcome: Option<Box<FlowOutcome>>,
        cleanup: Option<SessionError>,
    },
}

impl FlowInvokeError {
    /// Returns a managed cleanup error without replacing the primary failure.
    pub const fn cleanup_error(&self) -> Option<&SessionError> {
        match self {
            Self::Session { cleanup, .. } => cleanup.as_ref(),
            _ => None,
        }
    }
    /// Returns the partial flow outcome when managed cleanup failed after execution.
    pub fn partial_outcome(&self) -> Option<&FlowOutcome> {
        match self {
            Self::Session { outcome, .. } => outcome.as_deref(),
            Self::InvalidFlow(_) | Self::Policy(_) => None,
        }
    }
}
