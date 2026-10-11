//! Serializable Flow actions, outcomes and validation vocabulary.

use super::Flow;
pub use crate::internal::policy::policy::{Continuation, FlowPolicy, StopScope};
use crate::request::CancellationToken;
use crate::{
    action::{JavaScriptModuleBundle, JavaScriptSourceSnapshot},
    assertions::LocalAssertion,
    automation_record::OperationReceipt,
    expect::{Expectation, UntilExpectation},
};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::{error::Error, fmt, time::Duration};

/// Conservative limits applied to authored flow steps and string inputs.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FlowLimits {
    /// Maximum number of step and wrapper nodes across the root and nested Flows.
    pub max_steps: u64,
    /// Maximum number of nested Flow levels below the root Flow.
    pub max_depth: u32,
    /// Maximum UTF-8 bytes allowed in any CSS selector.
    pub max_selector_bytes: usize,
    /// Maximum UTF-8 bytes allowed in one Evaluate source string.
    pub max_source_bytes: usize,
    /// Maximum encoded JSON bytes for a complete Flow definition.
    pub max_serialized_bytes: usize,
}

impl Default for FlowLimits {
    fn default() -> Self {
        Self {
            max_steps: 128,
            max_depth: 8,
            max_selector_bytes: 4_096,
            max_source_bytes: 65_536,
            max_serialized_bytes: 1_048_576,
        }
    }
}

/// One typed action or assertion in a flow.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Step {
    /// Local Rust checks over one current Contract observation.
    AssertAll { assertion: LocalAssertion },
    /// Waits for an expectation, optionally after one trigger action.
    ///
    /// With a trigger, observation starts before that action is dispatched and
    /// the trigger executes once. One timeout covers both the action and wait.
    Until {
        /// One supported action, executed once after observation starts.
        trigger: Option<Box<Step>>,
        /// Serializable, bounded expectation data.
        expectation: Expectation,
    },
    /// Applies one execution budget to the complete action.
    Timed {
        action: Box<Step>,
        timeout: Duration,
    },
    /// Local continuation overrides and optional runtime cancellation binding.
    Configured {
        action: Box<Step>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        on_failure: Option<Continuation>,
        #[serde(default, skip_serializing_if = "Option::is_none")]
        on_cancellation: Option<Continuation>,
        #[serde(default, skip_serializing_if = "is_false")]
        cancellation_binding_required: bool,
        #[serde(skip)]
        cancellation: StepCancellationBinding,
    },
    /// Runs a child Flow as a nested timeout scope.
    NestedFlow { flow: Box<Flow> },
    /// Navigate the current tab to a URL.
    Navigate { url: String },
    /// Click one selector-resolved target.
    Click { selector: String },
    /// Enter text into one selector-resolved target.
    EnterText { selector: String, text: String },
    /// Wait for an explicit number of milliseconds.
    Wait { milliseconds: u64 },
    /// Capture the current tab's screenshot.
    Screenshot,
    /// Check a condition once and stop if it is rejected.
    Assert { condition: Condition },
    /// Check a condition until the supplied positive timeout expires.
    WaitUntil {
        condition: Condition,
        timeout_ms: u64,
    },
    /// Evaluate a policy-approved script on the current tab.
    Evaluate { source: String },
    /// Evaluates an exact construction-time file snapshot as a script.
    EvaluateFile { snapshot: JavaScriptSourceSnapshot },
    /// Executes a construction-time local ES module graph.
    EvaluateModule { bundle: JavaScriptModuleBundle },
}

impl<'de> Deserialize<'de> for Step {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
        enum StepWire {
            AssertAll {
                assertion: LocalAssertion,
            },
            Until {
                #[serde(default)]
                trigger: Option<Box<Step>>,
                expectation: Expectation,
            },
            Timed {
                action: Box<Step>,
                #[serde(default)]
                timeout: Option<Duration>,
                #[serde(default)]
                timeout_us: Option<u64>,
            },
            Configured {
                action: Box<Step>,
                #[serde(default)]
                on_failure: Option<Continuation>,
                #[serde(default)]
                on_cancellation: Option<Continuation>,
                #[serde(default)]
                cancellation_binding_required: bool,
            },
            NestedFlow {
                flow: Box<Flow>,
            },
            Navigate {
                url: String,
            },
            Click {
                selector: String,
            },
            EnterText {
                selector: String,
                text: String,
            },
            Wait {
                milliseconds: u64,
            },
            Screenshot,
            Assert {
                condition: Condition,
            },
            WaitUntil {
                condition: Condition,
                timeout_ms: u64,
            },
            Evaluate {
                source: String,
            },
            EvaluateFile {
                snapshot: JavaScriptSourceSnapshot,
            },
            EvaluateModule {
                bundle: JavaScriptModuleBundle,
            },
        }

