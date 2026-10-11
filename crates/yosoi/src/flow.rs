//! Serializable browser workflows and their bounded execution records.

mod error;
mod execution;
mod model;
mod validation;

pub use error::FlowValidationError;
pub use model::*;
use validation::validate_flow;

pub use execution::FlowInvokeError;

use crate::{policy::Policy, request::CancellationToken, session::Work};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::time::Duration;

/// Creates a flow from ordered steps.
pub fn new(steps: impl IntoIterator<Item = Step>) -> Flow {
    Flow::new(steps)
}

/// A sequence of browser operations to run in order.
///
/// The flow is validated before execution. Its public `steps` field keeps the
/// wire model straightforward to author and deserialize; callers should use
/// [`Flow::validate`] after mutating or deserializing it.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Flow {
    /// Ordered operations in this flow.
    pub steps: Vec<Step>,
    /// Fallback duration for unannotated actions in this scope, in milliseconds.
    timeout: Option<Duration>,
    /// Optional failure continuation override inherited by child steps.
    on_failure: Option<Continuation>,
    /// Optional local cancellation continuation override inherited by child steps.
    on_cancellation: Option<Continuation>,
    /// Optional single screenshot capture after a failed or unknown step.
    pub capture_on_failure: FailureCapturePolicy,
}

impl Default for Flow {
    fn default() -> Self {
        Self::new([])
    }
}

impl Serialize for Flow {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        #[derive(Serialize)]
        struct FlowRef<'a> {
            schema_version: u32,
            steps: &'a [Step],
            #[serde(skip_serializing_if = "Option::is_none")]
            timeout: Option<Duration>,
            #[serde(skip_serializing_if = "Option::is_none")]
            on_failure: Option<Continuation>,
            #[serde(skip_serializing_if = "Option::is_none")]
            on_cancellation: Option<Continuation>,
            #[serde(skip_serializing_if = "FailureCapturePolicy::is_disabled")]
            capture_on_failure: FailureCapturePolicy,
        }

        FlowRef {
            schema_version: if self.has_until() { 4 } else { 3 },
            steps: &self.steps,
            timeout: self.timeout,
            on_failure: self.on_failure,
            on_cancellation: self.on_cancellation,
            capture_on_failure: self.capture_on_failure,
        }
        .serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for Flow {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct FlowWire {
            #[serde(default)]
            schema_version: Option<u32>,
            #[serde(default)]
            steps: Vec<Step>,
            #[serde(default)]
            timeout: Option<Duration>,
            #[serde(default)]
            timeout_us: Option<u64>,
            #[serde(default)]
            timeout_ms: Option<u64>,
            #[serde(default)]
            on_failure: Option<Continuation>,
            #[serde(default)]
            on_cancellation: Option<Continuation>,
            #[serde(default)]
            capture_on_failure: FailureCapturePolicy,
        }

        let wire = FlowWire::deserialize(deserializer)?;
        let timeout = match wire.schema_version {
            None | Some(1) if wire.timeout.is_none() && wire.timeout_ms.is_none() => {
                wire.timeout_us.map(Duration::from_micros)
            }
            Some(2..=4) if wire.timeout_us.is_none() && wire.timeout_ms.is_none() => wire.timeout,
            None | Some(1) => {
                return Err(D::Error::custom(
                    "legacy Flow schema accepts only timeout_us; timeout values use microseconds",
                ));
            }
            Some(2..=4) => {
                return Err(D::Error::custom(
                    "Flow schemas 2, 3 and 4 accept only their unit-bearing timeout field",
                ));
            }
            Some(version) => {
                return Err(D::Error::custom(format!(
                    "Flow schema version {version} is unsupported; this build supports 1, 2, 3 and 4"
                )));
            }
        };

        if matches!(wire.schema_version, None | Some(1 | 2))
            && (wire.on_failure.is_some()
                || wire.on_cancellation.is_some()
                || wire.steps.iter().any(Step::has_local_continuation_settings))
        {
            return Err(D::Error::custom(
                "Flow schemas 1 and 2 cannot represent continuation overrides",
            ));
        }

        let flow = Self {
            steps: wire.steps,
            timeout,
            on_failure: wire.on_failure,
            on_cancellation: wire.on_cancellation,
            capture_on_failure: wire.capture_on_failure,
        };
        if wire.schema_version != Some(4) && flow.has_until() {
            return Err(D::Error::custom("waiting assertions require Flow schema 4"));
        }
        Ok(flow)
    }
}

impl Flow {
    pub(crate) fn has_until(&self) -> bool {
        self.steps.iter().any(|step| match step.operation() {
            Step::Until { .. } => true,
            Step::NestedFlow { flow } => flow.has_until(),
            _ => false,
        })
    }
    /// Acquires a Session and lease, executes this recipe, and closes owned resources.
    /// Include a Navigate action when the recipe needs an initial page.
    /// Inspect the returned terminal status and receipts to determine success.
    pub async fn invoke(&self) -> Result<FlowOutcome, FlowInvokeError> {
        Box::pin(execution::invoke(
            self,
            None,
            None,
            &CancellationToken::new(),
            false,
        ))
        .await
    }

    /// Sets the inherited action timeout for this Flow, in milliseconds.
    /// A nearer nested Flow or action timeout overrides it.
    pub const fn timeout(mut self, milliseconds: u64) -> Self {
        self.timeout = Some(Duration::from_millis(milliseconds));
        self
    }

    /// Sets this Flow's failure behavior; a child or leaf override takes precedence.
    pub const fn on_failure(mut self, continuation: Continuation) -> Self {
        self.on_failure = Some(continuation);
        self
    }

