#![allow(clippy::missing_const_for_fn)]
mod artifacts;
pub use artifacts::{
    BrowserArtifactStaging, BrowserDiscardedArtifactDescriptor, BrowserStagingAccounting,
    BrowserStagingSlot, StagingSlotError,
};
mod parts;
pub use parts::{BrowserStagingParts, StagingState};
mod mapping;
pub use mapping::{
    BrowserArtifactMapping, BrowserByteLayer, BrowserMappingError, BrowserSnapshotObservation,
    BrowserStagingFamily,
};
mod payload;

use super::facts::BrowserAdapterOutputError;
use crate::browser_spec::BrowserByteDomain;
use crate::{
    ArtifactByteExtent, ArtifactSensitivity, ByteCount, CaptureOffset, MeasuredCount, MediaType,
    WebArtifactFamily,
};
use std::sync::Arc;
use thiserror::Error;
pub use yosoi_types::LossExtent;
use yosoi_types::ReasonCode;

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct ArtifactStagingOutcome {
    data: BrowserStagingParts,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum StagingOutcomeError {
    #[error("retained byte length cannot be represented")]
    RetainedLengthOverflow,
    #[error("complete data must retain every observed byte")]
    CompleteLengthMismatch,
    #[error("partial/truncated retained and known lost bytes must equal observed bytes")]
    LossMismatch,
    #[error("partial/truncated data must lose at least one byte")]
    NoLoss,
    #[error("canonical acquired payloads can only stage decoded source bodies")]
    AcquiredPayloadMappingMismatch,
}
impl ArtifactStagingOutcome {
    pub fn structured(
        evidence: crate::BrowserStructuredEvidence,
        reason: Option<ReasonCode>,
    ) -> Result<Self, StagingOutcomeError> {
        let unexplained_loss = match &evidence {
            crate::BrowserStructuredEvidence::Network {
                resource_accounting,
                event_accounting,
                ..
            } => {
                resource_accounting.lost() != LossExtent::Known(0)
                    || !matches!(event_accounting.dropped(), crate::MeasuredCount::Known(count) if count.get() == 0)
            }
            crate::BrowserStructuredEvidence::Accessibility(value) => {
                value.nodes_lost != LossExtent::Known(0) || value.bytes.lost != LossExtent::Known(0)
            }
            crate::BrowserStructuredEvidence::RuntimeDiagnostics {
                runtime_event_accounting,
                byte_accounting,
                ..
            } => {
                !matches!(runtime_event_accounting.dropped(), crate::MeasuredCount::Known(count) if count.get() == 0)
                    || byte_accounting.lost != LossExtent::Known(0)
            }
            crate::BrowserStructuredEvidence::Layout(_) => false,
        };
        if reason.is_none() && unexplained_loss {
            return Err(StagingOutcomeError::LossMismatch);
        }
        Ok(Self {
            data: BrowserStagingParts::Structured { evidence, reason },
        })
    }
    pub const fn unrequested() -> Self {
        Self {
            data: BrowserStagingParts::Unrequested,
        }
    }
    pub fn complete(
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
    ) -> Result<Self, StagingOutcomeError> {
        let retained =
            u64::try_from(bytes.len()).map_err(|_| StagingOutcomeError::RetainedLengthOverflow)?;
        if retained != observed {
            return Err(StagingOutcomeError::CompleteLengthMismatch);
        }
        Ok(Self {
            data: BrowserStagingParts::Complete {
                mapping,
                bytes,
                observed,
            },
        })
    }
    pub fn partial(
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
        loss: LossExtent,
        reason: ReasonCode,
    ) -> Result<Self, StagingOutcomeError> {
        Self::lossy(false, mapping, bytes, observed, loss, reason)
    }
    pub fn truncated(
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
        loss: LossExtent,
        reason: ReasonCode,
    ) -> Result<Self, StagingOutcomeError> {
        Self::lossy(true, mapping, bytes, observed, loss, reason)
    }
    fn lossy(
        truncated: bool,
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
        loss: LossExtent,
        reason: ReasonCode,
    ) -> Result<Self, StagingOutcomeError> {
        let retained =
            u64::try_from(bytes.len()).map_err(|_| StagingOutcomeError::RetainedLengthOverflow)?;
        if retained > observed {
            return Err(StagingOutcomeError::LossMismatch);
        }
        if retained == observed && (truncated || loss != LossExtent::Unknown) {
            return Err(StagingOutcomeError::NoLoss);
        }
        if let LossExtent::Known(lost) = loss
            && (lost == 0 || retained.checked_add(lost) != Some(observed))
        {
            return Err(StagingOutcomeError::LossMismatch);
        }
        let data = if truncated {
            BrowserStagingParts::Truncated {
                mapping,
                bytes,
                observed,
                loss,
                reason,
            }
        } else {
            BrowserStagingParts::Partial {
                mapping,
                bytes,
                observed,
                loss,
                reason,
            }
        };
        Ok(Self { data })
    }
    pub const fn discarded(
        domain: BrowserByteDomain,
        observed: LossExtent,
        reason: ReasonCode,
    ) -> Self {
        Self {
            data: BrowserStagingParts::Discarded {
                domain,
                observed,
                reason,
            },
        }
    }
    pub fn unavailable(reason: ReasonCode) -> Self {
        Self {
            data: BrowserStagingParts::Unavailable(reason),
        }
    }
    pub fn failed(reason: ReasonCode) -> Self {
        Self {
            data: BrowserStagingParts::Failed(reason),
        }
    }
    pub fn disabled(reason: ReasonCode) -> Self {
        Self {
            data: BrowserStagingParts::Disabled(reason),
        }
    }
    pub fn unsupported(reason: ReasonCode) -> Self {
        Self {
            data: BrowserStagingParts::Unsupported(reason),
        }
    }
    pub const fn state(&self) -> StagingState {
        match self.data {
            BrowserStagingParts::Unrequested => StagingState::Unrequested,
            BrowserStagingParts::Structured { ref reason, .. } => {
                if reason.is_some() {
                    StagingState::Partial
                } else {
                    StagingState::Complete
                }
            }
            BrowserStagingParts::Complete { .. } => StagingState::Complete,
            BrowserStagingParts::Partial { .. } => StagingState::Partial,
            BrowserStagingParts::Truncated { .. } => StagingState::Truncated,
            BrowserStagingParts::Discarded { .. } => StagingState::Discarded,
            BrowserStagingParts::Unavailable(_) => StagingState::Unavailable,
            BrowserStagingParts::Failed(_) => StagingState::Failed,
            BrowserStagingParts::Disabled(_) => StagingState::Disabled,
            BrowserStagingParts::Unsupported(_) => StagingState::Unsupported,
        }
    }
    pub fn bytes(&self) -> Option<&[u8]> {
        match &self.data {
            BrowserStagingParts::Complete { bytes, .. }
            | BrowserStagingParts::Partial { bytes, .. }
            | BrowserStagingParts::Truncated { bytes, .. } => Some(bytes),
            _ => None,
        }
    }
    pub fn shared_bytes(&self) -> Option<Arc<[u8]>> {
        match &self.data {
            BrowserStagingParts::Complete { bytes, .. }
            | BrowserStagingParts::Partial { bytes, .. }
            | BrowserStagingParts::Truncated { bytes, .. } => Some(Arc::clone(bytes)),
            _ => None,
        }
    }
    pub fn parts(&self) -> &BrowserStagingParts {
        &self.data
    }
    pub fn into_parts(self) -> BrowserStagingParts {
        self.data
    }
    pub fn mapping(&self) -> Option<BrowserArtifactMapping> {
        match &self.data {
            BrowserStagingParts::Complete { mapping, .. }
            | BrowserStagingParts::Partial { mapping, .. }
            | BrowserStagingParts::Truncated { mapping, .. } => Some(*mapping),
            _ => None,
        }
    }
    pub fn retained(&self) -> Result<u64, StagingOutcomeError> {
        let len = match &self.data {
            BrowserStagingParts::Complete { bytes, .. }
            | BrowserStagingParts::Partial { bytes, .. }
            | BrowserStagingParts::Truncated { bytes, .. } => bytes.len(),
            _ => 0,
        };
        u64::try_from(len).map_err(|_| StagingOutcomeError::RetainedLengthOverflow)
    }
}
