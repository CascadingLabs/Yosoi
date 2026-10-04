use chrono::{DateTime, TimeDelta, Utc};
use yosoi_types::{ArtifactAvailability, ArtifactRecord, Provenance, ReasonCode};

use crate::{
    ArtifactByteExtent, ArtifactCollection, ArtifactFamilyResult, ArtifactStagingOutcome,
    BrowserArtifactContext, BrowserDiscardedArtifactDescriptor, BrowserStagingFamily,
    BrowserStagingParts, BrowserStagingSlot, BrowserStructuredEvidence, ByteCount, LossExtent,
    MeasuredCount, SourceArtifactRef, SourceRepresentationArtifact, StagedBrowserArtifactEnvelope,
    WebArtifactFamily, WebArtifactMetadata,
};

use super::BrowserFinalizationError;

pub(super) fn family_result<T>(
    slot: Option<BrowserStagingSlot>,
    wrap: fn(WebArtifactMetadata) -> T,
    started_at: DateTime<Utc>,
) -> Result<ArtifactFamilyResult<T>, BrowserFinalizationError> {
    let slot = slot.ok_or(BrowserFinalizationError::Invariant("missing staging slot"))?;
    let (family, outcome, envelope, discarded) = slot.into_staged_parts();
    let browser_context = raw_browser_context(family, &outcome);
    match outcome.into_parts() {
        BrowserStagingParts::Unrequested => Ok(ArtifactFamilyResult::NotRequested),
        BrowserStagingParts::Complete { .. }
        | BrowserStagingParts::Structured { reason: None, .. } => {
            retained(envelope, wrap, None, browser_context, started_at)
        }
        BrowserStagingParts::Partial { reason, .. }
        | BrowserStagingParts::Truncated { reason, .. }
        | BrowserStagingParts::Structured {
            reason: Some(reason),
            ..
        } => retained(envelope, wrap, Some(reason), browser_context, started_at),
        BrowserStagingParts::Discarded { reason, .. } => {
            discarded_result(discarded, wrap, reason, started_at)
        }
        BrowserStagingParts::Unavailable(reason) => {
            Ok(ArtifactFamilyResult::Unavailable { reason })
        }
        BrowserStagingParts::Failed(reason) => Ok(ArtifactFamilyResult::Failed { reason }),
        BrowserStagingParts::Disabled(reason) => {
            Ok(ArtifactFamilyResult::OmittedByPolicy { reason })
        }
        BrowserStagingParts::Unsupported(reason) => {
            Ok(ArtifactFamilyResult::Unsupported { reason })
        }
    }
}

fn raw_browser_context(
    family: BrowserStagingFamily,
    outcome: &ArtifactStagingOutcome,
) -> Option<BrowserArtifactContext> {
    if family == BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree)
        && let BrowserStagingParts::Structured {
            evidence: BrowserStructuredEvidence::Accessibility(accessibility),
            ..
        } = outcome.parts()
    {
        return Some(BrowserArtifactContext::DocumentSnapshot {
            scope: accessibility.scope,
            captured_at: accessibility.at,
        });
    }
    if family == BrowserStagingFamily::Artifact(WebArtifactFamily::Layout)
        && let BrowserStagingParts::Structured {
            evidence: BrowserStructuredEvidence::Layout(layout),
            ..
        } = outcome.parts()
    {
        return Some(BrowserArtifactContext::DocumentSnapshot {
            scope: layout.scope,
            captured_at: layout.at,
        });
    }
    let snapshot = outcome.mapping()?.snapshot()?;
    match family {
        BrowserStagingFamily::Artifact(
            WebArtifactFamily::Source
            | WebArtifactFamily::RenderedDom
            | WebArtifactFamily::AccessibilityTree,
        ) => Some(BrowserArtifactContext::DocumentSnapshot {
            scope: snapshot.scope,
            captured_at: snapshot.at,
        }),
        BrowserStagingFamily::Artifact(WebArtifactFamily::Visual) => {
            snapshot.visual.map(BrowserArtifactContext::Visual)
        }
        _ => None,
    }
}

