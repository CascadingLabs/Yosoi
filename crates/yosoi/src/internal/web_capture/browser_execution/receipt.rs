use crate::internal::types::CaptureId;
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::{
    BrowserContextLease, BrowserExecutionLease, BrowserExecutionLimits, BrowserExecutionScope,
    BrowserSessionLease, BrowserTabLease,
};

/// Error returned when a browser execution receipt contradicts its own scope or accounting.
///
/// Variants intentionally contain no provider diagnostics, URLs, headers, cookies, or tokens.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserExecutionReceiptError {
    #[error("context lease does not belong to the admitted execution")]
    ContextOutsideExecution,
    #[error("session lease does not belong to the admitted context")]
    SessionOutsideContext,
    #[error("tab lease does not belong to the admitted session")]
    TabOutsideSession,
    #[error("cleanup receipt does not belong to the admitted execution")]
    CleanupOutsideAdmission,
    #[error("accounting receipt does not belong to the terminal execution")]
    AccountingOutsideTerminal,
    #[error("a durable execution receipt requires terminal accounting")]
    ReceiptWithoutTerminalAccounting,
    #[error("terminal completion requires completed context cleanup")]
    CompletionWithoutCompletedContextCleanup,
    #[error("terminal completion cannot have failed or deadline-exceeded process cleanup")]
    CompletionWithUnsuccessfulProcessCleanup,
    #[error("terminal context-cleanup reason contradicts the cleanup disposition")]
    ContextCleanupReasonMismatch,
    #[error("terminal process-cleanup reason contradicts the cleanup disposition")]
    ProcessCleanupReasonMismatch,
    #[error("an admission accounting snapshot requires at least one active process")]
    NoActiveProcess,
    #[error("active process count exceeds the process limit")]
    ProcessLimitExceeded,
    #[error("an admission accounting snapshot requires at least one active context")]
    NoActiveContext,
    #[error("an admission accounting snapshot requires an active context in its process")]
    NoActiveContextInProcess,
    #[error("active context count exceeds the total context limit")]
    ContextTotalLimitExceeded,
    #[error("active contexts in the execution process exceed the per-process limit")]
    ContextPerProcessLimitExceeded,
    #[error("active contexts in one process exceed all active contexts")]
    ContextScopeExceedsTotal,
    #[error("active contexts exceed the capacity of the active processes")]
    ContextsExceedActiveProcessCapacity,
    #[error("active contexts require at least one active process")]
    ContextsWithoutActiveProcess,
    #[error("an admission accounting snapshot requires at least one active tab")]
    NoActiveTab,
    #[error("an admission accounting snapshot requires an active tab in its session")]
    NoActiveTabInSession,
    #[error("active tab count exceeds the total tab limit")]
    TabTotalLimitExceeded,
    #[error("active tabs in the execution session exceed the per-session limit")]
    TabPerSessionLimitExceeded,
    #[error("active tabs in one session exceed all active tabs")]
    TabScopeExceedsTotal,
    #[error("active contexts require at least one active tab each")]
    ActiveContextsExceedActiveTabs,
    #[error("active tabs require at least one active context")]
    TabsWithoutActiveContext,
    #[error("active session tabs require an active context in their process")]
    SessionTabsWithoutActiveContext,
    #[error("a terminal accounting snapshot requires zero tabs in the released session")]
    TerminalSessionTabsRemain,
    #[error("queue depth exceeds the configured limit")]
    QueueDepthExceeded,
    #[error("completed executions since recycle exceed the recycle threshold")]
    RecycleThresholdExceeded,
    #[error("terminal accounting must include the completed execution in its process generation")]
    TerminalExecutionNotCounted,
    #[error("retained or unsuccessfully closed process cleanup requires an active process")]
    CleanupRequiresActiveProcess,
    #[error("process close cleanup cannot retain contexts in the completed execution generation")]
    ClosedProcessHasActiveContexts,
    #[error("unsuccessful context cleanup cannot leave the process warm for new admissions")]
    UnsuccessfulContextCleanupWarmRetained,
}

/// Closed proof that one execution was admitted with one coherent lease scope.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionAdmissionReceipt {
    scope: BrowserExecutionScope,
    execution: BrowserExecutionLease,
    context: BrowserContextLease,
    session: BrowserSessionLease,
    tab: BrowserTabLease,
}

