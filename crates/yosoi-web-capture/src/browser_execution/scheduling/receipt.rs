use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;
use yosoi_types::{CaptureDuration, CaptureOffset, EventCount, LossExtent};

use super::super::{BrowserNavigationRequestId, BrowserNavigationSchedulerId, BrowserTabLeaseId};
use super::{
    BrowserNavigationProgressKind, BrowserNavigationReadinessCheckpoint, BrowserNavigationRequest,
};

/// One secret-safe readiness progress receipt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserNavigationProgressReceipt {
    scheduler: BrowserNavigationSchedulerId,
    request: BrowserNavigationRequestId,
    tab: BrowserTabLeaseId,
    kind: BrowserNavigationProgressKind,
    sequence: EventCount,
    offset: CaptureOffset,
}

impl BrowserNavigationProgressReceipt {
    pub const fn new(
        request: &BrowserNavigationRequest,
        kind: BrowserNavigationProgressKind,
        sequence: EventCount,
        offset: CaptureOffset,
    ) -> Self {
        Self {
            scheduler: request.scheduler(),
            request: request.request(),
            tab: request.tab().tab(),
            kind,
            sequence,
            offset,
        }
    }

    pub const fn scheduler(self) -> BrowserNavigationSchedulerId {
        self.scheduler
    }

    pub const fn request(self) -> BrowserNavigationRequestId {
        self.request
    }

    pub const fn tab(self) -> BrowserTabLeaseId {
        self.tab
    }

    pub const fn kind(self) -> BrowserNavigationProgressKind {
        self.kind
    }

    pub const fn sequence(self) -> EventCount {
        self.sequence
    }

    pub const fn offset(self) -> CaptureOffset {
        self.offset
    }
}

/// Accounting for bounded navigation progress delivery.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserNavigationProgressAccounting {
    admitted: EventCount,
    retained: EventCount,
    dropped: LossExtent,
}

impl BrowserNavigationProgressAccounting {
    pub const fn empty() -> Self {
        Self {
            admitted: EventCount::new(0),
            retained: EventCount::new(0),
            dropped: LossExtent::Known(0),
        }
    }

    pub const fn with_unknown_loss(
        admitted: EventCount,
        retained: EventCount,
    ) -> Result<Self, BrowserNavigationSchedulingError> {
        Self::new(admitted, retained, LossExtent::Unknown)
    }

    pub const fn new(
        admitted: EventCount,
        retained: EventCount,
        dropped: LossExtent,
    ) -> Result<Self, BrowserNavigationSchedulingError> {
        if retained.get() > admitted.get() {
            return Err(BrowserNavigationSchedulingError::ProgressRetainedExceedsAdmitted);
        }
        if let LossExtent::Known(dropped) = dropped {
            let Some(accounted) = retained.get().checked_add(dropped) else {
                return Err(BrowserNavigationSchedulingError::ProgressAccountingOverflow);
            };
            if accounted != admitted.get() {
                return Err(BrowserNavigationSchedulingError::ProgressAccountingMismatch);
            }
        }
        Ok(Self {
            admitted,
            retained,
            dropped,
        })
    }

    pub const fn admitted(self) -> EventCount {
        self.admitted
    }

    pub const fn retained(self) -> EventCount {
        self.retained
    }

    pub const fn dropped(self) -> LossExtent {
        self.dropped
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserNavigationProgressAccountingWire {
    admitted: EventCount,
    retained: EventCount,
    dropped: LossExtent,
}

impl TryFrom<BrowserNavigationProgressAccountingWire> for BrowserNavigationProgressAccounting {
    type Error = BrowserNavigationSchedulingError;

    fn try_from(value: BrowserNavigationProgressAccountingWire) -> Result<Self, Self::Error> {
        Self::new(value.admitted, value.retained, value.dropped)
    }
}

impl<'de> Deserialize<'de> for BrowserNavigationProgressAccounting {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserNavigationProgressAccountingWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

/// Closed terminal result for one scheduled navigation.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserNavigationOutcome {
    Completed,
    CancelledBeforeAdmission,
    CancelledDuringNavigation,
    QueueWaitDeadline,
    DeadlineReached,
    TabClosed,
    ManagerShutdown,
    BrowserClosed,
    Failed { reason: BrowserNavigationFailure },
}

/// Secret-safe category for a navigation that could not complete.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserNavigationFailure {
    CommandRejected,
    DownloadStarted,
    DocumentIdentityMismatch,
    DocumentIdentityUnavailable,
    EventStreamClosed,
    ProviderUnavailable,
    InternalInvariant,
}

/// Exactly-once terminal receipt for one scheduled navigation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserNavigationTerminalReceipt {
    scheduler: BrowserNavigationSchedulerId,
    request: BrowserNavigationRequestId,
    tab: BrowserTabLeaseId,
    outcome: BrowserNavigationOutcome,
    requested_readiness: BrowserNavigationReadinessCheckpoint,
    reached_readiness: Option<BrowserNavigationProgressKind>,
    progress: BrowserNavigationProgressAccounting,
    engine_progress_dropped: LossExtent,
    provider_events_dropped: LossExtent,
    queue_wait: CaptureDuration,
    execution: CaptureDuration,
    cleanup_complete: bool,
    same_document: bool,
}

