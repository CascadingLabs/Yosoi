//! Checked completion for streaming and aggregate-producing acquisition paths.

use chrono::{DateTime, Utc};
use thiserror::Error;

use super::BoundedAcquisitionLifecycle;
use crate::{
    CaptureDuration, CaptureObservation, CaptureObservationError, CaptureTermination,
    ObservationWindow, ObservationWindowError, TerminalObservationState,
};

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum AcquisitionObservationError {
    #[error("publication request belongs to a different acquisition lifecycle")]
    CaptureIdentityMismatch,
    #[error("terminal observation precedes already admitted acquisition evidence")]
    AccountingRegression,
    #[error("terminal observation does not exactly match the stopped acquisition lifecycle")]
    StoppedAccountingMismatch,
    #[error("terminal reason contradicts the stopped acquisition lifecycle")]
    TerminationMismatch,
    #[error(transparent)]
    Window(#[from] ObservationWindowError),
    #[error(transparent)]
    Observation(#[from] CaptureObservationError),
}

impl BoundedAcquisitionLifecycle {
    /// Validates and adopts authoritative aggregate collector facts at the
    /// concrete provider boundary, before final publication.
    pub fn adopt_accounting(
        &mut self,
        terminal: &TerminalObservationState,
        termination: &CaptureTermination,
    ) -> Result<(), AcquisitionObservationError> {
        self.clone().finish_from_accounting(
            self.started_at,
            terminal.clone(),
            termination.clone(),
        )?;
        self.observed_through = terminal.observed_through();
        self.admitted_events = terminal.events().admitted().get();
        self.retained_events = terminal.events().retained().get();
        self.admitted_bytes = terminal.bytes().admitted().get();
        self.retained_bytes = terminal.bytes().retained().get();
        self.stop = Some(termination.clone());
        Ok(())
    }

    /// Adopt real collector totals without replaying synthetic admission events.
    ///
    /// Both transports use the same policy, clock, conservation and terminal checks.
    /// Unknown loss stays unknown; provider accounting is never inferred from payload size.
    pub fn finish_from_accounting(
        self,
        finished_at: DateTime<Utc>,
        terminal: TerminalObservationState,
        termination: CaptureTermination,
    ) -> Result<CaptureObservation, AcquisitionObservationError> {
        if let Some(stopped) = &self.stop {
            if stopped != &termination {
                return Err(AcquisitionObservationError::TerminationMismatch);
            }
            if terminal.observed_through() != self.observed_through
                || terminal.events().admitted().get() != self.admitted_events
                || terminal.events().retained().get() != self.retained_events
                || terminal.bytes().admitted().get() != self.admitted_bytes
                || terminal.bytes().retained().get() != self.retained_bytes
            {
                return Err(AcquisitionObservationError::StoppedAccountingMismatch);
            }
        } else if terminal.observed_through() < self.observed_through
            || terminal.events().admitted().get() < self.admitted_events
            || terminal.events().retained().get() < self.retained_events
            || terminal.bytes().admitted().get() < self.admitted_bytes
            || terminal.bytes().retained().get() < self.retained_bytes
        {
            return Err(AcquisitionObservationError::AccountingRegression);
        }
        let window = ObservationWindow::new(
            self.started_at,
            finished_at,
            CaptureDuration::from_microseconds(terminal.observed_through().as_microseconds()),
        )?;
        Ok(CaptureObservation::new(
            self.observation,
            window,
            terminal,
            termination,
        )?)
    }
}
