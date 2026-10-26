//! Portable Surface evidence values. Runtime authority is deliberately absent.

use crate::{archive::ArchiveRefError, automation_record::OperationStatus};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::collections::BTreeSet;

use super::{ArchiveLimits, Limits, Surface, SurfaceError};
use crate::{
    archive::DocumentArchiveRef,
    automation_record::AutomationRecord,
    documents::{Document, DocumentId, DocumentProfile},
    locators::Plan,
};

/// Interpreter needed to reconstruct retained evidence, without live authority.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum SourceInterpretation {
    /// One of the six SDK document representations, preserving its profile.
    #[default]
    Document,
    /// PNG/JPEG pixels with the exact original tiling policy.
    Image {
        /// Smallest automatically indexed region size in pixels.
        tile_side: u32,
    },
    /// A bounded manifest of named document/image views; never nested bundles.
    Bundle,
}

#[derive(Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
struct Bundle {
    scope: String,
    views: Vec<(String, ArchivedSource)>,
}

/// Typed reference selecting a Surface outcome through the existing Archive API.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct OutcomeRef {
    /// Exact immutable Document storing this self-contained outcome.
    pub document: DocumentArchiveRef,
    /// Logical Surface outcome schema required on read.
    pub version: u32,
}

/// Exact retained source bytes and their document interpretation.
#[derive(Clone, Debug, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct ArchivedSource {
    /// Interpreter for these bytes; raw evidence envelopes use `Document`.
    #[serde(default)]
    pub interpretation: SourceInterpretation,
    /// Identifier within this outcome, independent of a local Archive path.
    pub key: String,
    /// Original SDK document identity.
    pub document: DocumentId,
    /// Original representation and schema profile, including snapshot epoch.
    pub profile: DocumentProfile,
    /// SHA-256 of the decoded original bytes.
    pub sha256: String,
    /// Base64 transport of the original bytes, not an address of an external file.
    pub content_base64: String,
    /// Optional exact index identity when this source was prepared as a Surface.
    pub surface: Option<String>,
}

impl ArchivedSource {
    /// Freezes an SDK document and optionally binds its prepared interpretation.
    pub fn new(key: impl Into<String>, document: &Document, surface: Option<&Surface>) -> Self {
        Self {
            interpretation: SourceInterpretation::Document,
            key: key.into(),
            document: document.id().clone(),
            profile: document.profile(),
            sha256: format!("{:x}", Sha256::digest(document.bytes())),
            content_base64: STANDARD.encode(document.bytes()),
            surface: surface.map(|value| value.identity().to_owned()),
        }
    }

    /// Retains a prepared document, image or combined observation with its exact identity.
    pub fn capture(key: impl Into<String>, surface: &Surface) -> Result<Self, SurfaceError> {
        let mut source = match &surface.data.original {
            Some(super::Original::Document { id, profile }) => {
                let document = Document::from_profile(
                    id.clone(),
                    *profile,
                    surface.data.source.as_bytes().to_vec(),
                )
                .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
                Self::new(key, &document, Some(surface))
            }
            #[cfg(any(feature = "browser", feature = "surface-images"))]
            Some(super::Original::Image { bytes, tile_side }) => {
                let document = Document::text("surface-image", bytes.clone())
                    .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
                let mut source = Self::new(key, &document, Some(surface));
                source.interpretation = SourceInterpretation::Image {
                    tile_side: *tile_side,
                };
                source
            }
            None => {
                let scope = surface
                    .data
                    .nodes
                    .first()
                    .ok_or(SurfaceError::Unknown)?
                    .text
                    .clone();
                let views = surface
                    .data
                    .views
                    .iter()
                    .map(|(name, view)| Ok((name.clone(), Self::capture(name, view)?)))
                    .collect::<Result<Vec<_>, SurfaceError>>()?;
                let bytes = serde_json::to_vec(&Bundle { scope, views })
                    .map_err(|error| SurfaceError::Parse(error.to_string()))?;
                let document = Document::json("surface-bundle", bytes)
                    .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
                let mut source = Self::new(key, &document, Some(surface));
                source.interpretation = SourceInterpretation::Bundle;
                source
            }
        };
        source.surface = Some(surface.identity().to_owned());
        Ok(source)
    }

