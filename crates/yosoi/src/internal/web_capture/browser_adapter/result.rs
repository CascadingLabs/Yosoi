//! Browser attempt state carrying its shared acquisition lifecycle to publication.

use crate::internal::web_capture as yosoi_web_capture;

use super::{
    BrowserAdapterFacts, BrowserAdapterOutputError, BrowserAdapterTerminal, BrowserProviderStop,
    BrowserTerminalKind, CleanupState,
};
use crate::internal::web_capture::browser_finalization::adopt_browser_accounting;

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserAdapterResultState {
    ReadyForFinalization,
    Stopped,
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserAdapterResult {
    state: BrowserAdapterResultState,
    terminal: BrowserAdapterTerminal,
    facts: BrowserAdapterFacts,
    lifecycle: Option<yosoi_web_capture::BoundedAcquisitionLifecycle>,
    execution: Option<yosoi_web_capture::BrowserExecutionReceipt>,
}

impl BrowserAdapterResult {
    pub fn ready_for_finalization(
        terminal: BrowserAdapterTerminal,
        facts: BrowserAdapterFacts,
    ) -> Result<Self, BrowserAdapterOutputError> {
        if terminal.at() != facts.observed_through() {
            return Err(BrowserAdapterOutputError::TerminalOffsetMismatch);
        }
        let eligible = matches!(
            (terminal.kind(), facts.spec().observation().settlement()),
            (
                BrowserTerminalKind::QuietSettled,
                yosoi_web_capture::SettlementPolicy::QuietPeriod(_)
            ) | (
                BrowserTerminalKind::ControllerCompleted,
                yosoi_web_capture::SettlementPolicy::Disabled
            )
        );
        if (matches!(terminal.kind(), BrowserTerminalKind::QuietSettled)
            && facts.settlement().is_none())
            || !eligible
            || !facts.source_representation_is_finalizable()
            || !facts.navigation_completed()
            || facts.cleanup() != CleanupState::Complete
        {
            return Err(BrowserAdapterOutputError::InvalidReadyState);
        }
        Ok(Self {
            state: BrowserAdapterResultState::ReadyForFinalization,
            terminal,
            facts,
            lifecycle: None,
            execution: None,
        })
    }

    pub fn stopped(
        terminal: BrowserAdapterTerminal,
        facts: BrowserAdapterFacts,
    ) -> Result<Self, BrowserAdapterOutputError> {
        if terminal.at() != facts.observed_through() {
            return Err(BrowserAdapterOutputError::TerminalOffsetMismatch);
        }
        if matches!(
            terminal.kind(),
            BrowserTerminalKind::QuietSettled | BrowserTerminalKind::ControllerCompleted
        ) {
            return Err(BrowserAdapterOutputError::InvalidStoppedState);
        }
        let cleanup_terminal = matches!(
            terminal.kind(),
            BrowserTerminalKind::ProviderStopped {
                reason: BrowserProviderStop::CleanupFailure
            }
        );
        if cleanup_terminal && facts.cleanup() != CleanupState::Failed {
            return Err(BrowserAdapterOutputError::InvalidStoppedState);
        }
        Ok(Self {
            state: BrowserAdapterResultState::Stopped,
            terminal,
            facts,
            lifecycle: None,
            execution: None,
        })
    }

    /// Carries the one live shared lifecycle created at browser-attempt start.
    pub fn with_lifecycle(
        mut self,
        mut lifecycle: yosoi_web_capture::BoundedAcquisitionLifecycle,
    ) -> Result<Self, BrowserAdapterOutputError> {
        if lifecycle.capture_id() != self.facts.spec().request().capture_id()
            || lifecycle.observation() != self.facts.spec().observation()
        {
            return Err(BrowserAdapterOutputError::LifecycleMismatch);
        }
        adopt_browser_accounting(&mut lifecycle, &self.terminal, &self.facts)
            .map_err(|_| BrowserAdapterOutputError::LifecycleMismatch)?;
        if lifecycle.observed_through() != self.terminal.at()
            || lifecycle.admitted_events() != self.facts.events().admitted().get()
            || lifecycle.retained_events() != self.facts.events().retained().get()
            || lifecycle.admitted_bytes() != self.facts.bytes().observed()
            || lifecycle.retained_bytes() != self.facts.bytes().retained()
            || lifecycle.termination().is_none()
        {
            return Err(BrowserAdapterOutputError::LifecycleMismatch);
        }
        self.lifecycle = Some(lifecycle);
        Ok(self)
    }

    /// Attaches the receipt only when it belongs to this exact capture occurrence.
    pub fn with_execution(
        mut self,
        execution: yosoi_web_capture::BrowserExecutionReceipt,
    ) -> Result<Self, BrowserAdapterOutputError> {
        if execution.capture_id() != self.facts.spec().request().capture_id() {
            return Err(BrowserAdapterOutputError::ExecutionCaptureMismatch);
        }
        self.execution = Some(execution);
        Ok(self)
    }

    pub const fn lifecycle(&self) -> Option<&yosoi_web_capture::BoundedAcquisitionLifecycle> {
        self.lifecycle.as_ref()
    }
    pub const fn execution(&self) -> Option<&yosoi_web_capture::BrowserExecutionReceipt> {
        self.execution.as_ref()
    }
    pub const fn terminal(&self) -> &BrowserAdapterTerminal {
        &self.terminal
    }
    pub const fn facts(&self) -> &BrowserAdapterFacts {
        &self.facts
    }
    pub const fn is_ready(&self) -> bool {
        matches!(self.state, BrowserAdapterResultState::ReadyForFinalization)
    }
    pub const fn state(&self) -> BrowserAdapterResultState {
        self.state
    }
    pub fn into_parts(
        self,
    ) -> (
        BrowserAdapterResultState,
        BrowserAdapterTerminal,
        BrowserAdapterFacts,
    ) {
        (self.state, self.terminal, self.facts)
    }
    pub fn into_parts_with_execution(
        self,
    ) -> (
        BrowserAdapterResultState,
        BrowserAdapterTerminal,
        BrowserAdapterFacts,
        Option<yosoi_web_capture::BrowserExecutionReceipt>,
    ) {
        (self.state, self.terminal, self.facts, self.execution)
    }
    pub(in crate::internal::web_capture) fn into_finalization_parts(
        self,
    ) -> (
        BrowserAdapterResultState,
        BrowserAdapterTerminal,
        BrowserAdapterFacts,
        Option<yosoi_web_capture::BoundedAcquisitionLifecycle>,
        Option<yosoi_web_capture::BrowserExecutionReceipt>,
    ) {
        (
            self.state,
            self.terminal,
            self.facts,
            self.lifecycle,
            self.execution,
        )
    }
}
