#![allow(clippy::missing_const_for_fn)]
mod payload;

use super::facts::BrowserAdapterOutputError;
use crate::browser_spec::{BrowserByteDomain, byte_domain_for_staging};
use crate::{
    ArtifactByteExtent, ArtifactSensitivity, ByteCount, CaptureOffset, MeasuredCount, MediaType,
    WebArtifactFamily,
};
use std::{fmt, sync::Arc};
use thiserror::Error;
pub use yosoi_types::LossExtent;
use yosoi_types::{Producer, ReasonCode, Schema};

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserByteLayer {
    DecodedResponseBody,
    DecodedSourceUtf8,
    SourceRepresentation,
    RenderedDomUtf8,
    AccessibilityTreeUtf8,
    Png,
    RuntimeDiagnosticsUtf8,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub enum BrowserStagingFamily {
    Artifact(WebArtifactFamily),
    SourceRepresentation,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserArtifactMapping {
    family: BrowserStagingFamily,
    layer: BrowserByteLayer,
    snapshot: Option<BrowserSnapshotObservation>,
    source_binding: Option<yosoi_types::Sha256Digest>,
}
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct BrowserSnapshotObservation {
    family: BrowserStagingFamily,
    pub scope: crate::BrowserDocumentScope,
    pub at: CaptureOffset,
    pub accessibility_nodes: Option<u32>,
    pub accessibility_depth: Option<i64>,
    pub accessibility_ignored_nodes_included: Option<bool>,
    pub visual: Option<crate::BrowserVisualFact>,
}
impl BrowserSnapshotObservation {
    const fn plain(
        family: WebArtifactFamily,
        scope: crate::BrowserDocumentScope,
        at: CaptureOffset,
    ) -> Self {
        Self {
            family: BrowserStagingFamily::Artifact(family),
            scope,
            at,
            accessibility_nodes: None,
            accessibility_depth: None,
            accessibility_ignored_nodes_included: None,
            visual: None,
        }
    }
    pub const fn source(scope: crate::BrowserDocumentScope, at: CaptureOffset) -> Self {
        Self::plain(WebArtifactFamily::Source, scope, at)
    }
    pub const fn rendered_dom(scope: crate::BrowserDocumentScope, at: CaptureOffset) -> Self {
        Self::plain(WebArtifactFamily::RenderedDom, scope, at)
    }
    pub const fn accessibility_tree(
        scope: crate::BrowserDocumentScope,
        at: CaptureOffset,
        nodes: u32,
    ) -> Self {
        Self::accessibility_tree_descriptor(scope, at, nodes, None, true)
    }
    pub const fn accessibility_tree_descriptor(
        scope: crate::BrowserDocumentScope,
        at: CaptureOffset,
        nodes: u32,
        depth: Option<i64>,
        ignored_nodes_included: bool,
    ) -> Self {
        Self {
            family: BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
            scope,
            at,
            accessibility_nodes: Some(nodes),
            accessibility_depth: depth,
            accessibility_ignored_nodes_included: Some(ignored_nodes_included),
            visual: None,
        }
    }
    pub const fn visual(scope: crate::BrowserDocumentScope, at: CaptureOffset) -> Self {
        Self::plain(WebArtifactFamily::Visual, scope, at)
    }
    pub const fn visual_fact(fact: crate::BrowserVisualFact) -> Self {
        Self {
            family: BrowserStagingFamily::Artifact(WebArtifactFamily::Visual),
            scope: fact.scope,
            at: fact.at,
            accessibility_nodes: None,
            accessibility_depth: None,
            accessibility_ignored_nodes_included: None,
            visual: Some(fact),
        }
    }
}
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
#[error("staging family and representation layer do not match")]
pub struct BrowserMappingError;
impl BrowserArtifactMapping {
    pub fn new(
        family: BrowserStagingFamily,
        layer: BrowserByteLayer,
    ) -> Result<Self, BrowserMappingError> {
        let valid = matches!(
            (family, layer),
            (
                BrowserStagingFamily::Artifact(WebArtifactFamily::Source),
                BrowserByteLayer::DecodedResponseBody
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::DecodedSource),
                BrowserByteLayer::DecodedSourceUtf8
            ) | (
                BrowserStagingFamily::SourceRepresentation,
                BrowserByteLayer::SourceRepresentation
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::RenderedDom),
                BrowserByteLayer::RenderedDomUtf8
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::AccessibilityTree),
                BrowserByteLayer::AccessibilityTreeUtf8
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::Visual),
                BrowserByteLayer::Png
            ) | (
                BrowserStagingFamily::Artifact(WebArtifactFamily::RuntimeDiagnostics),
                BrowserByteLayer::RuntimeDiagnosticsUtf8
            )
        );
        if !valid {
            return Err(BrowserMappingError);
        }
        Ok(Self {
            family,
            layer,
            snapshot: None,
            source_binding: None,
        })
    }
    pub fn derived_from_source(mut self, source: &[u8]) -> Self {
        self.source_binding = Some(yosoi_types::Sha256Digest::digest(source));
        self
    }
    pub const fn source_binding(self) -> Option<yosoi_types::Sha256Digest> {
        self.source_binding
    }
    pub fn with_snapshot(
        mut self,
        snapshot: BrowserSnapshotObservation,
    ) -> Result<Self, BrowserMappingError> {
        if snapshot.family != self.family
            || matches!(self.family, BrowserStagingFamily::SourceRepresentation)
        {
            return Err(BrowserMappingError);
        }
        self.snapshot = Some(snapshot);
        Ok(self)
    }
    pub const fn snapshot(self) -> Option<BrowserSnapshotObservation> {
        self.snapshot
    }
    pub const fn family(self) -> BrowserStagingFamily {
        self.family
    }
    pub const fn layer(self) -> BrowserByteLayer {
        self.layer
    }
}
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
        evidence: crate::BrowserStructuredEvidence,
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
    envelope: Option<crate::StagedBrowserArtifactEnvelope>,
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
        envelope: crate::StagedBrowserArtifactEnvelope,
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
        Option<crate::StagedBrowserArtifactEnvelope>,
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
    pub const fn envelope(&self) -> Option<&crate::StagedBrowserArtifactEnvelope> {
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