        match StepWire::deserialize(deserializer)? {
            StepWire::AssertAll { assertion } => Ok(Self::AssertAll { assertion }),
            StepWire::Until {
                trigger,
                expectation,
            } => Ok(Self::Until {
                trigger,
                expectation,
            }),
            StepWire::Timed {
                action,
                timeout: Some(timeout),
                timeout_us: None,
            } => Ok(Self::Timed { action, timeout }),
            StepWire::Timed {
                action,
                timeout: None,
                timeout_us: Some(timeout_us),
            } => Ok(Self::Timed {
                action,
                timeout: Duration::from_micros(timeout_us),
            }),
            StepWire::Timed { .. } => Err(D::Error::custom(
                "timed action requires exactly one timeout field; timeout_us values are microseconds",
            )),
            StepWire::Configured {
                action,
                on_failure,
                on_cancellation,
                cancellation_binding_required,
            } => Ok(Self::Configured {
                action,
                on_failure,
                on_cancellation,
                cancellation_binding_required,
                cancellation: StepCancellationBinding::default(),
            }),
            StepWire::NestedFlow { flow } => Ok(Self::NestedFlow { flow }),
            StepWire::Navigate { url } => Ok(Self::Navigate { url }),
            StepWire::Click { selector } => Ok(Self::Click { selector }),
            StepWire::EnterText { selector, text } => Ok(Self::EnterText { selector, text }),
            StepWire::Wait { milliseconds } => Ok(Self::Wait { milliseconds }),
            StepWire::Screenshot => Ok(Self::Screenshot),
            StepWire::Assert { condition } => Ok(Self::Assert { condition }),
            StepWire::WaitUntil {
                condition,
                timeout_ms,
            } => Ok(Self::WaitUntil {
                condition,
                timeout_ms,
            }),
            StepWire::Evaluate { source } => Ok(Self::Evaluate { source }),
            StepWire::EvaluateFile { snapshot } => Ok(Self::EvaluateFile { snapshot }),
            StepWire::EvaluateModule { bundle } => Ok(Self::EvaluateModule { bundle }),
        }
    }
}

#[doc(hidden)]
#[derive(Clone, Debug, Default)]
pub struct StepCancellationBinding(Option<CancellationToken>);

impl PartialEq for StepCancellationBinding {
    fn eq(&self, _other: &Self) -> bool {
        true
    }
}
impl Eq for StepCancellationBinding {}

struct ConfiguredStep {
    action: Box<Step>,
    on_failure: Option<Continuation>,
    on_cancellation: Option<Continuation>,
    cancellation_binding_required: bool,
    cancellation: StepCancellationBinding,
}

#[derive(Clone, Debug, Default)]
struct StepSettings {
    timeout: Option<Duration>,
    on_failure: Option<Continuation>,
    on_cancellation: Option<Continuation>,
    cancellation_binding_required: bool,
    cancellation: Option<CancellationToken>,
}

impl StepSettings {
    /// Applies the explicit settings in `nearer` over inherited trigger settings.
    fn overlay(self, nearer: Self) -> Self {
        Self {
            timeout: nearer.timeout.or(self.timeout),
            on_failure: nearer.on_failure.or(self.on_failure),
            on_cancellation: nearer.on_cancellation.or(self.on_cancellation),
            cancellation_binding_required: self.cancellation_binding_required
                || nearer.cancellation_binding_required,
            cancellation: nearer.cancellation.or(self.cancellation),
        }
    }