    /// Sets this Flow's local cancellation behavior; a child or leaf override takes precedence.
    pub const fn on_cancellation(mut self, continuation: Continuation) -> Self {
        self.on_cancellation = Some(continuation);
        self
    }

    /// Optionally supplies an application-owned stop signal; invoke is always cancellable.
    pub const fn with_cancellation<'a>(&'a self, token: &'a CancellationToken) -> BoundFlow<'a> {
        BoundFlow {
            flow: self,
            policy: None,
            lease: None,
            cancellation: Some(token),
            allow_javascript: false,
        }
    }

    /// Configures an invocation's policy without executing or acquiring resources.
    /// Without a supplied lease, invoke acquires and closes its own Session.
    pub const fn bind<'a>(&'a self, policy: &'a Policy) -> BoundFlow<'a> {
        BoundFlow {
            flow: self,
            policy: Some(policy),
            lease: None,
            cancellation: None,
            allow_javascript: false,
        }
    }

    /// Configures this invocation to borrow the caller's existing tab lease.
    /// This does not execute, acquire another lease, or take ownership of cleanup.
    /// Invoke runs on the lease's current tab; the caller releases it afterward.
    pub const fn with_lease<'a>(&'a self, lease: &'a Work) -> BoundFlow<'a> {
        BoundFlow {
            flow: self,
            policy: None,
            lease: Some(lease),
            cancellation: None,
            allow_javascript: false,
        }
    }

    /// Creates a flow from ordered steps.
    pub fn new(steps: impl IntoIterator<Item = Step>) -> Self {
        Self {
            steps: steps.into_iter().collect(),
            timeout: None,
            on_failure: None,
            on_cancellation: None,
            capture_on_failure: FailureCapturePolicy::Disabled,
        }
    }

    /// Selects whether one bounded screenshot is captured after a failed or
    /// unknown step.
    pub const fn with_failure_capture(mut self, policy: FailureCapturePolicy) -> Self {
        self.capture_on_failure = policy;
        self
    }

    /// Returns the configured post-failure capture policy.
    pub const fn failure_capture_policy(&self) -> FailureCapturePolicy {
        self.capture_on_failure
    }

    /// Returns the steps in their authored order.
    pub fn steps(&self) -> &[Step] {
        &self.steps
    }

    pub(crate) const fn timeout_duration(&self) -> Option<Duration> {
        self.timeout
    }

    pub(crate) const fn on_failure_override(&self) -> Option<Continuation> {
        self.on_failure
    }

    pub(crate) const fn on_cancellation_override(&self) -> Option<Continuation> {
        self.on_cancellation
    }

    pub(crate) fn has_continuation_configuration(&self) -> bool {
        self.on_failure.is_some()
            || self.on_cancellation.is_some()
            || self.steps.iter().any(|step| {
                step.has_local_continuation_settings()
                    || match step.operation() {
                        Step::NestedFlow { flow } => flow.has_continuation_configuration(),
                        _ => false,
                    }
            })
    }

    /// Validates the flow using conservative SDK input limits.
    pub fn validate(&self) -> Result<(), FlowValidationError> {
        self.validate_with_limits(FlowLimits::default())
    }

    /// Validates the flow using the supplied step and input bounds.
    pub fn validate_with_limits(&self, limits: FlowLimits) -> Result<(), FlowValidationError> {
        let mut step_count = 0_u128;
        validate_flow(self, limits, 0, &mut step_count)?;
        let encoded = serde_json::to_vec(self)
            .map_err(|error| FlowValidationError::Serialization(error.to_string()))?;
        if encoded.len() > limits.max_serialized_bytes {
            return Err(FlowValidationError::SerializedInputTooLarge {
                actual: encoded.len(),
                maximum: limits.max_serialized_bytes,
            });
        }
        Ok(())
    }
}

/// A configured invocation borrowing its recipe, policy, and optional tab lease.
///
/// Configuration does not acquire resources or run actions. Without a lease,
/// invoke owns acquisition and cleanup; with a lease, cleanup stays with its caller.
#[derive(Debug)]
pub struct BoundFlow<'a> {
    flow: &'a Flow,
    policy: Option<&'a Policy>,
    lease: Option<&'a Work>,
    cancellation: Option<&'a CancellationToken>,
    allow_javascript: bool,
}

impl<'a> BoundFlow<'a> {
    /// Explicitly permits JavaScript when this invocation acquires its own Session.
    /// A borrowed lease retains its Session's permission; this cannot elevate it.
    pub const fn allow_javascript(mut self) -> Self {
        self.allow_javascript = true;
        self
    }
    /// Applies this policy within the supplied Session's existing permission limits.
    /// This configures the invocation without executing it or changing its recipe.
    pub const fn bind(mut self, policy: &'a Policy) -> Self {
        self.policy = Some(policy);
        self
    }

    /// Uses the caller's existing lease without acquiring control or owning cleanup.
    /// This configures the invocation without executing it or changing its recipe.
    pub const fn with_lease(mut self, lease: &'a Work) -> Self {
        self.lease = Some(lease);
        self
    }

    /// Executes using the configured lease, or acquires and closes its own Session.
    pub async fn invoke(&self) -> Result<FlowOutcome, FlowInvokeError> {
        let internal = CancellationToken::new();
        Box::pin(execution::invoke(
            self.flow,
            self.policy,
            self.lease,
            self.cancellation.unwrap_or(&internal),
            self.allow_javascript,
        ))
        .await
    }

    /// Supplies an optional external stop signal without selecting a different executor.
    pub const fn with_cancellation(mut self, token: &'a CancellationToken) -> Self {
        self.cancellation = Some(token);
        self
    }
}