impl BrowserExecutionAdmissionReceipt {
    pub fn new(
        scope: BrowserExecutionScope,
        execution: BrowserExecutionLease,
        context: BrowserContextLease,
        session: BrowserSessionLease,
        tab: BrowserTabLease,
    ) -> Result<Self, BrowserExecutionReceiptError> {
        if context.execution() != &execution {
            return Err(BrowserExecutionReceiptError::ContextOutsideExecution);
        }
        if session.context() != &context {
            return Err(BrowserExecutionReceiptError::SessionOutsideContext);
        }
        if tab.session() != &session {
            return Err(BrowserExecutionReceiptError::TabOutsideSession);
        }
        Ok(Self {
            scope,
            execution,
            context,
            session,
            tab,
        })
    }

    pub const fn scope(&self) -> BrowserExecutionScope {
        self.scope
    }

    pub const fn execution(&self) -> &BrowserExecutionLease {
        &self.execution
    }

    pub const fn context(&self) -> &BrowserContextLease {
        &self.context
    }

    pub const fn session(&self) -> &BrowserSessionLease {
        &self.session
    }

    pub const fn tab(&self) -> &BrowserTabLease {
        &self.tab
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionAdmissionReceiptWire {
    scope: BrowserExecutionScope,
    execution: BrowserExecutionLease,
    context: BrowserContextLease,
    session: BrowserSessionLease,
    tab: BrowserTabLease,
}

impl TryFrom<BrowserExecutionAdmissionReceiptWire> for BrowserExecutionAdmissionReceipt {
    type Error = BrowserExecutionReceiptError;

    fn try_from(value: BrowserExecutionAdmissionReceiptWire) -> Result<Self, Self::Error> {
        Self::new(
            value.scope,
            value.execution,
            value.context,
            value.session,
            value.tab,
        )
    }
}

impl<'de> Deserialize<'de> for BrowserExecutionAdmissionReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserExecutionAdmissionReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Observed cleanup result for the disposable context owned by an execution.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserContextCleanupDisposition {
    Completed,
    DeadlineExceeded,
    Failed,
}

/// Observed cleanup result for the process that hosted an execution.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProcessCleanupDisposition {
    /// The still-live process remains manager-owned for another isolated context.
    WarmRetained,
    /// No process close was needed for this release.
    NotRequired,
    Completed,
    DeadlineExceeded,
    Failed,
}

/// Closed cleanup facts for one admitted execution.
///
/// Context and process cleanup remain separate because either resource can fail
/// independently, including both resources in the same release.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionCleanupReceipt {
    admission: BrowserExecutionAdmissionReceipt,
    context: BrowserContextCleanupDisposition,
    process: BrowserProcessCleanupDisposition,
}

impl BrowserExecutionCleanupReceipt {
    pub const fn new(
        admission: BrowserExecutionAdmissionReceipt,
        context: BrowserContextCleanupDisposition,
        process: BrowserProcessCleanupDisposition,
    ) -> Self {
        Self {
            admission,
            context,
            process,
        }
    }

    pub const fn admission(&self) -> &BrowserExecutionAdmissionReceipt {
        &self.admission
    }

    pub const fn context(&self) -> BrowserContextCleanupDisposition {
        self.context
    }

    pub const fn process(&self) -> BrowserProcessCleanupDisposition {
        self.process
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionCleanupReceiptWire {
    admission: BrowserExecutionAdmissionReceipt,
    context: BrowserContextCleanupDisposition,
    process: BrowserProcessCleanupDisposition,
}

impl<'de> Deserialize<'de> for BrowserExecutionCleanupReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let wire = BrowserExecutionCleanupReceiptWire::deserialize(deserializer)?;
        Ok(Self::new(wire.admission, wire.context, wire.process))
    }
}

