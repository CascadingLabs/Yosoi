use super::{VoidCrawlAdapterError, conversions};
use crate as yosoi;
use std::sync::Arc;
pub(super) fn slot(
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    yosoi::BrowserStagingSlot::new(family, outcome)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}
pub(super) fn retained_slot(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
    media_type: &str,
    at: yosoi::CaptureOffset,
    derived_from: Vec<yosoi_types::ArtifactRef>,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    retained_slot_with_producer(
        spec,
        spec.producer(),
        family,
        outcome,
        media_type,
        at,
        derived_from,
    )
}

pub(super) fn retained_slot_with_producer(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    producer: &yosoi_types::Producer,
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
    media_type: &str,
    at: yosoi::CaptureOffset,
    derived_from: Vec<yosoi_types::ArtifactRef>,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    let Some(bytes) = outcome.bytes() else {
        let staged = slot(family, outcome.clone())?;
        if let yosoi::BrowserStagingParts::Discarded { observed, .. } = outcome.parts() {
            let observed_bytes = match observed {
                yosoi::LossExtent::Known(value) => {
                    yosoi::MeasuredCount::Known(yosoi::ByteCount::new(*value))
                }
                yosoi::LossExtent::Unknown => yosoi::MeasuredCount::Unavailable {
                    reason: conversions::reason("voidcrawl.discarded-byte-extent-unavailable")?,
                },
            };
            let schema = match family {
                yosoi::BrowserStagingFamily::SourceRepresentation => {
                    spec.output_schemas().source_representation()
                }
                yosoi::BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
            }
            .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
            .clone();
            let reference = spec
                .identity_plan()
                .reference(family)
                .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
            let descriptor = yosoi::BrowserDiscardedArtifactDescriptor::new(
                reference,
                schema,
                producer.clone(),
                yosoi::MediaType::new(media_type)
                    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
                yosoi::ArtifactSensitivity::Sensitive,
                at,
                observed_bytes,
                derived_from,
            );
            return staged
                .with_discarded_descriptor(descriptor)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging);
        }
        return Ok(staged);
    };
    let shared_bytes = outcome
        .shared_bytes()
        .ok_or(VoidCrawlAdapterError::InvalidStaging)?;
    let retained = u64::try_from(bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let extent = match outcome.parts() {
        yosoi::BrowserStagingParts::Complete { .. } => yosoi::ArtifactByteExtent::Complete {
            retained_bytes: yosoi::ByteCount::new(retained),
        },
        yosoi::BrowserStagingParts::Partial { observed, loss, .. }
        | yosoi::BrowserStagingParts::Truncated { observed, loss, .. } => {
            let complete = match loss {
                yosoi::LossExtent::Known(_) => {
                    yosoi::MeasuredCount::Known(yosoi::ByteCount::new(*observed))
                }
                yosoi::LossExtent::Unknown => yosoi::MeasuredCount::Unavailable {
                    reason: conversions::reason("voidcrawl.bytes.complete-size-unknown")?,
                },
            };
            yosoi::ArtifactByteExtent::truncated(yosoi::ByteCount::new(retained), complete)
                .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?
        }
        _ => return Err(VoidCrawlAdapterError::InvalidStaging),
    };
    let schema = match family {
        yosoi::BrowserStagingFamily::SourceRepresentation => {
            spec.output_schemas().source_representation()
        }
        yosoi::BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
    }
    .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
    .clone();
    let reference = spec
        .identity_plan()
        .reference(family)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let envelope = yosoi::StagedBrowserArtifactEnvelope::new(
        reference,
        schema,
        producer.clone(),
        yosoi::MediaType::new(media_type).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        yosoi_types::Sha256Digest::digest(bytes),
        extent,
        yosoi::ArtifactSensitivity::Sensitive,
        at,
        shared_bytes,
        derived_from,
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    slot(family, outcome)?
        .with_envelope(envelope)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub(super) fn structured_slot(
    spec: &yosoi::ResolvedBrowserCaptureSpec,
    family: yosoi::BrowserStagingFamily,
    outcome: yosoi::ArtifactStagingOutcome,
    at: yosoi::CaptureOffset,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    let yosoi::BrowserStagingParts::Structured { evidence, .. } = outcome.parts() else {
        return Err(VoidCrawlAdapterError::InvalidStaging);
    };
    let bytes = evidence
        .to_canonical_json()
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    let extent = yosoi::ArtifactByteExtent::Complete {
        retained_bytes: yosoi::ByteCount::new(
            u64::try_from(bytes.len()).map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        ),
    };
    let schema = match family {
        yosoi::BrowserStagingFamily::Artifact(value) => spec.output_schemas().get(value),
        yosoi::BrowserStagingFamily::SourceRepresentation => None,
    }
    .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?
    .clone();
    let reference = spec
        .identity_plan()
        .reference(family)
        .ok_or(VoidCrawlAdapterError::InvalidResolvedSpec)?;
    let envelope = yosoi::StagedBrowserArtifactEnvelope::new(
        reference,
        schema,
        spec.producer().clone(),
        yosoi::MediaType::new("application/json")
            .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?,
        yosoi_types::Sha256Digest::digest(&bytes),
        extent,
        yosoi::ArtifactSensitivity::Sensitive,
        at,
        Arc::from(bytes),
        Vec::new(),
    )
    .map_err(|_| VoidCrawlAdapterError::InvalidStaging)?;
    slot(family, outcome)?
        .with_envelope(envelope)
        .map_err(|_| VoidCrawlAdapterError::InvalidStaging)
}

pub(super) fn unrequested(
    family: yosoi::BrowserStagingFamily,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    slot(family, yosoi::ArtifactStagingOutcome::unrequested())
}
pub(super) fn missing(
    family: yosoi::BrowserStagingFamily,
    requested: yosoi::ArtifactRequest,
) -> Result<yosoi::BrowserStagingSlot, VoidCrawlAdapterError> {
    if requested == yosoi::ArtifactRequest::NotRequested {
        unrequested(family)
    } else {
        slot(
            family,
            yosoi::ArtifactStagingOutcome::failed(conversions::reason(
                "voidcrawl.capture.stopped-before-snapshot",
            )?),
        )
    }
}
