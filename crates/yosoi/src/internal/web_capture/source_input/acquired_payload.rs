use crate::internal::types::ReasonCode;
use thiserror::Error;

use super::{RetainedSource, RetainedSourceExtent};
use crate::internal::web_capture::{ByteCount, MeasuredCount};

/// Checked retained, observed, and lost byte facts for one acquired payload.
#[derive(Clone, Debug, Eq, PartialEq)]
#[allow(
    clippy::struct_field_names,
    reason = "retained, observed, and lost byte counts are explicit accounting terms"
)]
pub struct AcquiredPayloadAccounting {
    retained_bytes: ByteCount,
    observed_bytes: MeasuredCount<ByteCount>,
    lost_bytes: MeasuredCount<ByteCount>,
}

impl AcquiredPayloadAccounting {
    pub fn new(
        retained_bytes: ByteCount,
        observed_bytes: MeasuredCount<ByteCount>,
        lost_bytes: MeasuredCount<ByteCount>,
    ) -> Result<Self, AcquiredPayloadError> {
        if let MeasuredCount::Known(observed) = &observed_bytes {
            if retained_bytes.get() > observed.get() {
                return Err(AcquiredPayloadError::RetainedExceedsObserved);
            }
            if let MeasuredCount::Known(lost) = &lost_bytes {
                let explained = retained_bytes
                    .get()
                    .checked_add(lost.get())
                    .ok_or(AcquiredPayloadError::AccountingOverflow)?;
                if explained != observed.get() {
                    return Err(AcquiredPayloadError::KnownLossMismatch);
                }
            }
        }
        Ok(Self {
            retained_bytes,
            observed_bytes,
            lost_bytes,
        })
    }

    pub const fn retained_bytes(&self) -> ByteCount {
        self.retained_bytes
    }
    pub const fn observed_bytes(&self) -> &MeasuredCount<ByteCount> {
        &self.observed_bytes
    }
    pub const fn lost_bytes(&self) -> &MeasuredCount<ByteCount> {
        &self.lost_bytes
    }
}

/// Provider-neutral terminal meaning of an acquired byte payload.
#[derive(Debug, Eq, PartialEq)]
pub enum AcquiredPayloadState {
    Complete(RetainedSource),
    Truncated {
        source: RetainedSource,
        reason: ReasonCode,
    },
    Discarded {
        reason: ReasonCode,
    },
    Unavailable {
        reason: ReasonCode,
    },
    Failed {
        reason: ReasonCode,
    },
    Disabled {
        reason: ReasonCode,
    },
    Unsupported {
        reason: ReasonCode,
    },
}

/// One canonical acquired byte-payload result with validated extent accounting.
#[derive(Debug, Eq, PartialEq)]
pub struct AcquiredPayloadOutcome {
    state: AcquiredPayloadState,
    accounting: AcquiredPayloadAccounting,
}

impl AcquiredPayloadOutcome {
    pub fn complete(bytes: Vec<u8>) -> Result<Self, AcquiredPayloadError> {
        let retained = byte_len(&bytes)?;
        let accounting = AcquiredPayloadAccounting::new(
            retained,
            MeasuredCount::Known(retained),
            MeasuredCount::Known(ByteCount::new(0)),
        )?;
        Ok(Self {
            state: AcquiredPayloadState::Complete(RetainedSource::complete(bytes)),
            accounting,
        })
    }

    pub fn truncated(
        bytes: Vec<u8>,
        observed_bytes: ByteCount,
        lost_bytes: MeasuredCount<ByteCount>,
        reason: ReasonCode,
    ) -> Result<Self, AcquiredPayloadError> {
        let retained = byte_len(&bytes)?;
        let accounting = AcquiredPayloadAccounting::new(
            retained,
            MeasuredCount::Known(observed_bytes),
            lost_bytes,
        )?;
        if matches!(accounting.lost_bytes(), MeasuredCount::Known(lost) if lost.get() == 0) {
            return Err(AcquiredPayloadError::TruncatedWithoutLoss);
        }
        Ok(Self {
            state: AcquiredPayloadState::Truncated {
                source: RetainedSource::new(bytes, RetainedSourceExtent::Truncated),
                reason,
            },
            accounting,
        })
    }

    pub fn discarded(
        observed_bytes: MeasuredCount<ByteCount>,
        reason: ReasonCode,
    ) -> Result<Self, AcquiredPayloadError> {
        let lost_bytes = observed_bytes.clone();
        let accounting =
            AcquiredPayloadAccounting::new(ByteCount::new(0), observed_bytes, lost_bytes)?;
        Ok(Self {
            state: AcquiredPayloadState::Discarded { reason },
            accounting,
        })
    }

    pub fn unavailable(reason: ReasonCode) -> Result<Self, AcquiredPayloadError> {
        Self::without_payload(
            AcquiredPayloadState::Unavailable {
                reason: reason.clone(),
            },
            reason,
        )
    }

    pub fn failed(reason: ReasonCode) -> Result<Self, AcquiredPayloadError> {
        Self::without_payload(
            AcquiredPayloadState::Failed {
                reason: reason.clone(),
            },
            reason,
        )
    }

