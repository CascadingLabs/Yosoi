//! Recipe validation errors.

use super::FlowOutcome;
use crate::assertions::AssertionError;
use crate::{policy::PolicyError, session::SessionError};
use std::{error::Error, fmt};
use thiserror::Error;

/// Authored recipe structure or value rejected before browser execution.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum FlowValidationError {
    /// JavaScript parsing or action validation rejected the authored source.
    JavaScript(String),
    /// An authored assertion contains an invalid condition or value.
    Assertion(AssertionError),
    /// A deserialized step-local cancellation token has not been rebound by the caller.
    UnboundCancellation,
    /// A timeout is zero or cannot fit a monotonic deadline on this platform.
    InvalidTimeout,
    /// An action has overlapping nested timeout wrappers, whose semantics are unsupported.
    NestedTimeout,
    /// A nested Flow requests failure capture without supported child-capture provenance.
    NestedFailureCaptureUnsupported,
    /// The total authored step count exceeds the recipe validation budget.
    TooManySteps {
        /// Count of authored steps found during validation.
        actual: u128,
        /// Maximum permitted step count.
        maximum: u64,
    },
    /// Nested Flow depth exceeds the recipe validation budget.
    TooDeep {
        /// Nested depth measured during validation.
        actual: u32,
        /// Maximum permitted nested Flow depth.
        maximum: u32,
    },
    /// Serialized recipe bytes exceed the input validation budget.
    SerializedInputTooLarge {
        /// Byte length of the serialized authored recipe.
        actual: usize,
        /// Maximum accepted serialized bytes.
        maximum: usize,
    },
    /// The authored recipe could not be serialized for structural validation.
    Serialization(String),
    /// A step's locator selector contains no usable text.
    EmptySelector {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
    },
    /// An authored locator selector exceeds its byte budget.
    SelectorTooLong {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
        /// UTF-8 bytes in the authored selector.
        actual: usize,
        /// Maximum accepted selector bytes.
        maximum: usize,
    },
    /// An Until step has no positive wait duration.
    ZeroTimeout {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
    },
    /// A JavaScript action contains no usable source text.
    EmptySource {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
    },
    /// Authored JavaScript source exceeds the action-source byte budget.
    SourceTooLong {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
        /// UTF-8 bytes in the authored source.
        actual: usize,
        /// Maximum accepted action-source bytes.
        maximum: usize,
    },
    /// An Until step requests a trigger kind unsupported by this recipe vocabulary.
    InvalidUntilTrigger {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
        /// Trigger kind label rejected during validation.
        kind: String,
    },
    /// A required Until expectation field contains no usable text.
    EmptyExpectation {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
        /// Name of the empty authored expectation field.
        field: &'static str,
    },
    /// An authored Until expectation field exceeds its byte budget.
    ExpectationValueTooLong {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
        /// Name of the oversized expectation field.
        field: &'static str,
        /// UTF-8 bytes in the authored field value.
        actual: usize,
        /// Maximum accepted bytes for that field.
        maximum: usize,
    },
    /// The aggregate number of Until expectation clauses exceeds its budget.
    TooManyExpectations {
        /// Number of expectation clauses found during recipe validation.
        actual: u128,
        /// Maximum permitted expectation-clause count.
        maximum: usize,
    },
    /// Nested boolean Until expectations exceed the permitted expression depth.
    ExpectationTooDeep {
        /// Boolean expression depth measured during validation.
        actual: u32,
        /// Maximum permitted expectation depth.
        maximum: u32,
    },
    /// An Until expectation fails value or structural checks not covered by a specific variant.
    InvalidExpectation {
        /// Zero-based index of the affected step in its containing Flow.
        step_index: u64,
        /// Explanation of the rejected expectation; it can include authored details.
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
    /// The authored Flow failed validation before Session invocation.
    #[error("flow validation failed: {0}")]
    InvalidFlow(#[source] FlowValidationError),
    /// The supplied complete policy failed validation before invocation.
    #[error("policy validation failed: {0}")]
    Policy(#[source] PolicyError),
    /// Managed Session setup, invocation, or cleanup failed, possibly after partial execution.
    #[error("session operation failed: {source}")]
    Session {
        /// Primary Session failure, retained separately from a cleanup failure.
        source: SessionError,
        /// Owned partial outcome when execution produced one before the failure.
        outcome: Option<Box<FlowOutcome>>,
        /// Additional cleanup failure, if present; external effects are not rolled back.
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
