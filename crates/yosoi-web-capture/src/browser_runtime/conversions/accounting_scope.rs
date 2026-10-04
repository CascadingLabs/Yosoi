use crate as yosoi;
use crate::VoidCrawlAdapterError;
use std::sync::Arc;
use void_crawl_core as provider;
use yosoi_types::ReasonCode;

#[allow(
    dead_code,
    reason = "closed CAS-329 conversion contract is table-tested"
)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub(super) enum ProviderResultDescriptor {
    Complete,
    Truncated,
    Discarded,
    Unavailable(&'static str),
    Failed(&'static str),
}

#[allow(
    dead_code,
    reason = "closed CAS-329 conversion contract is table-tested"
)]
pub(super) const fn byte_domain(
    value: provider::BrowserByteDomain,
) -> Result<yosoi::BrowserByteDomain, VoidCrawlAdapterError> {
    match value {
        provider::BrowserByteDomain::CdpDecodedBody => Ok(yosoi::BrowserByteDomain::CdpDecodedBody),
        provider::BrowserByteDomain::RenderedDomUtf8 => {
            Ok(yosoi::BrowserByteDomain::RenderedDomUtf8)
        }
        provider::BrowserByteDomain::AccessibilityJsonUtf8 => {
            Ok(yosoi::BrowserByteDomain::AccessibilityJsonUtf8)
        }
        provider::BrowserByteDomain::RuntimeDiagnosticUtf8 => {
            Ok(yosoi::BrowserByteDomain::RuntimeDiagnosticUtf8)
        }
        provider::BrowserByteDomain::ScreenshotPng => Ok(yosoi::BrowserByteDomain::ScreenshotPng),
        provider::BrowserByteDomain::RecordingFrame
        | provider::BrowserByteDomain::EncodedRecording => {
            Err(VoidCrawlAdapterError::UnsupportedRecording)
        }
    }
}

#[allow(
    dead_code,
    reason = "closed CAS-329 conversion contract is table-tested"
)]
pub(super) const fn payload_extent(
    value: provider::BrowserPayloadExtent,
) -> ProviderResultDescriptor {
    match value {
        provider::BrowserPayloadExtent::Complete => ProviderResultDescriptor::Complete,
        provider::BrowserPayloadExtent::Truncated { complete_bytes: _ } => {
            ProviderResultDescriptor::Truncated
        }
        provider::BrowserPayloadExtent::Discarded { observed_bytes: _ } => {
            ProviderResultDescriptor::Discarded
        }
        provider::BrowserPayloadExtent::Unavailable { reason } => {
            ProviderResultDescriptor::Unavailable(match reason {
                provider::BrowserPayloadUnavailableReason::ProviderDidNotReport => {
                    "provider-did-not-report"
                }
                provider::BrowserPayloadUnavailableReason::NotCollected => "not-collected",
                provider::BrowserPayloadUnavailableReason::Unsupported => "unsupported",
            })
        }
        provider::BrowserPayloadExtent::Failed { reason } => {
            ProviderResultDescriptor::Failed(match reason {
                provider::BrowserPayloadFailureReason::ProviderRejected => "provider-rejected",
                provider::BrowserPayloadFailureReason::ProviderDisconnected => {
                    "provider-disconnected"
                }
                provider::BrowserPayloadFailureReason::InvalidEncoding => "invalid-encoding",
                provider::BrowserPayloadFailureReason::Deadline => "deadline",
                provider::BrowserPayloadFailureReason::Cancelled => "cancelled",
                provider::BrowserPayloadFailureReason::SinkFailure => "sink-failure",
            })
        }
    }
}