fn discarded_result<T>(
    descriptor: Option<BrowserDiscardedArtifactDescriptor>,
    wrap: fn(WebArtifactMetadata) -> T,
    reason: ReasonCode,
    started_at: DateTime<Utc>,
) -> Result<ArtifactFamilyResult<T>, BrowserFinalizationError> {
    let descriptor = descriptor.ok_or(BrowserFinalizationError::DiscardedMetadataUnavailable)?;
    let generated_at = offset_time(started_at, descriptor.generated_at().as_microseconds())?;
    let provenance = Provenance::new(
        descriptor.reference().activity_id(),
        descriptor.producer().clone(),
        descriptor.schema().clone(),
        generated_at,
        descriptor.derived_from().to_vec(),
    );
    let record = ArtifactRecord::new(
        descriptor.reference().artifact_id(),
        None,
        ArtifactAvailability::Discarded,
        Some(reason.clone()),
        provenance,
    )
    .map_err(|_| BrowserFinalizationError::Invariant("discarded artifact record"))?;
    let metadata = WebArtifactMetadata::new(
        record,
        descriptor.media_type().clone(),
        descriptor.observed_extent().clone(),
        descriptor.sensitivity(),
    )
    .map_err(|_| BrowserFinalizationError::Invariant("discarded artifact metadata"))?;
    let artifacts = ArtifactCollection::new(vec![wrap(metadata)])
        .map_err(|_| BrowserFinalizationError::Invariant("artifact collection"))?;
    Ok(ArtifactFamilyResult::Partial { artifacts, reason })
}

fn retained<T>(
    envelope: Option<StagedBrowserArtifactEnvelope>,
    wrap: fn(WebArtifactMetadata) -> T,
    reason: Option<ReasonCode>,
    browser_context: Option<BrowserArtifactContext>,
    started_at: DateTime<Utc>,
) -> Result<ArtifactFamilyResult<T>, BrowserFinalizationError> {
    let envelope = envelope.ok_or(BrowserFinalizationError::Invariant(
        "retained staging envelope",
    ))?;
    let metadata = metadata(&envelope, reason.clone(), browser_context, started_at)?;
    let artifacts = ArtifactCollection::new(vec![wrap(metadata)])
        .map_err(|_| BrowserFinalizationError::Invariant("artifact collection"))?;
    Ok(match reason {
        Some(reason) => ArtifactFamilyResult::Partial { artifacts, reason },
        None => ArtifactFamilyResult::Complete { artifacts },
    })
}

pub(super) fn source_representation_result(
    slot: Option<BrowserStagingSlot>,
    started_at: DateTime<Utc>,
) -> Result<ArtifactFamilyResult<SourceRepresentationArtifact>, BrowserFinalizationError> {
    let slot = slot.ok_or(BrowserFinalizationError::Invariant(
        "source representation slot",
    ))?;
    let (_, outcome, envelope, _discarded) = slot.into_staged_parts();
    match outcome.into_parts() {
        BrowserStagingParts::Complete { .. }
        | BrowserStagingParts::Structured { reason: None, .. } => {
            let envelope = envelope.ok_or(BrowserFinalizationError::Invariant(
                "source representation envelope",
            ))?;
            let source = envelope.derived_from().first().copied().ok_or(
                BrowserFinalizationError::Invariant("source representation lineage"),
            )?;
            let artifact = SourceRepresentationArtifact::try_from_source(
                metadata(&envelope, None, None, started_at)?,
                SourceArtifactRef::from_untyped(source),
            )
            .map_err(|_| BrowserFinalizationError::Invariant("source representation"))?;
            let artifacts = ArtifactCollection::new(vec![artifact])
                .map_err(|_| BrowserFinalizationError::Invariant("artifact collection"))?;
            Ok(ArtifactFamilyResult::Complete { artifacts })
        }
        BrowserStagingParts::Unrequested => Ok(ArtifactFamilyResult::NotRequested),
        BrowserStagingParts::Unavailable(reason) => {
            Ok(ArtifactFamilyResult::Unavailable { reason })
        }
        BrowserStagingParts::Failed(reason) => Ok(ArtifactFamilyResult::Failed { reason }),
        BrowserStagingParts::Disabled(reason) => {
            Ok(ArtifactFamilyResult::OmittedByPolicy { reason })
        }
        BrowserStagingParts::Unsupported(reason) => {
            Ok(ArtifactFamilyResult::Unsupported { reason })
        }
        _ => Err(BrowserFinalizationError::Invariant(
            "source representation outcome",
        )),
    }
}

