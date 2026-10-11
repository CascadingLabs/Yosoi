//! Input and result types used by the acquisition lifecycle coordinator.

use crate::internal::web_capture as yosoi_web_capture;

use chrono::{DateTime, Utc};
use thiserror::Error;

use crate::internal::web_capture::{
    ByteCount, CaptureEnvironment, CaptureOffset, CaptureResolution, CaptureTermination,
    ControllerStopReason, EventCount, InFlightActivity, MeasuredCount, WebArtifactManifest,
    WebArtifactRef, WebArtifactRelationship, WebProviderCapabilityProfile,
};

/// One producer event offered to the lifecycle coordinator.
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct LifecycleEvent {
    pub(super) offset: CaptureOffset,
    pub(super) admitted_bytes: ByteCount,
    pub(super) retained_bytes: ByteCount,
    pub(super) retained: bool,
}
impl LifecycleEvent {
    pub const fn new(
        offset: CaptureOffset,
        admitted_bytes: ByteCount,
        retained_bytes: ByteCount,
        retained: bool,
    ) -> Result<Self, LifecycleEventError> {
        if retained_bytes.get() > admitted_bytes.get() {
            return Err(LifecycleEventError::RetainedBytesExceedAdmitted);
        }
        Ok(Self {
            offset,
            admitted_bytes,
            retained_bytes,
            retained,
        })
    }
    pub const fn offset(self) -> CaptureOffset {
        self.offset
    }
    pub const fn admitted_bytes(self) -> ByteCount {
        self.admitted_bytes
    }
    pub const fn retained_bytes(self) -> ByteCount {
        self.retained_bytes
    }
    pub const fn is_retained(self) -> bool {
        self.retained
    }
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum LifecycleEventError {
    #[error("event retained bytes cannot exceed admitted bytes")]
    RetainedBytesExceedAdmitted,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct AdmittedEvent {
    pub(super) admitted_bytes: ByteCount,
    pub(super) retained_bytes: ByteCount,
    pub(super) event_retained: bool,
}
impl AdmittedEvent {
    pub(in crate::internal::web_capture) const fn new(
        admitted_bytes: ByteCount,
        retained_bytes: ByteCount,
        event_retained: bool,
    ) -> Self {
        Self {
            admitted_bytes,
            retained_bytes,
            event_retained,
        }
    }
    pub const fn admitted_bytes(self) -> ByteCount {
        self.admitted_bytes
    }
    pub const fn retained_bytes(self) -> ByteCount {
        self.retained_bytes
    }
    pub const fn is_event_retained(self) -> bool {
        self.event_retained
    }
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum EventAdmission {
    Admitted(AdmittedEvent),
    AdmittedAndStopped {
        admitted: AdmittedEvent,
        termination: CaptureTermination,
    },
    NotAdmittedAndStopped(CaptureTermination),
}

#[derive(Clone, Debug, Eq, PartialEq)]
pub enum LifecycleStop {
    Completed(ControllerStopReason),
    Interrupted(yosoi_web_capture::InterruptionEvidence),
}

#[derive(Debug, Default, Eq, PartialEq)]
pub struct StagedPayloads(pub(super) Vec<(WebArtifactRef, Vec<u8>)>);
impl StagedPayloads {
    pub fn insert(
        &mut self,
        reference: WebArtifactRef,
        bytes: Vec<u8>,
    ) -> Result<(), StagedPayloadError> {
        if self.0.iter().any(|(existing, _)| *existing == reference) {
            return Err(StagedPayloadError::Duplicate);
        }
        self.0.push((reference, bytes));
        Ok(())
    }

    pub fn into_entries(self) -> Vec<(WebArtifactRef, Vec<u8>)> {
        self.0
    }
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum StagedPayloadError {
    #[error("payload reference was already staged")]
    Duplicate,
}

#[derive(Debug)]
pub struct LifecycleFinalizationInput {
    pub finished_at: DateTime<Utc>,
    pub terminal_offset: CaptureOffset,
    pub dropped_events: MeasuredCount<EventCount>,
    pub dropped_bytes: MeasuredCount<ByteCount>,
    pub in_flight: InFlightActivity,
    pub resolution: CaptureResolution,
    pub environment: CaptureEnvironment,
    pub capabilities: WebProviderCapabilityProfile,
    pub manifest: WebArtifactManifest,
    pub relationships: Vec<WebArtifactRelationship>,
    pub payloads: StagedPayloads,
}
