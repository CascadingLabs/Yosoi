use std::num::NonZeroUsize;

use crate::internal::browser as provider;
use tokio::{
    sync::{mpsc, oneshot},
    time::Instant,
};

use crate::internal::web_capture as yosoi;

use super::{handle::ReadinessSignal, worker::NavigationJob};

pub(super) struct ProgressEmitter {
    request: yosoi::BrowserNavigationRequest,
    readiness: yosoi::BrowserNavigationReadinessCheckpoint,
    sender: mpsc::Sender<yosoi::BrowserNavigationProgressReceipt>,
    readiness_sender: Option<oneshot::Sender<ReadinessSignal>>,
    next_sequence: u64,
    admitted: u64,
    retained: u64,
    dropped: u64,
    accounting_unknown: bool,
    reached: Option<yosoi::BrowserNavigationProgressKind>,
}

impl ProgressEmitter {
    pub(super) const fn new(
        request: yosoi::BrowserNavigationRequest,
        readiness: yosoi::BrowserNavigationReadinessCheckpoint,
        sender: mpsc::Sender<yosoi::BrowserNavigationProgressReceipt>,
        readiness_sender: Option<oneshot::Sender<ReadinessSignal>>,
    ) -> Self {
        Self {
            request,
            readiness,
            sender,
            readiness_sender,
            next_sequence: 1,
            admitted: 0,
            retained: 0,
            dropped: 0,
            accounting_unknown: false,
            reached: None,
        }
    }

    pub(super) fn emit(
        &mut self,
        kind: yosoi::BrowserNavigationProgressKind,
        offset: yosoi::CaptureDuration,
    ) {
        let sequence = self.next_sequence;
        let Some(next_sequence) = sequence.checked_add(1) else {
            self.accounting_unknown = true;
            return;
        };
        self.next_sequence = next_sequence;
        match self.admitted.checked_add(1) {
            Some(value) => self.admitted = value,
            None => self.accounting_unknown = true,
        }
        let receipt = yosoi::BrowserNavigationProgressReceipt::new(
            &self.request,
            kind,
            yosoi::EventCount::new(sequence),
            yosoi::CaptureOffset::from_microseconds(offset.as_microseconds()),
        );
        match self.sender.try_send(receipt) {
            Ok(()) => match self.retained.checked_add(1) {
                Some(value) => self.retained = value,
                None => self.accounting_unknown = true,
            },
            Err(_) => match self.dropped.checked_add(1) {
                Some(value) => self.dropped = value,
                None => self.accounting_unknown = true,
            },
        }
        if self.reached.is_none() && satisfies(self.readiness, kind) {
            self.reached = Some(kind);
            if let Some(sender) = self.readiness_sender.take() {
                let _ = sender.send(ReadinessSignal::Reached(receipt));
            }
        }
    }

    pub(super) const fn accounting(&self) -> yosoi::BrowserNavigationProgressAccounting {
        if self.accounting_unknown {
            let accounting = yosoi::BrowserNavigationProgressAccounting::with_unknown_loss(
                yosoi::EventCount::new(self.admitted),
                yosoi::EventCount::new(self.retained),
            );
            let Ok(accounting) = accounting else {
                return yosoi::BrowserNavigationProgressAccounting::empty();
            };
            return accounting;
        }
        let accounting = yosoi::BrowserNavigationProgressAccounting::new(
            yosoi::EventCount::new(self.admitted),
            yosoi::EventCount::new(self.retained),
            yosoi::LossExtent::Known(self.dropped),
        );
        let Ok(accounting) = accounting else {
            let fallback = yosoi::BrowserNavigationProgressAccounting::with_unknown_loss(
                yosoi::EventCount::new(self.admitted),
                yosoi::EventCount::new(self.retained),
            );
            let Ok(fallback) = fallback else {
                return yosoi::BrowserNavigationProgressAccounting::empty();
            };
            return fallback;
        };
        accounting
    }

    pub(super) fn finish_readiness(&mut self, outcome: yosoi::BrowserNavigationOutcome) {
        if let Some(sender) = self.readiness_sender.take() {
            let _ = sender.send(ReadinessSignal::Ended(outcome));
        }
    }

    pub(super) const fn reached(&self) -> Option<yosoi::BrowserNavigationProgressKind> {
        self.reached
    }
}

pub(super) fn finish_before_start(
    mut job: NavigationJob,
    submitted: Instant,
    outcome: yosoi::BrowserNavigationOutcome,
) {
    send_empty_terminal(
        &mut job,
        outcome,
        elapsed(submitted),
        yosoi::CaptureDuration::default(),
        true,
    );
}

pub(super) fn finish_started(
    mut job: NavigationJob,
    queue_wait: yosoi::CaptureDuration,
    started: Instant,
    outcome: yosoi::BrowserNavigationOutcome,
    cleanup_complete: bool,
) {
    send_empty_terminal(
        &mut job,
        outcome,
        queue_wait,
        elapsed(started),
        cleanup_complete,
    );
}

fn send_empty_terminal(
    job: &mut NavigationJob,
    outcome: yosoi::BrowserNavigationOutcome,
    queue_wait: yosoi::CaptureDuration,
    execution: yosoi::CaptureDuration,
    cleanup_complete: bool,
) {
    if let Some(sender) = job.readiness_sender.take() {
        let _ = sender.send(ReadinessSignal::Ended(outcome));
    }
    let receipt = yosoi::BrowserNavigationTerminalReceipt::new(
        &job.request,
        outcome,
        None,
        yosoi::BrowserNavigationProgressAccounting::empty(),
        yosoi::LossExtent::Known(0),
        yosoi::LossExtent::Known(0),
        queue_wait,
        execution,
        cleanup_complete,
        false,
    );
    if let Some(sender) = job.terminal_sender.take() {
        let _ = sender.send(receipt);
    }
}

