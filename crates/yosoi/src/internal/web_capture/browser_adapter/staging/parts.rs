use crate::internal::web_capture as yosoi_web_capture;

use super::{BrowserArtifactMapping, BrowserByteDomain, LossExtent};
use crate::internal::types::ReasonCode;
use std::{fmt, sync::Arc};
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum StagingState {
    Unrequested,
    Complete,
    Partial,
    Truncated,
    Discarded,
    Unavailable,
    Failed,
    Disabled,
    Unsupported,
}
#[allow(clippy::large_enum_variant)]
#[derive(Clone, Eq, PartialEq)]
pub enum BrowserStagingParts {
    Unrequested,
    Structured {
        evidence: yosoi_web_capture::BrowserStructuredEvidence,
        reason: Option<ReasonCode>,
    },
    Complete {
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
    },
    Partial {
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
        loss: LossExtent,
        reason: ReasonCode,
    },
    Truncated {
        mapping: BrowserArtifactMapping,
        bytes: Arc<[u8]>,
        observed: u64,
        loss: LossExtent,
        reason: ReasonCode,
    },
    Discarded {
        domain: BrowserByteDomain,
        observed: LossExtent,
        reason: ReasonCode,
    },
    Unavailable(ReasonCode),
    Failed(ReasonCode),
    Disabled(ReasonCode),
    Unsupported(ReasonCode),
}

impl fmt::Debug for BrowserStagingParts {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        match self {
            Self::Unrequested => formatter.write_str("Unrequested"),
            Self::Structured { evidence, reason } => formatter
                .debug_struct("Structured")
                .field("evidence", evidence)
                .field("reason", reason)
                .finish(),
            Self::Complete {
                mapping,
                bytes,
                observed,
            } => formatter
                .debug_struct("Complete")
                .field("mapping", mapping)
                .field("byte_len", &bytes.len())
                .field("bytes", &"<redacted>")
                .field("observed", observed)
                .finish(),
            Self::Partial {
                mapping,
                bytes,
                observed,
                loss,
                reason,
            } => formatter
                .debug_struct("Partial")
                .field("mapping", mapping)
                .field("byte_len", &bytes.len())
                .field("bytes", &"<redacted>")
                .field("observed", observed)
                .field("loss", loss)
                .field("reason", reason)
                .finish(),
            Self::Truncated {
                mapping,
                bytes,
                observed,
                loss,
                reason,
            } => formatter
                .debug_struct("Truncated")
                .field("mapping", mapping)
                .field("byte_len", &bytes.len())
                .field("bytes", &"<redacted>")
                .field("observed", observed)
                .field("loss", loss)
                .field("reason", reason)
                .finish(),
            Self::Discarded {
                domain,
                observed,
                reason,
            } => formatter
                .debug_struct("Discarded")
                .field("domain", domain)
                .field("observed", observed)
                .field("reason", reason)
                .finish(),
            Self::Unavailable(reason) => {
                formatter.debug_tuple("Unavailable").field(reason).finish()
            }
            Self::Failed(reason) => formatter.debug_tuple("Failed").field(reason).finish(),
            Self::Disabled(reason) => formatter.debug_tuple("Disabled").field(reason).finish(),
            Self::Unsupported(reason) => {
                formatter.debug_tuple("Unsupported").field(reason).finish()
            }
        }
    }
}