    /// Verifies and reconstructs exact bytes without fetching the original source.
    pub fn restore(&self, maximum: u64) -> Result<Document, SurfaceError> {
        let bound = maximum
            .checked_add(2)
            .and_then(|value| value.checked_div(3))
            .and_then(|value| value.checked_mul(4))
            .ok_or(SurfaceError::Limit("source encoding arithmetic"))?;
        if u64::try_from(self.content_base64.len())
            .map_err(|_| SurfaceError::Limit("source size"))?
            > bound
        {
            return Err(SurfaceError::Limit("archived source bytes"));
        }
        let bytes = STANDARD
            .decode(&self.content_base64)
            .map_err(|error| SurfaceError::Parse(error.to_string()))?;
        if u64::try_from(bytes.len()).map_err(|_| SurfaceError::Limit("source size"))? > maximum {
            return Err(SurfaceError::Limit("archived source bytes"));
        }
        if format!("{:x}", Sha256::digest(&bytes)) != self.sha256 {
            return Err(SurfaceError::Invalid(
                "archived source digest mismatch".into(),
            ));
        }
        Document::from_profile(self.document.clone(), self.profile, bytes)
            .map_err(|error| SurfaceError::Invalid(error.to_string()))
    }

    /// Restores the index and rejects an interpretation whose identity changed.
    pub fn restore_surface(&self, limits: Limits) -> Result<Surface, SurfaceError> {
        let document = self.restore(
            u64::try_from(limits.input_bytes).map_err(|_| SurfaceError::Limit("input limit"))?,
        )?;
        let surface = match self.interpretation {
            SourceInterpretation::Document => Surface::with_limits(&document, limits)?,
            SourceInterpretation::Image { tile_side } => {
                #[cfg(any(feature = "browser", feature = "surface-images"))]
                {
                    Surface::from_image(document.bytes(), tile_side, limits)?
                }
                #[cfg(not(any(feature = "browser", feature = "surface-images")))]
                {
                    let _ = tile_side;
                    return Err(SurfaceError::Invalid(
                        "image restoration requires surface-images".into(),
                    ));
                }
            }
            SourceInterpretation::Bundle => {
                let bundle: Bundle = serde_json::from_slice(document.bytes())
                    .map_err(|error| SurfaceError::Parse(error.to_string()))?;
                if bundle.views.is_empty()
                    || bundle.views.len() > 16
                    || bundle.views.iter().any(|(_, source)| {
                        matches!(source.interpretation, SourceInterpretation::Bundle)
                    })
                {
                    return Err(SurfaceError::Invalid(
                        "invalid or nested archived bundle".into(),
                    ));
                }
                let views = bundle
                    .views
                    .iter()
                    .map(|(name, source)| Ok((name.clone(), source.restore_surface(limits)?)))
                    .collect::<Result<Vec<_>, SurfaceError>>()?;
                Surface::combine(&bundle.scope, views, limits)?
            }
        };
        if self.surface.as_deref() != Some(surface.identity()) {
            return Err(SurfaceError::Invalid(
                "archived Surface interpretation mismatch".into(),
            ));
        }
        Ok(surface)
    }
}

/// A self-contained Surface execution suitable for normal Archive persistence.
/// Captures and selectors are data; no live session, cursor or action lease is stored.
#[derive(Clone, Debug, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Outcome {
    /// Logical portable Surface outcome version.
    pub version: u32,
    /// Original ordered observations and operation certainty.
    pub record: AutomationRecord,
    /// Retained original documents and materialized evidence envelopes.
    pub sources: Vec<ArchivedSource>,
    /// Existing compiled locator Plans, retained without a new selector language.
    pub plans: Vec<Plan>,
    /// Whether logical finalization was observed; external cleanup has its own receipts.
    pub sealed: bool,
    /// Whether all evidence required by the selected archive policy was retained.
    pub complete: bool,
    /// Limits governing this retained outcome.
    pub limits: ArchiveLimits,
}

impl Outcome {
    /// Starts an empty portable outcome for an adapter-managed run.
    /// Session users normally obtain this value through `Session::outcome`.
    pub fn new(id: impl Into<String>, limits: ArchiveLimits) -> Result<Self, SurfaceError> {
        limits.validate()?;
        Ok(Self {
            version: 1,
            record: AutomationRecord::new(id, Vec::new(), Vec::new())
                .map_err(|error| SurfaceError::Invalid(error.to_string()))?,
            sources: Vec::new(),
            plans: Vec::new(),
            sealed: false,
            complete: true,
            limits,
        })
    }

    /// Consumes this value and returns it with one exact retained source.
    /// Equal keys must have equal bytes and interpretation. Invalid, conflicting,
    /// excessive or sealed inputs return an error. Clone first to retain the old
    /// value on failure. Live runtime collectors preserve partial outcomes separately.
    pub fn with_source(mut self, source: ArchivedSource) -> Result<Self, SurfaceError> {
        self.retain(source)?;
        Ok(self)
    }