    fn apply(self, action: Step) -> Step {
        let action = if self.on_failure.is_some()
            || self.on_cancellation.is_some()
            || self.cancellation_binding_required
            || self.cancellation.is_some()
        {
            Step::Configured {
                action: Box::new(action),
                on_failure: self.on_failure,
                on_cancellation: self.on_cancellation,
                cancellation_binding_required: self.cancellation_binding_required,
                cancellation: StepCancellationBinding(self.cancellation),
            }
        } else {
            action
        };
        match self.timeout {
            Some(timeout) => Step::Timed {
                action: Box::new(action),
                timeout,
            },
            None => action,
        }
    }
}

fn is_false(value: &bool) -> bool {
    !*value
}

impl From<Flow> for Step {
    fn from(flow: Flow) -> Self {
        Self::NestedFlow {
            flow: Box::new(flow),
        }
    }
}

impl Step {
    /// Executes this action once, then waits until `expectation` is observed.
    ///
    /// The trigger's outer timeout, continuation, and cancellation settings are
    /// lifted to the complete Until step. Explicit settings carried by a local
    /// Contract assertion take precedence over the trigger settings.
    pub fn until(self, expectation: impl Into<UntilExpectation>) -> Self {
        let (trigger, trigger_settings) = self.into_until_parts();
        Self::compose_until(
            Some(Box::new(trigger)),
            expectation.into(),
            trigger_settings,
        )
    }

    pub(crate) fn until_without_trigger(expectation: impl Into<UntilExpectation>) -> Self {
        Self::compose_until(None, expectation.into(), StepSettings::default())
    }

    fn compose_until(
        trigger: Option<Box<Step>>,
        expected: UntilExpectation,
        trigger_settings: StepSettings,
    ) -> Self {
        let settings = trigger_settings.overlay(StepSettings {
            timeout: expected.timeout,
            on_failure: expected.on_failure,
            on_cancellation: expected.on_cancellation,
            cancellation_binding_required: expected.cancellation.is_some(),
            cancellation: expected.cancellation,
        });
        settings.apply(Self::Until {
            trigger,
            expectation: expected.expectation,
        })
    }

    fn into_until_parts(self) -> (Step, StepSettings) {
        let mut operation = self;
        let mut settings = StepSettings::default();
        loop {
            match operation {
                Self::Timed { action, timeout } => {
                    if settings.timeout.is_none() {
                        settings.timeout = Some(timeout);
                    }
                    operation = *action;
                }
                Self::Configured {
                    action,
                    on_failure,
                    on_cancellation,
                    cancellation_binding_required,
                    cancellation,
                } => {
                    if settings.on_failure.is_none() {
                        settings.on_failure = on_failure;
                    }
                    if settings.on_cancellation.is_none() {
                        settings.on_cancellation = on_cancellation;
                    }
                    settings.cancellation_binding_required |= cancellation_binding_required;
                    if settings.cancellation.is_none() {
                        settings.cancellation = cancellation.0;
                    }
                    operation = *action;
                }
                operation => return (operation, settings),
            }
        }
    }

    /// Sets this action's timeout in milliseconds; a second call replaces the first.
    pub fn timeout(self, milliseconds: u64) -> Self {
        let action = match self {
            Self::Timed { action, .. } => action,
            action => Box::new(action),
        };
        Self::Timed {
            action,
            timeout: Duration::from_millis(milliseconds),
        }
    }

    /// Overrides failure handling for this action or nested Flow.
    pub fn on_failure(self, continuation: Continuation) -> Self {
        self.configure(|configured| configured.on_failure = Some(continuation))
    }

    /// Overrides local cancellation handling for this action or nested Flow.
    pub fn on_cancellation(self, continuation: Continuation) -> Self {
        self.configure(|configured| configured.on_cancellation = Some(continuation))
    }

    /// Binds a step-local cancellation token that may stop this action or child Flow.
    /// The runtime token is omitted from serialized recipes; rebind it after loading.
    pub fn with_cancellation(self, token: &CancellationToken) -> Self {
        self.configure(|configured| {
            configured.cancellation_binding_required = true;
            configured.cancellation = StepCancellationBinding(Some(token.clone()));
        })
    }

    /// Restores the runtime authority omitted when a cancellation-bound step was serialized.
    pub fn rebind_cancellation(self, token: &CancellationToken) -> Self {
        self.configure(|configured| {
            configured.cancellation_binding_required = true;
            configured.cancellation = StepCancellationBinding(Some(token.clone()));
        })
    }