pub(super) fn decoded_source_result(
    slot: Option<BrowserStagingSlot>,
    source_representation: Option<&crate::SourceRepresentationEvidence>,
    started_at: DateTime<Utc>,
) -> Result<ArtifactFamilyResult<crate::DecodedSourceArtifact>, BrowserFinalizationError> {
    let slot = slot.ok_or(BrowserFinalizationError::Invariant("decoded source slot"))?;
    let (_, outcome, envelope, _discarded) = slot.into_staged_parts();
    let reason = match outcome.into_parts() {
        BrowserStagingParts::Complete { .. } => None,
        BrowserStagingParts::Partial { reason, .. }
        | BrowserStagingParts::Truncated { reason, .. } => Some(reason),
        BrowserStagingParts::Unrequested => return Ok(ArtifactFamilyResult::NotRequested),
        BrowserStagingParts::Unavailable(reason) => {
            return Ok(ArtifactFamilyResult::Unavailable { reason });
        }
        BrowserStagingParts::Failed(reason) => {
            return Ok(ArtifactFamilyResult::Failed { reason });
        }
        BrowserStagingParts::Disabled(reason) => {
            return Ok(ArtifactFamilyResult::OmittedByPolicy { reason });
        }
        BrowserStagingParts::Unsupported(reason) => {
            return Ok(ArtifactFamilyResult::Unsupported { reason });
        }
        BrowserStagingParts::Structured { .. } | BrowserStagingParts::Discarded { .. } => {
            return Err(BrowserFinalizationError::Invariant(
                "decoded source outcome",
            ));
        }
    };
    let envelope = envelope.ok_or(BrowserFinalizationError::Invariant(
        "decoded source envelope",
    ))?;
    let evidence = source_representation.ok_or(BrowserFinalizationError::Invariant(
        "decoded source interpretation evidence",
    ))?;
    let decoded_reference = decoded_source_reference(evidence).ok_or(
        BrowserFinalizationError::Invariant("decoded source evidence reference"),
    )?;
    if decoded_reference != crate::DecodedSourceArtifactRef::from_untyped(envelope.reference()) {
        return Err(BrowserFinalizationError::Invariant(
            "decoded source evidence reference",
        ));
    }
    let source =
        envelope
            .derived_from()
            .first()
            .copied()
            .ok_or(BrowserFinalizationError::Invariant(
                "decoded source lineage",
            ))?;
    let interpretation = decoded_interpretation(evidence).ok_or(
        BrowserFinalizationError::Invariant("decoded source interpretation"),
    )?;
    let artifact = crate::DecodedSourceArtifact::try_from_source_with_interpretation(
        metadata(&envelope, reason.clone(), None, started_at)?,
        SourceArtifactRef::from_untyped(source),
        interpretation,
    )
    .map_err(|_| BrowserFinalizationError::Invariant("decoded source artifact"))?;
    let artifacts = ArtifactCollection::new(vec![artifact])
        .map_err(|_| BrowserFinalizationError::Invariant("artifact collection"))?;
    Ok(match reason {
        Some(reason) => ArtifactFamilyResult::Partial { artifacts, reason },
        None => ArtifactFamilyResult::Complete { artifacts },
    })
}