impl BrowserNavigationTerminalReceipt {
    #[allow(
        clippy::too_many_arguments,
        reason = "typed terminal receipt keeps each accounting fact explicit"
    )]
    pub const fn new(
        request: &BrowserNavigationRequest,
        outcome: BrowserNavigationOutcome,
        reached_readiness: Option<BrowserNavigationProgressKind>,
        progress: BrowserNavigationProgressAccounting,
        engine_progress_dropped: LossExtent,
        provider_events_dropped: LossExtent,
        queue_wait: CaptureDuration,
        execution: CaptureDuration,
        cleanup_complete: bool,
        same_document: bool,
    ) -> Self {
        Self {
            scheduler: request.scheduler(),
            request: request.request(),
            tab: request.tab().tab(),
            outcome,
            requested_readiness: request.readiness(),
            reached_readiness,
            progress,
            engine_progress_dropped,
            provider_events_dropped,
            queue_wait,
            execution,
            cleanup_complete,
            same_document,
        }
    }

    pub const fn scheduler(self) -> BrowserNavigationSchedulerId {
        self.scheduler
    }

    pub const fn request(self) -> BrowserNavigationRequestId {
        self.request
    }

    pub const fn tab(self) -> BrowserTabLeaseId {
        self.tab
    }

    pub const fn outcome(self) -> BrowserNavigationOutcome {
        self.outcome
    }

    pub const fn requested_readiness(self) -> BrowserNavigationReadinessCheckpoint {
        self.requested_readiness
    }

    pub const fn reached_readiness(self) -> Option<BrowserNavigationProgressKind> {
        self.reached_readiness
    }

    pub const fn progress(self) -> BrowserNavigationProgressAccounting {
        self.progress
    }

    pub const fn engine_progress_dropped(self) -> LossExtent {
        self.engine_progress_dropped
    }

    pub const fn provider_events_dropped(self) -> LossExtent {
        self.provider_events_dropped
    }

    pub const fn queue_wait(self) -> CaptureDuration {
        self.queue_wait
    }

    pub const fn execution(self) -> CaptureDuration {
        self.execution
    }

    pub const fn cleanup_complete(self) -> bool {
        self.cleanup_complete
    }

    pub const fn same_document(self) -> bool {
        self.same_document
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserNavigationTerminalReceiptWire {
    scheduler: BrowserNavigationSchedulerId,
    request: BrowserNavigationRequestId,
    tab: BrowserTabLeaseId,
    outcome: BrowserNavigationOutcome,
    requested_readiness: BrowserNavigationReadinessCheckpoint,
    reached_readiness: Option<BrowserNavigationProgressKind>,
    progress: BrowserNavigationProgressAccounting,
    engine_progress_dropped: LossExtent,
    provider_events_dropped: LossExtent,
    queue_wait: CaptureDuration,
    execution: CaptureDuration,
    cleanup_complete: bool,
    same_document: bool,
}

impl TryFrom<BrowserNavigationTerminalReceiptWire> for BrowserNavigationTerminalReceipt {
    type Error = BrowserNavigationSchedulingError;

    fn try_from(value: BrowserNavigationTerminalReceiptWire) -> Result<Self, Self::Error> {
        if value
            .reached_readiness
            .is_some_and(|reached| !readiness_matches(value.requested_readiness, reached))
        {
            return Err(BrowserNavigationSchedulingError::ReadinessMismatch);
        }
        if value.same_document && value.outcome != BrowserNavigationOutcome::Completed {
            return Err(BrowserNavigationSchedulingError::SameDocumentWithoutCompletion);
        }
        Ok(Self {
            scheduler: value.scheduler,
            request: value.request,
            tab: value.tab,
            outcome: value.outcome,
            requested_readiness: value.requested_readiness,
            reached_readiness: value.reached_readiness,
            progress: value.progress,
            engine_progress_dropped: value.engine_progress_dropped,
            provider_events_dropped: value.provider_events_dropped,
            queue_wait: value.queue_wait,
            execution: value.execution,
            cleanup_complete: value.cleanup_complete,
            same_document: value.same_document,
        })
    }
}

impl<'de> Deserialize<'de> for BrowserNavigationTerminalReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserNavigationTerminalReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

fn readiness_matches(
    requested: BrowserNavigationReadinessCheckpoint,
    reached: BrowserNavigationProgressKind,
) -> bool {
    use BrowserNavigationProgressKind as Progress;
    use BrowserNavigationReadinessCheckpoint as Readiness;
    match requested {
        Readiness::CommandAccepted => reached == Progress::CommandAccepted,
        Readiness::DocumentCommitted => {
            matches!(
                reached,
                Progress::DocumentCommitted | Progress::SameDocumentNavigation
            )
        }
        Readiness::DomContentLoaded => {
            matches!(
                reached,
                Progress::DomContentLoaded | Progress::SameDocumentNavigation
            )
        }
        Readiness::Load => matches!(reached, Progress::Load | Progress::SameDocumentNavigation),
        Readiness::ControllerCompleted => reached == Progress::ControllerCompleted,
        Readiness::NetworkIdle => false,
    }
}

/// Typed domain errors for bounded navigation scheduling receipts.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserNavigationSchedulingError {
    #[error("navigation progress retained count exceeds admitted count")]
    ProgressRetainedExceedsAdmitted,
    #[error("navigation progress retained and dropped counts overflowed")]
    ProgressAccountingOverflow,
    #[error("navigation progress admitted count does not equal retained plus dropped")]
    ProgressAccountingMismatch,
    #[error("navigation readiness receipt does not satisfy the requested checkpoint")]
    ReadinessMismatch,
    #[error("same-document navigation requires a completed outcome")]
    SameDocumentWithoutCompletion,
}