/// Secret-safe primary reason that an admitted browser execution terminated.
///
/// Cleanup remains an independent pair of observed resource facts on the
/// terminal receipt. A provider failure followed by cleanup failure therefore
/// keeps `ProviderFailure` as its primary reason while preserving both cleanup
/// dispositions separately.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserExecutionTerminalReason {
    Completed,
    CallerCancelled,
    SystemInterrupted,
    DeadlineExceeded,
    ProviderDisconnected,
    ProviderUnavailable,
    ObservationLimitExceeded,
    TabCloseFailed,
    ContextCleanupFailed,
    ContextCleanupDeadlineExceeded,
    ProcessCleanupFailed,
    ProcessCleanupDeadlineExceeded,
    InternalInvariantFailure,
    ProviderFailure,
}

/// Closed terminal fact for one browser execution.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionTerminalReceipt {
    admission: BrowserExecutionAdmissionReceipt,
    cleanup: BrowserExecutionCleanupReceipt,
    reason: BrowserExecutionTerminalReason,
}

impl BrowserExecutionTerminalReceipt {
    pub fn new(
        admission: BrowserExecutionAdmissionReceipt,
        cleanup: BrowserExecutionCleanupReceipt,
        reason: BrowserExecutionTerminalReason,
    ) -> Result<Self, BrowserExecutionReceiptError> {
        if cleanup.admission() != &admission {
            return Err(BrowserExecutionReceiptError::CleanupOutsideAdmission);
        }
        if reason == BrowserExecutionTerminalReason::Completed {
            if cleanup.context() != BrowserContextCleanupDisposition::Completed {
                return Err(BrowserExecutionReceiptError::CompletionWithoutCompletedContextCleanup);
            }
            if matches!(
                cleanup.process(),
                BrowserProcessCleanupDisposition::DeadlineExceeded
                    | BrowserProcessCleanupDisposition::Failed
            ) {
                return Err(BrowserExecutionReceiptError::CompletionWithUnsuccessfulProcessCleanup);
            }
        }
        if (reason == BrowserExecutionTerminalReason::ContextCleanupFailed
            && cleanup.context() != BrowserContextCleanupDisposition::Failed)
            || (reason == BrowserExecutionTerminalReason::ContextCleanupDeadlineExceeded
                && cleanup.context() != BrowserContextCleanupDisposition::DeadlineExceeded)
        {
            return Err(BrowserExecutionReceiptError::ContextCleanupReasonMismatch);
        }
        if (reason == BrowserExecutionTerminalReason::ProcessCleanupFailed
            && cleanup.process() != BrowserProcessCleanupDisposition::Failed)
            || (reason == BrowserExecutionTerminalReason::ProcessCleanupDeadlineExceeded
                && cleanup.process() != BrowserProcessCleanupDisposition::DeadlineExceeded)
        {
            return Err(BrowserExecutionReceiptError::ProcessCleanupReasonMismatch);
        }
        Ok(Self {
            admission,
            cleanup,
            reason,
        })
    }

    pub const fn admission(&self) -> &BrowserExecutionAdmissionReceipt {
        &self.admission
    }

    pub const fn cleanup(&self) -> &BrowserExecutionCleanupReceipt {
        &self.cleanup
    }

    pub const fn reason(&self) -> BrowserExecutionTerminalReason {
        self.reason
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionTerminalReceiptWire {
    admission: BrowserExecutionAdmissionReceipt,
    cleanup: BrowserExecutionCleanupReceipt,
    reason: BrowserExecutionTerminalReason,
}

impl TryFrom<BrowserExecutionTerminalReceiptWire> for BrowserExecutionTerminalReceipt {
    type Error = BrowserExecutionReceiptError;

    fn try_from(value: BrowserExecutionTerminalReceiptWire) -> Result<Self, Self::Error> {
        Self::new(value.admission, value.cleanup, value.reason)
    }
}

impl<'de> Deserialize<'de> for BrowserExecutionTerminalReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserExecutionTerminalReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Lifecycle point represented by a browser execution accounting snapshot.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserExecutionAccountingPhase {
    /// Snapshot while the admission lease is active.
    Admission,
    /// Snapshot after terminal cleanup, when released resources may be absent.
    Terminal,
}

/// Closed, point-in-time manager accounting for an admitted browser execution.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionAccountingReceipt {
    phase: BrowserExecutionAccountingPhase,
    admission: BrowserExecutionAdmissionReceipt,
    limits: BrowserExecutionLimits,
    active_processes: u32,
    active_contexts_total: u32,
    active_contexts_in_process: u32,
    active_tabs_total: u32,
    active_tabs_in_session: u32,
    queued_executions: u32,
    completed_executions_since_recycle: u32,
}

impl BrowserExecutionAccountingReceipt {
    /// Creates an accounting snapshot taken while the admitted lease is active.
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        admission: BrowserExecutionAdmissionReceipt,
        limits: BrowserExecutionLimits,
        active_processes: u32,
        active_contexts_total: u32,
        active_contexts_in_process: u32,
        active_tabs_total: u32,
        active_tabs_in_session: u32,
        queued_executions: u32,
        completed_executions_since_recycle: u32,
    ) -> Result<Self, BrowserExecutionReceiptError> {
        Self::with_phase(
            BrowserExecutionAccountingPhase::Admission,
            admission,
            limits,
            active_processes,
            active_contexts_total,
            active_contexts_in_process,
            active_tabs_total,
            active_tabs_in_session,
            queued_executions,
            completed_executions_since_recycle,
        )
    }

