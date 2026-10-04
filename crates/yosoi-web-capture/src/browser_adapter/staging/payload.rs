//! Browser artifact construction for the shared acquired-payload contract.

use std::sync::Arc;

use crate::{AcquiredPayloadOutcome, AcquiredPayloadState, BrowserByteDomain, WebArtifactFamily};

use super::{
    ArtifactStagingOutcome, BrowserArtifactMapping, BrowserByteLayer, BrowserStagingFamily,
    LossExtent, StagingOutcomeError,
};

impl ArtifactStagingOutcome {
    /// Adds browser snapshot identity to a provider-neutral acquired source payload.
    ///
    /// Payload state and accounting have already been validated by the shared
    /// acquisition contract; this boundary only constructs browser artifact staging.
    pub fn acquired_payload(
        mapping: BrowserArtifactMapping,
        outcome: AcquiredPayloadOutcome,
    ) -> Result<Self, StagingOutcomeError> {
        if mapping.family() != BrowserStagingFamily::Artifact(WebArtifactFamily::Source)
            || mapping.layer() != BrowserByteLayer::DecodedResponseBody
        {
            return Err(StagingOutcomeError::AcquiredPayloadMappingMismatch);
        }
        let (state, accounting) = outcome.into_parts();
        match state {
            AcquiredPayloadState::Complete(source) => {
                let observed = accounting
                    .observed_bytes()
                    .as_known()
                    .ok_or(StagingOutcomeError::CompleteLengthMismatch)?
                    .get();
                Self::complete(mapping, Arc::from(source.into_bytes()), observed)
            }
            AcquiredPayloadState::Truncated { source, reason } => {
                let observed = accounting
                    .observed_bytes()
                    .as_known()
                    .ok_or(StagingOutcomeError::LossMismatch)?
                    .get();
                let loss = accounting
                    .lost_bytes()
                    .as_known()
                    .map_or(LossExtent::Unknown, |lost| LossExtent::Known(lost.get()));
                Self::truncated(
                    mapping,
                    Arc::from(source.into_bytes()),
                    observed,
                    loss,
                    reason,
                )
            }
            AcquiredPayloadState::Discarded { reason } => {
                let observed = accounting
                    .observed_bytes()
                    .as_known()
                    .map_or(LossExtent::Unknown, |value| LossExtent::Known(value.get()));
                Ok(Self::discarded(
                    BrowserByteDomain::CdpDecodedBody,
                    observed,
                    reason,
                ))
            }
            AcquiredPayloadState::Unavailable { reason } => Ok(Self::unavailable(reason)),
            AcquiredPayloadState::Failed { reason } => Ok(Self::failed(reason)),
            AcquiredPayloadState::Disabled { reason } => Ok(Self::disabled(reason)),
            AcquiredPayloadState::Unsupported { reason } => Ok(Self::unsupported(reason)),
        }
    }
}