    pub(super) fn retain(&mut self, source: ArchivedSource) -> Result<(), SurfaceError> {
        let result = self.retain_checked(source);
        if result.is_err() {
            self.complete = false;
        }
        result
    }

    fn retain_checked(&mut self, source: ArchivedSource) -> Result<(), SurfaceError> {
        if self.sealed {
            return Err(SurfaceError::Invalid("outcome is sealed".into()));
        }
        if let Some(prior) = self.sources.iter().find(|prior| prior.key == source.key) {
            if prior == &source {
                return Ok(());
            }
            return Err(SurfaceError::Invalid(
                "conflicting retained source key".into(),
            ));
        }
        self.sources.push(source);
        if let Err(error) = self.validate() {
            self.sources.pop();
            return Err(error);
        }
        Ok(())
    }

    pub(super) fn receipt(
        &mut self,
        kind: &str,
        status: OperationStatus,
        result: serde_json::Value,
    ) {
        use crate::automation_record::OperationReceipt;
        if self.record.operations().len() >= self.limits.operations {
            self.complete = false;
            return;
        }
        let receipt = OperationReceipt {
            browser: None,
            id: format!("{}:{}", self.record.id(), self.record.operations().len()),
            kind: kind.into(),
            status,
            result: Some(result),
            observation: None,
            error: None,
        };
        if self.record.push_operation(receipt).is_err() {
            self.complete = false;
        }
    }

    /// Validates schema, original record, bounded source bytes and compiled Plans.
    pub fn validate(&self) -> Result<(), SurfaceError> {
        self.limits.validate()?;
        if self.version != 1 {
            return Err(SurfaceError::Invalid(
                "unsupported Surface outcome version".into(),
            ));
        }
        self.record
            .validate()
            .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
        if self.plans.len() > self.limits.operations
            || self.sources.len() > self.limits.observations
            || self.record.operations().len() > self.limits.operations
        {
            return Err(SurfaceError::Limit("outcome items"));
        }
        // Plan deserialization runs the existing compiled-plan validation.
        for plan in &self.plans {
            let encoded =
                serde_json::to_vec(plan).map_err(|error| SurfaceError::Parse(error.to_string()))?;
            let _: Plan = serde_json::from_slice(&encoded)
                .map_err(|error| SurfaceError::Invalid(error.to_string()))?;
        }
        let mut total = 0_u64;
        let mut keys = BTreeSet::new();
        for source in &self.sources {
            if source.key.is_empty() || !keys.insert(&source.key) {
                return Err(SurfaceError::Invalid(
                    "outcome source keys must be nonempty and unique".into(),
                ));
            }
            let document = source.restore(self.limits.bytes)?;
            total = total
                .checked_add(document.byte_len())
                .ok_or(SurfaceError::Limit("outcome byte arithmetic"))?;
            if total > self.limits.bytes {
                return Err(SurfaceError::Limit("outcome evidence bytes"));
            }
        }
        for receipt in self.record.operations() {
            if !matches!(
                receipt.kind.as_str(),
                "surface.capture" | "surface.video.source" | "surface.video.frame"
            ) {
                continue;
            }
            let key = receipt
                .result
                .as_ref()
                .and_then(|value| value.get("document"))
                .and_then(serde_json::Value::as_str)
                .ok_or_else(|| {
                    SurfaceError::Invalid("missing retained document reference".into())
                })?;
            let _: DocumentArchiveRef = key
                .parse()
                .map_err(|error: ArchiveRefError| SurfaceError::Invalid(error.to_string()))?;
            let source = self.sources.iter().find(|source| source.key == key);
            if self.complete && source.is_none() {
                return Err(SurfaceError::Invalid(
                    "complete outcome is missing required document evidence".into(),
                ));
            }
            if let Some(source) = source
                && receipt.kind == "surface.capture"
                && receipt
                    .result
                    .as_ref()
                    .and_then(|value| value.get("surface"))
                    .and_then(serde_json::Value::as_str)
                    != source.surface.as_deref()
            {
                return Err(SurfaceError::Invalid(
                    "capture descriptor differs from retained interpretation".into(),
                ));
            }
        }
        Ok(())
    }

    /// Restores one exact retained Surface without granting live authority.
    pub fn surface(&self, key: &str, limits: Limits) -> Result<Surface, SurfaceError> {
        self.sources
            .iter()
            .find(|source| source.key == key)
            .ok_or(SurfaceError::Unknown)?
            .restore_surface(limits)
    }
}