    fn configure(self, update: impl FnOnce(&mut ConfiguredStep)) -> Self {
        let mut configured = match self {
            Self::Configured {
                action,
                on_failure,
                on_cancellation,
                cancellation_binding_required,
                cancellation,
            } => ConfiguredStep {
                action,
                on_failure,
                on_cancellation,
                cancellation_binding_required,
                cancellation,
            },
            action => ConfiguredStep {
                action: Box::new(action),
                on_failure: None,
                on_cancellation: None,
                cancellation_binding_required: false,
                cancellation: StepCancellationBinding::default(),
            },
        };
        update(&mut configured);
        Self::Configured {
            action: configured.action,
            on_failure: configured.on_failure,
            on_cancellation: configured.on_cancellation,
            cancellation_binding_required: configured.cancellation_binding_required,
            cancellation: configured.cancellation,
        }
    }

    pub(crate) fn operation(&self) -> &Step {
        match self {
            Self::Timed { action, .. } | Self::Configured { action, .. } => action.operation(),
            action => action,
        }
    }

    pub(crate) fn timeout_duration(&self) -> Option<Duration> {
        match self {
            Self::Timed { timeout, .. } => Some(*timeout),
            Self::Configured { action, .. } => action.timeout_duration(),
            _ => None,
        }
    }

    pub(crate) fn failure_override(&self) -> Option<Continuation> {
        match self {
            Self::Configured {
                on_failure, action, ..
            } => on_failure.or_else(|| action.failure_override()),
            Self::Timed { action, .. } => action.failure_override(),
            _ => None,
        }
    }

    pub(crate) fn cancellation_override(&self) -> Option<Continuation> {
        match self {
            Self::Configured {
                on_cancellation,
                action,
                ..
            } => on_cancellation.or_else(|| action.cancellation_override()),
            Self::Timed { action, .. } => action.cancellation_override(),
            _ => None,
        }
    }

    pub(crate) fn cancellation_token(&self) -> Option<&CancellationToken> {
        match self {
            Self::Configured {
                cancellation,
                action,
                ..
            } => cancellation
                .0
                .as_ref()
                .or_else(|| action.cancellation_token()),
            Self::Timed { action, .. } => action.cancellation_token(),
            _ => None,
        }
    }

    pub(crate) fn requires_cancellation_binding(&self) -> bool {
        match self {
            Self::Configured {
                cancellation_binding_required,
                cancellation,
                action,
                ..
            } => {
                (*cancellation_binding_required && cancellation.0.is_none())
                    || action.requires_cancellation_binding()
            }
            Self::Timed { action, .. } => action.requires_cancellation_binding(),
            Self::Until { trigger, .. } => trigger
                .as_deref()
                .is_some_and(Step::requires_cancellation_binding),
            _ => false,
        }
    }

    pub(super) fn has_local_continuation_settings(&self) -> bool {
        match self {
            Self::Configured {
                action,
                on_failure,
                on_cancellation,
                cancellation_binding_required,
                ..
            } => {
                on_failure.is_some()
                    || on_cancellation.is_some()
                    || *cancellation_binding_required
                    || (!matches!(action.operation(), Self::NestedFlow { .. })
                        && action.has_local_continuation_settings())
            }
            Self::Timed { action, .. } => action.has_local_continuation_settings(),
            Self::Until { trigger, .. } => trigger
                .as_deref()
                .is_some_and(Step::has_local_continuation_settings),
            Self::NestedFlow { .. } => false,
            _ => false,
        }
    }

    pub(crate) fn has_nested_timeout(&self) -> bool {
        match self {
            Self::Timed { action, .. } => {
                matches!(action.operation(), Self::NestedFlow { .. })
                    || action.has_nested_timeout()
                    || action.timeout_duration().is_some()
            }
            Self::Configured { action, .. } => action.has_nested_timeout(),
            Self::Until { trigger, .. } => trigger.as_deref().is_some_and(|trigger| {
                trigger.has_nested_timeout() || trigger.timeout_duration().is_some()
            }),
            _ => false,
        }
    }