pub(super) fn elapsed(started: Instant) -> yosoi::CaptureDuration {
    yosoi::CaptureDuration::from_microseconds(
        u64::try_from(started.elapsed().as_micros()).unwrap_or(u64::MAX),
    )
}

pub(super) fn nonzero_usize(value: u32) -> Option<NonZeroUsize> {
    usize::try_from(value).ok().and_then(NonZeroUsize::new)
}

pub(super) const fn map_provider_progress(
    kind: provider::NavigationProgressKind,
) -> yosoi::BrowserNavigationProgressKind {
    match kind {
        provider::NavigationProgressKind::CommandAccepted => {
            yosoi::BrowserNavigationProgressKind::CommandAccepted
        }
        provider::NavigationProgressKind::DocumentCommitted => {
            yosoi::BrowserNavigationProgressKind::DocumentCommitted
        }
        provider::NavigationProgressKind::SameDocumentNavigation => {
            yosoi::BrowserNavigationProgressKind::SameDocumentNavigation
        }
        provider::NavigationProgressKind::DomContentLoaded => {
            yosoi::BrowserNavigationProgressKind::DomContentLoaded
        }
        provider::NavigationProgressKind::Load => yosoi::BrowserNavigationProgressKind::Load,
        provider::NavigationProgressKind::FrameStopped => {
            yosoi::BrowserNavigationProgressKind::FrameStopped
        }
    }
}

fn satisfies(
    readiness: yosoi::BrowserNavigationReadinessCheckpoint,
    progress: yosoi::BrowserNavigationProgressKind,
) -> bool {
    use crate::internal::web_capture::BrowserNavigationProgressKind as Progress;
    use crate::internal::web_capture::BrowserNavigationReadinessCheckpoint as Readiness;
    match readiness {
        Readiness::CommandAccepted => progress == Progress::CommandAccepted,
        Readiness::DocumentCommitted => matches!(
            progress,
            Progress::DocumentCommitted | Progress::SameDocumentNavigation
        ),
        Readiness::DomContentLoaded => matches!(
            progress,
            Progress::DomContentLoaded | Progress::SameDocumentNavigation
        ),
        Readiness::Load => matches!(progress, Progress::Load | Progress::SameDocumentNavigation),
        Readiness::ControllerCompleted => progress == Progress::ControllerCompleted,
        Readiness::NetworkIdle => false,
    }
}

pub(super) const fn map_termination(
    termination: provider::NavigationTermination,
) -> yosoi::BrowserNavigationOutcome {
    match termination {
        provider::NavigationTermination::Completed => yosoi::BrowserNavigationOutcome::Completed,
        provider::NavigationTermination::Cancelled => {
            yosoi::BrowserNavigationOutcome::CancelledDuringNavigation
        }
        provider::NavigationTermination::DeadlineReached => {
            yosoi::BrowserNavigationOutcome::DeadlineReached
        }
        provider::NavigationTermination::PageClosed => yosoi::BrowserNavigationOutcome::TabClosed,
        provider::NavigationTermination::BrowserClosed => {
            yosoi::BrowserNavigationOutcome::BrowserClosed
        }
        provider::NavigationTermination::Failed { reason } => {
            yosoi::BrowserNavigationOutcome::Failed {
                reason: map_failure(reason),
            }
        }
    }
}

const fn map_failure(
    failure: provider::NavigationFailureReason,
) -> yosoi::BrowserNavigationFailure {
    match failure {
        provider::NavigationFailureReason::CommandRejected => {
            yosoi::BrowserNavigationFailure::CommandRejected
        }
        provider::NavigationFailureReason::BecameDownload => {
            yosoi::BrowserNavigationFailure::DownloadStarted
        }
        provider::NavigationFailureReason::DocumentIdentityMismatch => {
            yosoi::BrowserNavigationFailure::DocumentIdentityMismatch
        }
        provider::NavigationFailureReason::DocumentIdentityUnavailable => {
            yosoi::BrowserNavigationFailure::DocumentIdentityUnavailable
        }
        provider::NavigationFailureReason::EventStreamClosed => {
            yosoi::BrowserNavigationFailure::EventStreamClosed
        }
        provider::NavigationFailureReason::ProviderFailure => {
            yosoi::BrowserNavigationFailure::ProviderUnavailable
        }
    }
}

pub(super) const fn map_loss(measured: provider::MeasuredCount) -> yosoi::LossExtent {
    match measured {
        provider::MeasuredCount::Known { value } => yosoi::LossExtent::Known(value),
        provider::MeasuredCount::Unavailable { .. } => yosoi::LossExtent::Unknown,
    }
}

pub(super) const fn provider_failure() -> yosoi::BrowserNavigationOutcome {
    yosoi::BrowserNavigationOutcome::Failed {
        reason: yosoi::BrowserNavigationFailure::ProviderUnavailable,
    }
}

pub(super) const fn internal_failure() -> yosoi::BrowserNavigationOutcome {
    yosoi::BrowserNavigationOutcome::Failed {
        reason: yosoi::BrowserNavigationFailure::InternalInvariant,
    }
}

pub(super) const fn leaves_page_uncertain(outcome: yosoi::BrowserNavigationOutcome) -> bool {
    matches!(
        outcome,
        yosoi::BrowserNavigationOutcome::Failed {
            reason: yosoi::BrowserNavigationFailure::DocumentIdentityMismatch
                | yosoi::BrowserNavigationFailure::DocumentIdentityUnavailable
                | yosoi::BrowserNavigationFailure::EventStreamClosed
                | yosoi::BrowserNavigationFailure::ProviderUnavailable
                | yosoi::BrowserNavigationFailure::InternalInvariant
        }
    )
}