pub fn reason(value: &'static str) -> Result<ReasonCode, VoidCrawlAdapterError> {
    ReasonCode::new(value).map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub fn missing_observation_accounting(
    observation_failed: bool,
) -> Result<yosoi::EventAccounting, VoidCrawlAdapterError> {
    yosoi::EventAccounting::new(
        yosoi::EventCount::new(0),
        yosoi::EventCount::new(0),
        if observation_failed {
            yosoi::MeasuredCount::Unavailable {
                reason: reason("voidcrawl.observation.finalization-failed")?,
            }
        } else {
            yosoi::MeasuredCount::Known(yosoi::EventCount::new(0))
        },
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

const fn provider_error_category(
    value: provider::VoidCrawlErrorCategory,
) -> crate::VoidCrawlAdapterErrorCategory {
    match value {
        provider::VoidCrawlErrorCategory::InvalidInput => {
            crate::VoidCrawlAdapterErrorCategory::InvalidInput
        }
        provider::VoidCrawlErrorCategory::Unsupported => {
            crate::VoidCrawlAdapterErrorCategory::Unsupported
        }
        provider::VoidCrawlErrorCategory::Timeout => crate::VoidCrawlAdapterErrorCategory::Timeout,
        provider::VoidCrawlErrorCategory::Interrupted => {
            crate::VoidCrawlAdapterErrorCategory::Interrupted
        }
        provider::VoidCrawlErrorCategory::Unavailable => {
            crate::VoidCrawlAdapterErrorCategory::Unavailable
        }
        provider::VoidCrawlErrorCategory::ProviderFailure => {
            crate::VoidCrawlAdapterErrorCategory::ProviderFailure
        }
        provider::VoidCrawlErrorCategory::Internal => {
            crate::VoidCrawlAdapterErrorCategory::Internal
        }
        _ => crate::VoidCrawlAdapterErrorCategory::UnknownFuture,
    }
}

pub const fn map_provider_error(error: &provider::VoidCrawlError) -> VoidCrawlAdapterError {
    VoidCrawlAdapterError::Provider {
        code: error.code().as_str(),
        category: provider_error_category(error.category()),
    }
}

pub const fn main_document_scope() -> yosoi::BrowserDocumentScope {
    yosoi::BrowserDocumentScope {
        frame: yosoi::BrowserFrameId(1),
        epoch: yosoi::BrowserDocumentEpoch(1),
    }
}

pub const fn document_scope(
    value: &provider::DocumentScope,
) -> Option<yosoi::BrowserDocumentScope> {
    let provider::DocumentEpoch::Known(epoch) = value.epoch else {
        return None;
    };
    Some(yosoi::BrowserDocumentScope {
        frame: value.frame_id,
        epoch: yosoi::BrowserDocumentEpoch(epoch),
    })
}

fn bytes_outcome(
    bytes: &[u8],
    retained: usize,
    complete: Option<usize>,
    state: provider::SnapshotState,
    mapping: yosoi::BrowserArtifactMapping,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    if retained != bytes.len() {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    }
    match state {
        provider::SnapshotState::Complete => yosoi::ArtifactStagingOutcome::complete(
            mapping,
            Arc::from(bytes),
            u64::try_from(retained).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        ),
        provider::SnapshotState::Truncated => {
            let observed = u64::try_from(complete.ok_or(VoidCrawlAdapterError::InvalidStaging)?)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            let retained =
                u64::try_from(retained).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
            let lost = observed
                .checked_sub(retained)
                .filter(|v| *v > 0)
                .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
            yosoi::ArtifactStagingOutcome::truncated(
                mapping,
                Arc::from(bytes),
                observed,
                yosoi::LossExtent::Known(lost),
                reason("voidcrawl.snapshot.byte-limit")?,
            )
        }
        provider::SnapshotState::Unavailable { reason: why } => {
            return Ok(yosoi::ArtifactStagingOutcome::unavailable(reason(
                match why {
                    provider::SnapshotUnavailableReason::BrowserDidNotReport => {
                        "voidcrawl.snapshot.browser-did-not-report"
                    }
                    provider::SnapshotUnavailableReason::FrameUnavailable => {
                        "voidcrawl.snapshot.frame-unavailable"
                    }
                    provider::SnapshotUnavailableReason::SerializationFailed => {
                        "voidcrawl.snapshot.serialization-failed"
                    }
                },
            )?));
        }
    }
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub fn rendered_dom(
    value: &provider::RenderedDomSnapshot,
    at: yosoi::CaptureOffset,
) -> Result<yosoi::ArtifactStagingOutcome, VoidCrawlAdapterError> {
    let Some(snapshot_scope) = document_scope(&value.scope) else {
        return Ok(yosoi::ArtifactStagingOutcome::unavailable(reason(
            "voidcrawl.snapshot.document-epoch-unavailable",
        )?));
    };
    let mapping = yosoi::BrowserArtifactMapping::new(
        yosoi::BrowserStagingFamily::Artifact(yosoi::WebArtifactFamily::RenderedDom),
        yosoi::BrowserByteLayer::RenderedDomUtf8,
    )
    .and_then(|m| {
        m.with_snapshot(yosoi::BrowserSnapshotObservation::rendered_dom(
            snapshot_scope,
            at,
        ))
    })
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    bytes_outcome(
        value.bytes(),
        value.retained_bytes,
        value.complete_bytes,
        value.state,
        mapping,
    )
}

pub(super) fn event_accounting(
    admitted: u64,
    retained: u64,
    dropped: provider::MeasuredCount,
) -> Result<yosoi::EventAccounting, VoidCrawlAdapterError> {
    let dropped = match dropped {
        provider::MeasuredCount::Known { value } => {
            yosoi::MeasuredCount::Known(yosoi::EventCount::new(value))
        }
        provider::MeasuredCount::Unavailable {
            reason: unavailable,
        } => {
            let code = match unavailable {
                provider::MeasurementUnavailableReason::NotCollected => {
                    "voidcrawl.events.dropped-not-collected"
                }
                provider::MeasurementUnavailableReason::ProviderDidNotReport => {
                    "voidcrawl.events.dropped-provider-did-not-report"
                }
            };
            yosoi::MeasuredCount::Unavailable {
                reason: reason(code)?,
            }
        }
    };
    yosoi::EventAccounting::new(
        yosoi::EventCount::new(admitted),
        yosoi::EventCount::new(retained),
        dropped,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