    pub(crate) fn wrapper_count(&self) -> u32 {
        let mut current = self;
        let mut count = 0_u32;
        loop {
            match current {
                Self::Timed { action, .. } | Self::Configured { action, .. } => {
                    count = match count.checked_add(1) {
                        Some(count) => count,
                        None => return u32::MAX,
                    };
                    current = action;
                }
                _ => return count,
            }
        }
    }
    pub(crate) const fn kind(&self) -> &'static str {
        match self {
            Self::AssertAll { .. } => "assert_all",
            Self::Until { .. } => "until",
            Self::Timed { action, .. } => action.kind(),
            Self::Configured { action, .. } => action.kind(),
            Self::NestedFlow { .. } => "nested_flow",
            Self::Navigate { .. } => "navigate",
            Self::Click { .. } => "click",
            Self::EnterText { .. } => "enter_text",
            Self::Wait { .. } => "wait",
            Self::Screenshot => "screenshot",
            Self::Assert { .. } => "assert",
            Self::WaitUntil { .. } => "wait_until",
            Self::Evaluate { .. } => "evaluate",
            Self::EvaluateFile { .. } => "evaluate_file",
            Self::EvaluateModule { .. } => "evaluate_module",
        }
    }
}

/// A typed condition evaluated against the current tab state.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum Condition {
    /// At least one element matches the selector.
    Exists { selector: String },
    /// At least one matching element is visible.
    Visible { selector: String },
    /// The number of matching elements meets or exceeds `count`.
    CountAtLeast { selector: String, count: u64 },
}

/// Why the runner stopped executing the flow.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlowTermination {
    /// Every step returned an observed receipt.
    Completed,
    /// Every selected scope finished; retained failures, cancellations, or skips remain.
    CompletedWithIssues,
    /// A failure policy stopped the current Flow or invocation.
    Failed,
    /// A dispatched operation may have completed without a known result.
    Unknown,
    /// A local or invocation cancellation stopped the selected scope.
    Cancelled,
}

/// The result record for one ordered flow step.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct StepOutcome {
    /// Zero-based position in the flattened execution result.
    pub index: u64,
    /// Nested Flow step indexes followed by the action's local step index.
    /// Older flat outcomes omit this path.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub flow_path: Vec<u64>,
    /// The observed, rejected, or unknown operation receipt.
    pub receipt: OperationReceipt,
    /// Failure classification, separate from the operation effect receipt.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure: Option<FlowFailureCause>,
    /// Cancellation source, separate from the operation effect receipt.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cancellation: Option<FlowCancellationCause>,
    /// Nested Flow node whose step-local token cancelled this leaf's subtree.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub cancelled_flow: Option<Vec<u64>>,
}

/// Why an attempted Flow step failed.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlowFailureCause {
    /// The action returned a known rejection.
    Rejected,
    /// The action failed before an operation receipt was returned.
    Execution,
    /// A dispatched operation may have changed the browser without an observed result.
    UnknownOutcome,
}

/// Which cancellation authority stopped an attempted Flow step.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlowCancellationCause {
    /// The explicitly bound token for this Step or nested Flow was cancelled.
    Step,
    /// The invocation cancellation token was cancelled.
    Invocation,
    /// The owning Session or tab authority was revoked.
    Session,
}

/// Why execution stopped at an invocation boundary.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FlowStopCause {
    Failure,
    Cancellation,
    UnknownOutcome,
    UnsafeState,
}

/// The event and scope that stopped the invocation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct FlowStopReason {
    /// Path of the leaf that triggered the stop; empty if cancelled before the first leaf.
    pub flow_path: Vec<u64>,
    pub cause: FlowStopCause,
    /// The authored continuation policy, absent for hard safety stops.
    pub continuation: Option<Continuation>,
}

/// One leaf omitted after a scoped or invocation stop.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SkippedStep {
    /// Nested Flow indexes followed by the omitted leaf's local step index.
    pub flow_path: Vec<u64>,
    /// Path of the action that stopped the selected scope.
    pub stopped_by: Vec<u64>,
    pub cause: FlowStopCause,
    pub scope: StopScope,
}

