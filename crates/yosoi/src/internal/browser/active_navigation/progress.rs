use std::num::NonZeroU64;

use tokio::{sync::mpsc, time::Instant};

use crate::internal::browser::{MeasuredCount, MeasurementUnavailableReason};

use super::{NavigationProgress, NavigationProgressAccounting, NavigationProgressKind};

pub(super) struct ProgressEmitter {
    sender: mpsc::Sender<NavigationProgress>,
    started: Instant,
    next_sequence: u64,
    admitted: u64,
    retained: u64,
    dropped: u64,
    provider_dropped: u64,
    accounting_unknown: bool,
}

impl ProgressEmitter {
    pub(super) const fn new(sender: mpsc::Sender<NavigationProgress>, started: Instant) -> Self {
        Self {
            sender,
            started,
            next_sequence: 1,
            admitted: 0,
            retained: 0,
            dropped: 0,
            provider_dropped: 0,
            accounting_unknown: false,
        }
    }

    pub(super) fn emit(&mut self, kind: NavigationProgressKind) {
        let sequence = self.next_sequence;
        let Some(next_sequence) = sequence.checked_add(1) else {
            self.accounting_unknown = true;
            return;
        };
        self.next_sequence = next_sequence;
        if let Some(value) = self.admitted.checked_add(1) {
            self.admitted = value;
        } else {
            self.accounting_unknown = true;
        }
        let offset_micros = u64::try_from(self.started.elapsed().as_micros()).unwrap_or(u64::MAX);
        match self.sender.try_send(NavigationProgress {
            sequence,
            offset_micros,
            kind,
        }) {
            Ok(()) => {
                if let Some(value) = self.retained.checked_add(1) {
                    self.retained = value;
                } else {
                    self.accounting_unknown = true;
                }
            }
            Err(mpsc::error::TrySendError::Full(_) | mpsc::error::TrySendError::Closed(_)) => {
                self.record_drop(1);
            }
        }
    }

    pub(super) const fn provider_lagged(&mut self, dropped: NonZeroU64) {
        if let Some(value) = self.provider_dropped.checked_add(dropped.get()) {
            self.provider_dropped = value;
        } else {
            self.accounting_unknown = true;
        }
    }

    pub(super) const fn record_drop(&mut self, count: u64) {
        if let Some(value) = self.dropped.checked_add(count) {
            self.dropped = value;
        } else {
            self.accounting_unknown = true;
        }
    }

    pub(super) fn report(&self) -> NavigationProgressAccounting {
        let known = |value| MeasuredCount::Known { value };
        NavigationProgressAccounting {
            admitted: known(self.admitted),
            retained: known(self.retained),
            dropped: if self.accounting_unknown {
                MeasuredCount::Unavailable {
                    reason: MeasurementUnavailableReason::ProviderDidNotReport,
                }
            } else {
                known(self.dropped)
            },
        }
    }

    pub(super) const fn provider_report(&self) -> MeasuredCount {
        if self.accounting_unknown {
            MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::ProviderDidNotReport,
            }
        } else {
            MeasuredCount::Known {
                value: self.provider_dropped,
            }
        }
    }
}