const fn decoded_source_reference(
    evidence: &crate::SourceRepresentationEvidence,
) -> Option<crate::DecodedSourceArtifactRef> {
    match evidence.decoding() {
        crate::DurableCharacterDecoding::Complete(view)
        | crate::DurableCharacterDecoding::OutputTruncated(view) => view.decoded_source(),
        crate::DurableCharacterDecoding::UnsupportedEncoding { .. }
        | crate::DurableCharacterDecoding::Undecodable { .. }
        | crate::DurableCharacterDecoding::NotApplicable { .. } => None,
    }
}

fn decoded_interpretation(
    evidence: &crate::SourceRepresentationEvidence,
) -> Option<crate::DecodedSourceInterpretation> {
    let view = match evidence.decoding() {
        crate::DurableCharacterDecoding::Complete(view)
        | crate::DurableCharacterDecoding::OutputTruncated(view) => view,
        crate::DurableCharacterDecoding::UnsupportedEncoding { .. }
        | crate::DurableCharacterDecoding::Undecodable { .. }
        | crate::DurableCharacterDecoding::NotApplicable { .. } => return None,
    };
    let source_extent = if view.source_truncated() {
        crate::DecodedExtent::Truncated
    } else {
        crate::DecodedExtent::Complete
    };
    let unicode_extent = if view.output_truncated() {
        crate::DecodedExtent::Truncated
    } else {
        crate::DecodedExtent::Complete
    };
    crate::DecodedSourceInterpretation::new(
        view.encoding(),
        view.basis(),
        view.replacements(),
        view.conflicts().to_vec(),
        source_extent,
        unicode_extent,
    )
    .ok()
}

fn metadata(
    envelope: &StagedBrowserArtifactEnvelope,
    reason: Option<ReasonCode>,
    browser_context: Option<BrowserArtifactContext>,
    started_at: DateTime<Utc>,
) -> Result<WebArtifactMetadata, BrowserFinalizationError> {
    let availability = if matches!(envelope.extent(), ArtifactByteExtent::Complete { .. }) {
        ArtifactAvailability::Retained
    } else {
        ArtifactAvailability::Truncated
    };
    let generated_at = offset_time(started_at, envelope.generated_at().as_microseconds())?;
    let provenance = Provenance::new(
        envelope.reference().activity_id(),
        envelope.producer().clone(),
        envelope.schema().clone(),
        generated_at,
        envelope.derived_from().to_vec(),
    );
    let availability_reason = if availability == ArtifactAvailability::Truncated {
        reason
    } else {
        None
    };
    let record = ArtifactRecord::new(
        envelope.reference().artifact_id(),
        Some(envelope.digest()),
        availability,
        availability_reason,
        provenance,
    )
    .map_err(|_| BrowserFinalizationError::Invariant("artifact record"))?;
    WebArtifactMetadata::new_with_browser_context(
        record,
        envelope.media_type().clone(),
        envelope.extent().clone(),
        envelope.sensitivity(),
        browser_context,
    )
    .map_err(|_| BrowserFinalizationError::Invariant("artifact metadata"))
}

fn offset_time(
    started_at: DateTime<Utc>,
    microseconds: u64,
) -> Result<DateTime<Utc>, BrowserFinalizationError> {
    let microseconds =
        i64::try_from(microseconds).map_err(|_| BrowserFinalizationError::InvalidWallClock)?;
    started_at
        .checked_add_signed(TimeDelta::microseconds(microseconds))
        .ok_or(BrowserFinalizationError::InvalidWallClock)
}

pub(super) fn loss_bytes(
    loss: LossExtent,
) -> Result<MeasuredCount<ByteCount>, BrowserFinalizationError> {
    Ok(match loss {
        LossExtent::Known(value) => MeasuredCount::Known(ByteCount::new(value)),
        LossExtent::Unknown => MeasuredCount::Unavailable {
            reason: super::termination::reason_code("browser.bytes.loss-unobserved")?,
        },
    })
}