    pub fn disabled(reason: ReasonCode) -> Result<Self, AcquiredPayloadError> {
        Self::without_payload(
            AcquiredPayloadState::Disabled {
                reason: reason.clone(),
            },
            reason,
        )
    }

    pub fn unsupported(reason: ReasonCode) -> Result<Self, AcquiredPayloadError> {
        Self::without_payload(
            AcquiredPayloadState::Unsupported {
                reason: reason.clone(),
            },
            reason,
        )
    }

    fn without_payload(
        state: AcquiredPayloadState,
        reason: ReasonCode,
    ) -> Result<Self, AcquiredPayloadError> {
        let unavailable = MeasuredCount::Unavailable { reason };
        let accounting =
            AcquiredPayloadAccounting::new(ByteCount::new(0), unavailable.clone(), unavailable)?;
        Ok(Self { state, accounting })
    }

    pub const fn state(&self) -> &AcquiredPayloadState {
        &self.state
    }
    pub const fn accounting(&self) -> &AcquiredPayloadAccounting {
        &self.accounting
    }
    pub const fn retained_source(&self) -> Option<&RetainedSource> {
        match &self.state {
            AcquiredPayloadState::Complete(source)
            | AcquiredPayloadState::Truncated { source, .. } => Some(source),
            AcquiredPayloadState::Discarded { .. }
            | AcquiredPayloadState::Unavailable { .. }
            | AcquiredPayloadState::Failed { .. }
            | AcquiredPayloadState::Disabled { .. }
            | AcquiredPayloadState::Unsupported { .. } => None,
        }
    }
    pub const fn reason(&self) -> Option<&ReasonCode> {
        match &self.state {
            AcquiredPayloadState::Complete(_) => None,
            AcquiredPayloadState::Truncated { reason, .. }
            | AcquiredPayloadState::Discarded { reason }
            | AcquiredPayloadState::Unavailable { reason }
            | AcquiredPayloadState::Failed { reason }
            | AcquiredPayloadState::Disabled { reason }
            | AcquiredPayloadState::Unsupported { reason } => Some(reason),
        }
    }
    pub fn into_parts(self) -> (AcquiredPayloadState, AcquiredPayloadAccounting) {
        (self.state, self.accounting)
    }
}

fn byte_len(bytes: &[u8]) -> Result<ByteCount, AcquiredPayloadError> {
    u64::try_from(bytes.len())
        .map(ByteCount::new)
        .map_err(|_| AcquiredPayloadError::RetainedLengthOverflow)
}

#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum AcquiredPayloadError {
    #[error("retained payload length cannot be represented")]
    RetainedLengthOverflow,
    #[error("retained bytes cannot exceed observed bytes")]
    RetainedExceedsObserved,
    #[error("retained and known lost bytes must equal observed bytes")]
    KnownLossMismatch,
    #[error("payload byte accounting overflowed")]
    AccountingOverflow,
    #[error("a truncated payload must report known or unknown byte loss")]
    TruncatedWithoutLoss,
}

#[cfg(test)]
mod tests {
    use super::*;

    fn reason() -> ReasonCode {
        ReasonCode::new("web_capture.test.payload").unwrap()
    }

    #[test]
    fn complete_payload_has_exact_zero_loss_accounting() {
        let outcome = AcquiredPayloadOutcome::complete(vec![1, 2, 3]).unwrap();
        assert!(matches!(outcome.state(), AcquiredPayloadState::Complete(_)));
        assert_eq!(outcome.accounting().retained_bytes(), ByteCount::new(3));
        assert_eq!(
            outcome.accounting().observed_bytes(),
            &MeasuredCount::Known(ByteCount::new(3))
        );
        assert_eq!(
            outcome.accounting().lost_bytes(),
            &MeasuredCount::Known(ByteCount::new(0))
        );
    }

    #[test]
    fn contradictory_known_loss_is_rejected() {
        let error = AcquiredPayloadOutcome::truncated(
            vec![1, 2],
            ByteCount::new(5),
            MeasuredCount::Known(ByteCount::new(2)),
            reason(),
        )
        .unwrap_err();
        assert_eq!(error, AcquiredPayloadError::KnownLossMismatch);
    }

    #[test]
    fn truncated_payload_can_preserve_unknown_total_loss() {
        let reason = reason();
        let outcome = AcquiredPayloadOutcome::truncated(
            vec![1, 2],
            ByteCount::new(2),
            MeasuredCount::Unavailable {
                reason: reason.clone(),
            },
            reason,
        )
        .unwrap();
        assert!(matches!(
            outcome.state(),
            AcquiredPayloadState::Truncated { .. }
        ));
    }

    #[test]
    fn discarded_payload_retains_nothing_and_loses_observed_bytes() {
        let outcome =
            AcquiredPayloadOutcome::discarded(MeasuredCount::Known(ByteCount::new(7)), reason())
                .unwrap();
        assert_eq!(outcome.accounting().retained_bytes(), ByteCount::new(0));
        assert_eq!(
            outcome.accounting().lost_bytes(),
            &MeasuredCount::Known(ByteCount::new(7))
        );
    }
}
