use crate::internal::types as yosoi_types;
use crate::internal::web_capture as yosoi_web_capture;

use super::{
    ArtifactByteExtent, ArtifactSensitivity, ArtifactStagingOutcome, BrowserAdapterOutputError,
    BrowserStagingFamily, BrowserStagingParts, ByteCount, CaptureOffset, LossExtent, MeasuredCount,
    MediaType, WebArtifactFamily,
};
use crate::internal::types::{Producer, Schema};
use crate::internal::web_capture::browser_spec::byte_domain_for_staging;
use thiserror::Error;
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserStagingAccounting {
    observed: u64,
    retained: u64,
    lost: LossExtent,
}
impl BrowserStagingAccounting {
    pub const fn observed(self) -> u64 {
        self.observed
    }
    pub const fn retained(self) -> u64 {
        self.retained
    }
    pub const fn lost(self) -> LossExtent {
        self.lost
    }
    fn checked_add(self, other: Self) -> Result<Self, BrowserAdapterOutputError> {
        let lost = match (self.lost, other.lost) {
            (LossExtent::Known(a), LossExtent::Known(b)) => LossExtent::Known(
                a.checked_add(b)
                    .ok_or(BrowserAdapterOutputError::Overflow)?,
            ),
            _ => LossExtent::Unknown,
        };
        Ok(Self {
            observed: self
                .observed
                .checked_add(other.observed)
                .ok_or(BrowserAdapterOutputError::Overflow)?,
            retained: self
                .retained
                .checked_add(other.retained)
                .ok_or(BrowserAdapterOutputError::Overflow)?,
            lost,
        })
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserDiscardedArtifactDescriptor {
    reference: yosoi_types::ArtifactRef,
    schema: Schema,
    producer: Producer,
    media_type: MediaType,
    sensitivity: ArtifactSensitivity,
    generated_at: CaptureOffset,
    observed_extent: ArtifactByteExtent,
    derived_from: Vec<yosoi_types::ArtifactRef>,
}
impl BrowserDiscardedArtifactDescriptor {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        reference: yosoi_types::ArtifactRef,
        schema: Schema,
        producer: Producer,
        media_type: MediaType,
        sensitivity: ArtifactSensitivity,
        generated_at: CaptureOffset,
        observed_bytes: MeasuredCount<ByteCount>,
        derived_from: Vec<yosoi_types::ArtifactRef>,
    ) -> Self {
        Self {
            reference,
            schema,
            producer,
            media_type,
            sensitivity,
            generated_at,
            observed_extent: ArtifactByteExtent::Discarded { observed_bytes },
            derived_from,
        }
    }
    pub const fn reference(&self) -> yosoi_types::ArtifactRef {
        self.reference
    }
    pub const fn schema(&self) -> &Schema {
        &self.schema
    }
    pub const fn producer(&self) -> &Producer {
        &self.producer
    }
    pub const fn media_type(&self) -> &MediaType {
        &self.media_type
    }
    pub const fn sensitivity(&self) -> ArtifactSensitivity {
        self.sensitivity
    }
    pub const fn generated_at(&self) -> CaptureOffset {
        self.generated_at
    }
    pub const fn observed_extent(&self) -> &ArtifactByteExtent {
        &self.observed_extent
    }
    pub fn derived_from(&self) -> &[yosoi_types::ArtifactRef] {
        &self.derived_from
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserStagingSlot {
    family: BrowserStagingFamily,
    outcome: ArtifactStagingOutcome,
    envelope: Option<yosoi_web_capture::StagedBrowserArtifactEnvelope>,
    discarded: Option<BrowserDiscardedArtifactDescriptor>,
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("staging mapping does not match its named slot")]
pub struct StagingSlotError;
impl BrowserStagingSlot {
    pub fn new(
        family: BrowserStagingFamily,
        outcome: ArtifactStagingOutcome,
    ) -> Result<Self, StagingSlotError> {
        if let BrowserStagingParts::Structured { evidence, .. } = outcome.parts()
            && family != BrowserStagingFamily::Artifact(evidence.family())
        {
            return Err(StagingSlotError);
        }
        if outcome.mapping().is_some_and(|m| m.family() != family) {
            return Err(StagingSlotError);
        }
        if let BrowserStagingParts::Discarded { domain, .. } = outcome.parts()
            && byte_domain_for_staging(family) != Some(*domain)
        {
            return Err(StagingSlotError);
        }
        Ok(Self {
            family,
            outcome,
            envelope: None,
            discarded: None,
        })
    }
    pub fn with_envelope(
        mut self,
        envelope: yosoi_web_capture::StagedBrowserArtifactEnvelope,
    ) -> Result<Self, StagingSlotError> {
        let structured = matches!(self.outcome.parts(), BrowserStagingParts::Structured { .. });
        if self
            .outcome
            .bytes()
            .is_some_and(|bytes| bytes != envelope.bytes())
            || (self.outcome.bytes().is_none() && !structured)
        {
            return Err(StagingSlotError);
        }
        self.envelope = Some(envelope);
        Ok(self)
    }
    pub fn with_discarded_descriptor(
        mut self,
        descriptor: BrowserDiscardedArtifactDescriptor,
    ) -> Result<Self, StagingSlotError> {
        if !matches!(self.outcome.parts(), BrowserStagingParts::Discarded { .. })
            || self.envelope.is_some()
        {
            return Err(StagingSlotError);
        }
        self.discarded = Some(descriptor);
        Ok(self)
    }
    pub fn into_parts(self) -> (BrowserStagingFamily, ArtifactStagingOutcome) {
        (self.family, self.outcome)
    }
    pub fn into_staged_parts(
        self,
    ) -> (
        BrowserStagingFamily,
        ArtifactStagingOutcome,
        Option<yosoi_web_capture::StagedBrowserArtifactEnvelope>,
        Option<BrowserDiscardedArtifactDescriptor>,
    ) {
        (self.family, self.outcome, self.envelope, self.discarded)
    }
    pub const fn family(&self) -> BrowserStagingFamily {
        self.family
    }
    pub const fn outcome(&self) -> &ArtifactStagingOutcome {
        &self.outcome
    }
    pub const fn envelope(&self) -> Option<&yosoi_web_capture::StagedBrowserArtifactEnvelope> {
        self.envelope.as_ref()
    }
    pub const fn discarded_descriptor(&self) -> Option<&BrowserDiscardedArtifactDescriptor> {
        self.discarded.as_ref()
    }
}
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct BrowserArtifactStaging {
    slots: [BrowserStagingSlot; 11],
}
impl BrowserArtifactStaging {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source: BrowserStagingSlot,
        source_representation: BrowserStagingSlot,
        rendered_dom: BrowserStagingSlot,
        accessibility_tree: BrowserStagingSlot,
        network: BrowserStagingSlot,
        cookies: BrowserStagingSlot,
        storage: BrowserStagingSlot,
        layout: BrowserStagingSlot,
        visual: BrowserStagingSlot,
        runtime_diagnostics: BrowserStagingSlot,
    ) -> Result<Self, StagingSlotError> {
        let decoded_source = BrowserStagingSlot::new(
            BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
            ArtifactStagingOutcome::unrequested(),
        )?;
        let slots = [
            source,
            source_representation,
            decoded_source,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        ];
        let expected = [
            BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
            BrowserStagingFamily::SourceRepresentation,
            BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
            BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
            BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
            BrowserStagingFamily::Artifact(WebArtifactFamily::Network),
            BrowserStagingFamily::Artifact(WebArtifactFamily::Cookies),
            BrowserStagingFamily::Artifact(WebArtifactFamily::Storage),
            BrowserStagingFamily::Artifact(WebArtifactFamily::Layout),
            BrowserStagingFamily::Artifact(WebArtifactFamily::Visual),
            BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics),
        ];
        if slots.iter().zip(expected).any(|(s, e)| s.family() != e) {
            return Err(StagingSlotError);
        }
        Ok(Self { slots })
    }
    pub fn with_decoded_source(
        mut self,
        decoded_source: BrowserStagingSlot,
    ) -> Result<Self, StagingSlotError> {
        if decoded_source.family()
            != BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource)
        {
            return Err(StagingSlotError);
        }
        let [
            source,
            source_representation,
            _,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        ] = self.slots;
        self.slots = [
            source,
            source_representation,
            decoded_source,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        ];
        Ok(self)
    }
    pub fn accounting(&self) -> Result<BrowserStagingAccounting, BrowserAdapterOutputError> {
        self.slots.iter().try_fold(
            BrowserStagingAccounting {
                observed: 0,
                retained: 0,
                lost: LossExtent::Known(0),
            },
            |sum, slot| sum.checked_add(slot.outcome().accounting()?),
        )
    }
    pub fn into_parts(self) -> [BrowserStagingSlot; 11] {
        self.slots
    }
    pub fn slots(&self) -> &[BrowserStagingSlot] {
        &self.slots
    }
    pub fn source(&self) -> Option<&BrowserStagingSlot> {
        self.slots
            .iter()
            .find(|slot| slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::Source))
    }
    pub fn source_representation(&self) -> Option<&BrowserStagingSlot> {
        self.slots
            .iter()
            .find(|slot| slot.family() == BrowserStagingFamily::SourceRepresentation)
    }
    pub fn decoded_source(&self) -> Option<&BrowserStagingSlot> {
        self.slots.iter().find(|slot| {
            slot.family() == BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource)
        })
    }
}

impl ArtifactStagingOutcome {
    pub fn accounting(&self) -> Result<BrowserStagingAccounting, BrowserAdapterOutputError> {
        let retained = self
            .retained()
            .map_err(|_| BrowserAdapterOutputError::Overflow)?;
        let (observed, lost) = match &self.data {
            BrowserStagingParts::Complete { observed, .. } => (*observed, LossExtent::Known(0)),
            BrowserStagingParts::Partial { observed, loss, .. }
            | BrowserStagingParts::Truncated { observed, loss, .. } => (*observed, *loss),
            BrowserStagingParts::Discarded {
                observed: LossExtent::Known(value),
                ..
            } => (*value, LossExtent::Known(*value)),
            BrowserStagingParts::Discarded {
                observed: LossExtent::Unknown,
                ..
            } => (0, LossExtent::Unknown),
            _ => (0, LossExtent::Known(0)),
        };
        Ok(BrowserStagingAccounting {
            observed,
            retained,
            lost,
        })
    }
}