/// The flow definition and every operation result retained before termination.
#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct FlowOutcome {
    /// Flow outcome schema version. Version 3 records continuation and skipped paths.
    pub version: u32,
    /// Flow definition that was executed.
    pub flow: Flow,
    /// Completed and terminal step records in execution order.
    pub steps: Vec<StepOutcome>,
    /// Whether execution completed or stopped early.
    pub terminal: FlowTermination,
    /// Global fallback policies used for this invocation.
    /// Legacy outcomes use Continue for both events.
    #[serde(default)]
    pub continuation_defaults: FlowPolicy,
    /// Reason execution stopped, when a hard stop or authored Stop policy applied.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub stop_reason: Option<FlowStopReason>,
    /// Leaves omitted by a scoped stop, each with its trigger path and reason.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub skipped_steps: Vec<SkippedStep>,
    /// Managed release and close evidence, retained after execution starts.
    #[serde(default, skip_serializing_if = "Vec::is_empty")]
    pub cleanup: Vec<OperationReceipt>,
    /// Optional screenshot result captured after a failed or unknown step.
    /// A rejected or unknown receipt records a capture error without replacing
    /// the original terminal status or step receipts.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub failure_capture: Option<OperationReceipt>,
}

impl Serialize for FlowOutcome {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        if self.version < 3
            && (self.continuation_defaults != FlowPolicy::default()
                || self.flow.has_continuation_configuration()
                || self.stop_reason.is_some()
                || !self.skipped_steps.is_empty()
                || !self.cleanup.is_empty()
                || self.steps.iter().any(|step| {
                    step.failure.is_some()
                        || step.cancellation.is_some()
                        || step.cancelled_flow.is_some()
                }))
        {
            return Err(<S::Error as serde::ser::Error>::custom(
                "legacy Flow outcome versions cannot represent continuation settings",
            ));
        }
        #[derive(Serialize)]
        struct FlowOutcomeRef<'a> {
            version: u32,
            flow: &'a Flow,
            steps: &'a [StepOutcome],
            terminal: FlowTermination,
            #[serde(skip_serializing_if = "Option::is_none")]
            continuation_defaults: Option<&'a FlowPolicy>,
            #[serde(skip_serializing_if = "Option::is_none")]
            stop_reason: Option<&'a FlowStopReason>,
            #[serde(skip_serializing_if = "is_empty_slice")]
            skipped_steps: &'a [SkippedStep],
            #[serde(skip_serializing_if = "is_empty_slice")]
            cleanup: &'a [OperationReceipt],
            #[serde(skip_serializing_if = "Option::is_none")]
            failure_capture: Option<&'a OperationReceipt>,
        }

        FlowOutcomeRef {
            version: self.version,
            flow: &self.flow,
            steps: &self.steps,
            terminal: self.terminal,
            continuation_defaults: (self.version >= 3).then_some(&self.continuation_defaults),
            stop_reason: self.stop_reason.as_ref(),
            skipped_steps: &self.skipped_steps,
            cleanup: &self.cleanup,
            failure_capture: self.failure_capture.as_ref(),
        }
        .serialize(serializer)
    }
}

fn is_empty_slice<T>(value: &&[T]) -> bool {
    value.is_empty()
}

impl FlowOutcome {
    /// Requires actual completion while leaving this outcome/evidence available.
    pub fn require_completed(&self) -> Result<(), FlowCompletionError> {
        if self.terminal == FlowTermination::Completed
            && self.stop_reason.is_none()
            && self.skipped_steps.is_empty()
            && self.cleanup.iter().all(|receipt| {
                receipt.status == crate::automation_record::OperationStatus::Observed
            })
            && self.steps.iter().all(|step| {
                step.receipt.status == crate::automation_record::OperationStatus::Observed
                    && step.failure.is_none()
                    && step.cancellation.is_none()
            })
        {
            Ok(())
        } else {
            Err(FlowCompletionError {
                terminal: self.terminal,
            })
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct FlowCompletionError {
    pub terminal: FlowTermination,
}
impl fmt::Display for FlowCompletionError {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        write!(f, "Flow did not complete: {:?}", self.terminal)
    }
}
impl Error for FlowCompletionError {}

/// Whether the flow captures one screenshot after a failed or unknown step.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum FailureCapturePolicy {
    /// Do not capture additional evidence after termination.
    #[default]
    Disabled,
    /// Capture one screenshot using the same active Work lease.
    Screenshot,
}

impl FailureCapturePolicy {
    pub(super) const fn is_disabled(&self) -> bool {
        matches!(self, Self::Disabled)
    }
}

#[cfg(test)]
mod until_tests;