    /// Creates an accounting snapshot taken after release or process cleanup.
    #[allow(clippy::too_many_arguments)]
    pub fn terminal(
        admission: BrowserExecutionAdmissionReceipt,
        limits: BrowserExecutionLimits,
        active_processes: u32,
        active_contexts_total: u32,
        active_contexts_in_process: u32,
        active_tabs_total: u32,
        active_tabs_in_session: u32,
        queued_executions: u32,
        completed_executions_since_recycle: u32,
    ) -> Result<Self, BrowserExecutionReceiptError> {
        Self::with_phase(
            BrowserExecutionAccountingPhase::Terminal,
            admission,
            limits,
            active_processes,
            active_contexts_total,
            active_contexts_in_process,
            active_tabs_total,
            active_tabs_in_session,
            queued_executions,
            completed_executions_since_recycle,
        )
    }

    #[allow(clippy::too_many_arguments)]
    fn with_phase(
        phase: BrowserExecutionAccountingPhase,
        admission: BrowserExecutionAdmissionReceipt,
        limits: BrowserExecutionLimits,
        active_processes: u32,
        active_contexts_total: u32,
        active_contexts_in_process: u32,
        active_tabs_total: u32,
        active_tabs_in_session: u32,
        queued_executions: u32,
        completed_executions_since_recycle: u32,
    ) -> Result<Self, BrowserExecutionReceiptError> {
        validate_accounting(
            phase,
            limits,
            active_processes,
            active_contexts_total,
            active_contexts_in_process,
            active_tabs_total,
            active_tabs_in_session,
            queued_executions,
            completed_executions_since_recycle,
        )?;
        Ok(Self {
            phase,
            admission,
            limits,
            active_processes,
            active_contexts_total,
            active_contexts_in_process,
            active_tabs_total,
            active_tabs_in_session,
            queued_executions,
            completed_executions_since_recycle,
        })
    }

    pub const fn phase(&self) -> BrowserExecutionAccountingPhase {
        self.phase
    }

    pub const fn admission(&self) -> &BrowserExecutionAdmissionReceipt {
        &self.admission
    }

    pub const fn limits(&self) -> BrowserExecutionLimits {
        self.limits
    }

    pub const fn active_processes(&self) -> u32 {
        self.active_processes
    }

    pub const fn active_contexts_total(&self) -> u32 {
        self.active_contexts_total
    }

    pub const fn active_contexts_in_process(&self) -> u32 {
        self.active_contexts_in_process
    }

    pub const fn active_tabs_total(&self) -> u32 {
        self.active_tabs_total
    }

    pub const fn active_tabs_in_session(&self) -> u32 {
        self.active_tabs_in_session
    }

    pub const fn queued_executions(&self) -> u32 {
        self.queued_executions
    }

