use serde::{Deserialize, Serialize};

/// Whether a failure or local cancellation continues execution or stops a scope.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    content = "scope",
    rename_all = "snake_case",
    deny_unknown_fields
)]
#[derive(Default)]
pub enum Continuation {
    /// Keep executing later steps in the containing Flow.
    #[default]
    Continue,
    /// Stop at the selected scope after recording the triggering result.
    Stop(StopScope),
}

/// The execution scope affected by a continuation policy.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum StopScope {
    /// Stop the nearest containing Flow and return to its parent's next step.
    CurrentFlow,
    /// Stop every remaining step in the invocation.
    Invocation,
}

/// Fallback behavior for failed and locally cancelled Flow steps.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FlowPolicy {
    /// Behavior when an action or assertion fails.
    #[serde(default)]
    pub on_failure: Continuation,
    /// Behavior when a step-local cancellation token is cancelled.
    #[serde(default)]
    pub on_cancellation: Continuation,
}

impl FlowPolicy {
    pub const fn is_default(&self) -> bool {
        matches!(self.on_failure, Continuation::Continue)
            && matches!(self.on_cancellation, Continuation::Continue)
    }
}