    pub const fn completed_executions_since_recycle(&self) -> u32 {
        self.completed_executions_since_recycle
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionAccountingReceiptWire {
    phase: BrowserExecutionAccountingPhase,
    admission: BrowserExecutionAdmissionReceipt,
    limits: BrowserExecutionLimits,
    active_processes: u32,
    active_contexts_total: u32,
    active_contexts_in_process: u32,
    active_tabs_total: u32,
    active_tabs_in_session: u32,
    queued_executions: u32,
    completed_executions_since_recycle: u32,
}

impl TryFrom<BrowserExecutionAccountingReceiptWire> for BrowserExecutionAccountingReceipt {
    type Error = BrowserExecutionReceiptError;

    fn try_from(value: BrowserExecutionAccountingReceiptWire) -> Result<Self, Self::Error> {
        Self::with_phase(
            value.phase,
            value.admission,
            value.limits,
            value.active_processes,
            value.active_contexts_total,
            value.active_contexts_in_process,
            value.active_tabs_total,
            value.active_tabs_in_session,
            value.queued_executions,
            value.completed_executions_since_recycle,
        )
    }
}

impl<'de> Deserialize<'de> for BrowserExecutionAccountingReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserExecutionAccountingReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

#[allow(clippy::too_many_arguments)]
fn validate_accounting(
    phase: BrowserExecutionAccountingPhase,
    limits: BrowserExecutionLimits,
    active_processes: u32,
    active_contexts_total: u32,
    active_contexts_in_process: u32,
    active_tabs_total: u32,
    active_tabs_in_session: u32,
    queued_executions: u32,
    completed_executions_since_recycle: u32,
) -> Result<(), BrowserExecutionReceiptError> {
    if phase == BrowserExecutionAccountingPhase::Admission && active_processes == 0 {
        return Err(BrowserExecutionReceiptError::NoActiveProcess);
    }
    if active_processes > limits.processes().get() {
        return Err(BrowserExecutionReceiptError::ProcessLimitExceeded);
    }
    if phase == BrowserExecutionAccountingPhase::Admission && active_contexts_total == 0 {
        return Err(BrowserExecutionReceiptError::NoActiveContext);
    }
    if active_contexts_total > limits.contexts_total().get() {
        return Err(BrowserExecutionReceiptError::ContextTotalLimitExceeded);
    }
    if phase == BrowserExecutionAccountingPhase::Admission && active_contexts_in_process == 0 {
        return Err(BrowserExecutionReceiptError::NoActiveContextInProcess);
    }
    if active_contexts_in_process > limits.contexts_per_process().get() {
        return Err(BrowserExecutionReceiptError::ContextPerProcessLimitExceeded);
    }
    if active_contexts_in_process > active_contexts_total {
        return Err(BrowserExecutionReceiptError::ContextScopeExceedsTotal);
    }
    if active_contexts_total > 0 && active_processes == 0 {
        return Err(BrowserExecutionReceiptError::ContextsWithoutActiveProcess);
    }
    let active_context_capacity = active_processes
        .checked_mul(limits.contexts_per_process().get())
        .ok_or(BrowserExecutionReceiptError::ContextsExceedActiveProcessCapacity)?;
    if active_contexts_total > active_context_capacity {
        return Err(BrowserExecutionReceiptError::ContextsExceedActiveProcessCapacity);
    }
    if phase == BrowserExecutionAccountingPhase::Admission && active_tabs_total == 0 {
        return Err(BrowserExecutionReceiptError::NoActiveTab);
    }
    if active_tabs_total > limits.tabs_total().get() {
        return Err(BrowserExecutionReceiptError::TabTotalLimitExceeded);
    }
    if phase == BrowserExecutionAccountingPhase::Admission && active_tabs_in_session == 0 {
        return Err(BrowserExecutionReceiptError::NoActiveTabInSession);
    }
    if active_tabs_in_session > limits.tabs_per_session().get() {
        return Err(BrowserExecutionReceiptError::TabPerSessionLimitExceeded);
    }
    if active_tabs_in_session > active_tabs_total {
        return Err(BrowserExecutionReceiptError::TabScopeExceedsTotal);
    }
    if active_tabs_total > 0 && active_contexts_total == 0 {
        return Err(BrowserExecutionReceiptError::TabsWithoutActiveContext);
    }
    if active_contexts_total > active_tabs_total {
        return Err(BrowserExecutionReceiptError::ActiveContextsExceedActiveTabs);
    }
    if active_tabs_in_session > 0 && active_contexts_in_process == 0 {
        return Err(BrowserExecutionReceiptError::SessionTabsWithoutActiveContext);
    }
    if phase == BrowserExecutionAccountingPhase::Terminal && active_tabs_in_session != 0 {
        return Err(BrowserExecutionReceiptError::TerminalSessionTabsRemain);
    }
    if queued_executions > limits.queue_depth().get() {
        return Err(BrowserExecutionReceiptError::QueueDepthExceeded);
    }
    if phase == BrowserExecutionAccountingPhase::Admission
        && completed_executions_since_recycle > limits.recycle_threshold().get()
    {
        return Err(BrowserExecutionReceiptError::RecycleThresholdExceeded);
    }
    if phase == BrowserExecutionAccountingPhase::Terminal && completed_executions_since_recycle == 0
    {
        return Err(BrowserExecutionReceiptError::TerminalExecutionNotCounted);
    }
    Ok(())
}

/// Validated durable receipt for a complete provider-neutral browser execution.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserExecutionReceipt {
    capture_id: CaptureId,
    terminal: BrowserExecutionTerminalReceipt,
    accounting: BrowserExecutionAccountingReceipt,
}

impl BrowserExecutionReceipt {
    /// Creates a receipt permanently bound to one exact capture occurrence.
    pub fn new(
        capture_id: CaptureId,
        terminal: BrowserExecutionTerminalReceipt,
        accounting: BrowserExecutionAccountingReceipt,
    ) -> Result<Self, BrowserExecutionReceiptError> {
        if terminal.admission() != accounting.admission() {
            return Err(BrowserExecutionReceiptError::AccountingOutsideTerminal);
        }
        if accounting.phase() != BrowserExecutionAccountingPhase::Terminal {
            return Err(BrowserExecutionReceiptError::ReceiptWithoutTerminalAccounting);
        }
        validate_terminal_cleanup_accounting(terminal.cleanup(), &accounting)?;
        Ok(Self {
            capture_id,
            terminal,
            accounting,
        })
    }

    /// Returns the capture occurrence, and therefore activity identity, that owned this lease.
    pub const fn capture_id(&self) -> CaptureId {
        self.capture_id
    }

    pub const fn terminal(&self) -> &BrowserExecutionTerminalReceipt {
        &self.terminal
    }

    pub const fn accounting(&self) -> &BrowserExecutionAccountingReceipt {
        &self.accounting
    }
}

fn validate_terminal_cleanup_accounting(
    cleanup: &BrowserExecutionCleanupReceipt,
    accounting: &BrowserExecutionAccountingReceipt,
) -> Result<(), BrowserExecutionReceiptError> {
    if cleanup.context() != BrowserContextCleanupDisposition::Completed
        && cleanup.process() == BrowserProcessCleanupDisposition::WarmRetained
    {
        return Err(BrowserExecutionReceiptError::UnsuccessfulContextCleanupWarmRetained);
    }
    match cleanup.process() {
        BrowserProcessCleanupDisposition::WarmRetained => {
            if accounting.active_processes() == 0 {
                return Err(BrowserExecutionReceiptError::CleanupRequiresActiveProcess);
            }
        }
        BrowserProcessCleanupDisposition::Completed => {
            if accounting.active_contexts_in_process() != 0 {
                return Err(BrowserExecutionReceiptError::ClosedProcessHasActiveContexts);
            }
        }
        BrowserProcessCleanupDisposition::DeadlineExceeded
        | BrowserProcessCleanupDisposition::Failed => {
            if accounting.active_processes() == 0 {
                return Err(BrowserExecutionReceiptError::CleanupRequiresActiveProcess);
            }
            if accounting.active_contexts_in_process() != 0 {
                return Err(BrowserExecutionReceiptError::ClosedProcessHasActiveContexts);
            }
        }
        BrowserProcessCleanupDisposition::NotRequired => {}
    }
    Ok(())
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserExecutionReceiptWire {
    capture_id: CaptureId,
    terminal: BrowserExecutionTerminalReceipt,
    accounting: BrowserExecutionAccountingReceipt,
}

impl TryFrom<BrowserExecutionReceiptWire> for BrowserExecutionReceipt {
    type Error = BrowserExecutionReceiptError;

    fn try_from(value: BrowserExecutionReceiptWire) -> Result<Self, Self::Error> {
        Self::new(value.capture_id, value.terminal, value.accounting)
    }
}

impl<'de> Deserialize<'de> for BrowserExecutionReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserExecutionReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
