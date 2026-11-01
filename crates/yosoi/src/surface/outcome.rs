//! Portable Surface evidence values. Runtime authority is deliberately absent.

use crate::{archive::ArchiveRefError, automation_record::OperationStatus};
use base64::{Engine, engine::general_purpose::STANDARD};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{collections::BTreeSet, sync::Arc};

#[cfg(any(feature = "browser", feature = "surface-images"))]
use super::PixelArtifact;
use super::pixels::{PixelOperation, PixelSource};
use super::{
    ArchiveLimits, Limits, NetworkPayloadKind, NetworkPayloadState, NetworkWindow,
    PixelArtifactInfo, Surface, SurfaceError,
};
use crate::internal::media_documents::{
    from_archived_audio, from_archived_binary, from_archived_image, from_archived_video,
};
use crate::{
    archive::{DocumentArchiveRef, FileDocumentArchiveRef},
    automation_record::AutomationRecord,
    documents::{Document, DocumentId, DocumentProfile, FileDocument, FileMetadata, ImageDocument},
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
    /// New typed image payloads with their original source metadata.
    ImageDocument {
        /// Smallest automatically indexed region size in pixels.
        tile_side: u32,
    },
    /// A root pixel artifact with source provenance preserved during image indexing.
    PixelArtifact {
        /// Smallest automatically indexed region size in pixels.
        tile_side: u32,
    },
    /// A typed media file retained without an image or video Surface interpretation.
    FileDocument,
    /// A bounded manifest of named document/image views; never nested bundles.
    Bundle,
}

/// Concrete media kind retained in a portable Outcome.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ArchivedFileKind {
    /// PNG or JPEG image bytes.
    Image,
    /// Video container bytes.
    Video,
    /// Audio container bytes.
    Audio,
    /// Opaque binary bytes.
    Binary,
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
    /// Logical keys remain stable; keys used as Archive references follow
    /// the references written into the destination Archive.
    pub key: String,
    /// Original SDK document identity.
    pub document: DocumentId,
    /// Original text/DOM/JSON representation profile, absent for typed images.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub profile: Option<DocumentProfile>,
    /// Typed media family, absent for Documents and legacy text image envelopes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub file_kind: Option<ArchivedFileKind>,
    /// Original typed media metadata, absent for Documents and legacy envelopes.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub file_metadata: Option<FileMetadata>,
    /// Original pixel provenance when this source is a PixelArtifact.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub pixel_info: Option<PixelArtifactInfo>,
    /// SHA-256 of the decoded original bytes.
    pub sha256: String,
    /// Base64 transport of the original bytes, not an address of an external file.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub content_base64: Option<String>,
    /// Existing Archive reference used only inside a stored Outcome record.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub document_archive: Option<DocumentArchiveRef>,
    /// Existing typed media reference used only inside a stored Outcome record.
    #[serde(default, skip_serializing_if = "Option::is_none")]
    pub file_archive: Option<FileDocumentArchiveRef>,
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
            profile: Some(document.profile()),
            file_kind: None,
            file_metadata: None,
            pixel_info: None,
            sha256: format!("{:x}", Sha256::digest(document.bytes())),
            content_base64: Some(STANDARD.encode(document.bytes())),
            document_archive: None,
            file_archive: None,
            surface: surface.map(|value| value.identity().to_owned()),
        }
    }

    /// Freezes a typed media file without assigning a text Document profile.
    pub fn new_file_document(
        key: impl Into<String>,
        document: &FileDocument,
        surface: Option<&Surface>,
    ) -> Self {
        let file_kind = match document {
            FileDocument::Image(_) => ArchivedFileKind::Image,
            FileDocument::Video(_) => ArchivedFileKind::Video,
            FileDocument::Audio(_) => ArchivedFileKind::Audio,
            FileDocument::Binary(_) => ArchivedFileKind::Binary,
        };
        Self {
            interpretation: SourceInterpretation::FileDocument,
            key: key.into(),
            document: document.id().clone(),
            profile: None,
            file_kind: Some(file_kind),
            file_metadata: Some(document.metadata().clone()),
            pixel_info: None,
            sha256: document.sha256().to_owned(),
            content_base64: Some(STANDARD.encode(document.bytes())),
            document_archive: None,
            file_archive: None,
            surface: surface.map(|value| value.identity().to_owned()),
        }
    }

    /// Freezes a typed image without assigning it a text Document profile.
    pub fn new_image(
        key: impl Into<String>,
        document: &ImageDocument,
        tile_side: u32,
        surface: Option<&Surface>,
    ) -> Self {
        Self {
            interpretation: SourceInterpretation::ImageDocument { tile_side },
            key: key.into(),
            document: document.id().clone(),
            profile: None,
            file_kind: Some(ArchivedFileKind::Image),
            file_metadata: Some(document.metadata().clone()),
            pixel_info: None,
            sha256: document.sha256().to_owned(),
            content_base64: Some(STANDARD.encode(document.bytes())),
            document_archive: None,
            file_archive: None,
            surface: surface.map(|value| value.identity().to_owned()),
        }
    }

    /// Freezes a root PixelArtifact without replacing its source or coordinate provenance.
    #[cfg(any(feature = "browser", feature = "surface-images"))]
    pub fn new_pixel_artifact(
        key: impl Into<String>,
        artifact: &PixelArtifact,
        tile_side: u32,
        surface: Option<&Surface>,
    ) -> Self {
        let document = artifact.document();
        let is_root = matches!(&artifact.info().transform.operation, PixelOperation::Source);
        Self {
            interpretation: if is_root
                && surface.is_some_and(|surface| {
                    matches!(
                        surface.data.original.as_ref(),
                        Some(super::Original::TypedImage { .. })
                    )
                }) {
                SourceInterpretation::ImageDocument { tile_side }
            } else if is_root {
                SourceInterpretation::PixelArtifact { tile_side }
            } else {
                SourceInterpretation::FileDocument
            },
            key: key.into(),
            document: document.id().clone(),
            profile: None,
            file_kind: Some(ArchivedFileKind::Image),
            file_metadata: Some(document.metadata().clone()),
            pixel_info: Some(artifact.info().clone()),
            sha256: document.sha256().to_owned(),
            content_base64: Some(STANDARD.encode(document.bytes())),
            document_archive: None,
            file_archive: None,
            surface: if is_root {
                surface.map(|value| value.identity().to_owned())
            } else {
                None
            },
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
            #[cfg(any(feature = "browser", feature = "surface-images"))]
            Some(super::Original::TypedImage {
                document,
                tile_side,
            }) => Self::new_image(key, document, *tile_side, Some(surface)),
            #[cfg(any(feature = "browser", feature = "surface-images"))]
            Some(super::Original::PixelArtifact {
                artifact,
                tile_side,
            }) => Self::new_pixel_artifact(key, artifact, *tile_side, Some(surface)),
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

    /// Verifies and reconstructs a Document without fetching the original source.
    pub fn restore(&self, maximum: u64) -> Result<Document, SurfaceError> {
        if matches!(
            self.interpretation,
            SourceInterpretation::ImageDocument { .. } | SourceInterpretation::FileDocument
        ) || self.file_kind.is_some()
        {
            return Err(SurfaceError::Invalid(
                "typed media evidence must be restored with restore_file_document".into(),
            ));
        }
        let bytes = self.restore_bytes(maximum)?;
        let profile = self
            .profile
            .ok_or_else(|| SurfaceError::Invalid("archived Document profile is missing".into()))?;
        Document::from_profile(self.document.clone(), profile, bytes)
            .map_err(|error| SurfaceError::Invalid(error.to_string()))
    }

    /// Restores a typed original image without a source file or decoder.
    pub fn restore_image(&self, maximum: u64) -> Result<ImageDocument, SurfaceError> {
        if !matches!(
            self.interpretation,
            SourceInterpretation::ImageDocument { .. }
        ) {
            return Err(SurfaceError::Invalid(
                "archived source is not a typed ImageDocument".into(),
            ));
        }
        match self.restore_file_document(maximum)? {
            FileDocument::Image(document) => Ok(document),
            _ => Err(SurfaceError::Invalid(
                "archived typed media is not an ImageDocument".into(),
            )),
        }
    }

    /// Restores a root PixelArtifact without discarding its original source coordinates.
    #[cfg(any(feature = "browser", feature = "surface-images"))]
    pub fn restore_pixel_artifact(&self, maximum: u64) -> Result<PixelArtifact, SurfaceError> {
        if !matches!(
            self.interpretation,
            SourceInterpretation::PixelArtifact { .. }
                | SourceInterpretation::ImageDocument { .. }
                | SourceInterpretation::FileDocument
        ) || self.pixel_info.is_none()
        {
            return Err(SurfaceError::Invalid(
                "archived source is not a PixelArtifact".into(),
            ));
        }
        let info = self
            .pixel_info
            .clone()
            .ok_or_else(|| SurfaceError::Invalid("archived pixel provenance is missing".into()))?;
        match self.restore_file_document(maximum)? {
            FileDocument::Image(document) => PixelArtifact::from_archived_parts(document, info),
            _ => Err(SurfaceError::Invalid(
                "archived PixelArtifact payload is not an ImageDocument".into(),
            )),
        }
    }

    /// Restores the exact concrete typed media file without a source path or decoder.
    pub fn restore_file_document(&self, maximum: u64) -> Result<FileDocument, SurfaceError> {
        let kind = self
            .file_kind
            .ok_or_else(|| SurfaceError::Invalid("archived media kind is missing".into()))?;
        let metadata = self
            .file_metadata
            .clone()
            .ok_or_else(|| SurfaceError::Invalid("archived media metadata is missing".into()))?;
        let bytes = self.restore_bytes(maximum)?;
        if u64::try_from(bytes.len()).map_err(|_| SurfaceError::Limit("source size"))? > maximum {
            return Err(SurfaceError::Limit("archived source bytes"));
        }
        let bytes = Arc::new(bytes);
        let document = match kind {
            ArchivedFileKind::Image => {
                { from_archived_image(self.document.clone(), bytes, metadata) }
                    .map(FileDocument::Image)
            }
            ArchivedFileKind::Video => {
                { from_archived_video(self.document.clone(), bytes, metadata) }
                    .map(FileDocument::Video)
            }
            ArchivedFileKind::Audio => {
                { from_archived_audio(self.document.clone(), bytes, metadata) }
                    .map(FileDocument::Audio)
            }
            ArchivedFileKind::Binary => {
                { from_archived_binary(self.document.clone(), bytes, metadata) }
                    .map(FileDocument::Binary)
            }
        };
        document.map_err(|error| SurfaceError::Invalid(error.to_string()))
    }

    fn restore_bytes(&self, maximum: u64) -> Result<Vec<u8>, SurfaceError> {
        let encoded = self.content_base64.as_deref().ok_or_else(|| {
            SurfaceError::Invalid("archived source payload has not been hydrated".into())
        })?;
        let bound = maximum
            .checked_add(2)
            .and_then(|value| value.checked_div(3))
            .and_then(|value| value.checked_mul(4))
            .ok_or(SurfaceError::Limit("source encoding arithmetic"))?;
        if u64::try_from(encoded.len()).map_err(|_| SurfaceError::Limit("source size"))? > bound {
            return Err(SurfaceError::Limit("archived source bytes"));
        }
        let bytes = STANDARD
            .decode(encoded)
            .map_err(|error| SurfaceError::Parse(error.to_string()))?;
        if u64::try_from(bytes.len()).map_err(|_| SurfaceError::Limit("source size"))? > maximum {
            return Err(SurfaceError::Limit("archived source bytes"));
        }
        if format!("{:x}", Sha256::digest(&bytes)) != self.sha256 {
            return Err(SurfaceError::Invalid(
                "archived source digest mismatch".into(),
            ));
        }
        Ok(bytes)
    }

    /// Restores the index and rejects an interpretation whose identity changed.
    pub fn restore_surface(&self, limits: Limits) -> Result<Surface, SurfaceError> {
        let maximum =
            u64::try_from(limits.input_bytes).map_err(|_| SurfaceError::Limit("input limit"))?;
        let surface = match self.interpretation {
            SourceInterpretation::Document => {
                let document = self.restore(maximum)?;
                Surface::with_limits(&document, limits)?
            }
            SourceInterpretation::Image { tile_side } => {
                let document = self.restore(maximum)?;
                #[cfg(any(feature = "browser", feature = "surface-images"))]
                {
                    Surface::from_image(document.bytes(), tile_side, limits)?
                }
                #[cfg(not(any(feature = "browser", feature = "surface-images")))]
                {
                    let _ = document;
                    let _ = tile_side;
                    return Err(SurfaceError::Invalid(
                        "image restoration requires surface-images".into(),
                    ));
                }
            }
            SourceInterpretation::ImageDocument { tile_side } => {
                #[cfg(any(feature = "browser", feature = "surface-images"))]
                {
                    let image = self.restore_image(maximum)?;
                    Surface::from_image_document(&image, tile_side, limits)?
                }
                #[cfg(not(any(feature = "browser", feature = "surface-images")))]
                {
                    let _ = tile_side;
                    return Err(SurfaceError::Invalid(
                        "image restoration requires surface-images".into(),
                    ));
                }
            }
            SourceInterpretation::PixelArtifact { tile_side } => {
                #[cfg(any(feature = "browser", feature = "surface-images"))]
                {
                    let artifact = self.restore_pixel_artifact(maximum)?;
                    Surface::from_pixel_artifact(&artifact, tile_side, limits)?
                }
                #[cfg(not(any(feature = "browser", feature = "surface-images")))]
                {
                    let _ = tile_side;
                    return Err(SurfaceError::Invalid(
                        "pixel artifact restoration requires surface-images".into(),
                    ));
                }
            }
            SourceInterpretation::FileDocument => {
                return Err(SurfaceError::Invalid(
                    "generic typed media cannot be restored as an indexed Surface".into(),
                ));
            }
            SourceInterpretation::Bundle => {
                let document = self.restore(maximum)?;
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
            let source_bytes = source.restore_bytes(self.limits.bytes)?;
            if source.document_archive.is_some() && source.file_archive.is_some() {
                return Err(SurfaceError::Invalid(
                    "one source cannot reference both Document and FileDocument records".into(),
                ));
            }
            match &source.interpretation {
                SourceInterpretation::ImageDocument { .. } => {
                    if source.profile.is_some()
                        || source.file_kind != Some(ArchivedFileKind::Image)
                        || source.file_metadata.is_none()
                    {
                        return Err(SurfaceError::Invalid(
                            "typed image source profile or metadata is inconsistent".into(),
                        ));
                    }
                    source.restore_image(self.limits.bytes)?;
                    if let Some(info) = source.pixel_info.as_ref() {
                        if info.version != 1
                            || info.transform.version != 1
                            || info.sha256 != source.sha256
                            || info.width == 0
                            || info.height == 0
                            || !matches!(&info.source, PixelSource::ImageDocument { document_id, sha256 }
                            if document_id == source.document.as_str() && sha256 == &source.sha256)
                            || !matches!(info.transform.operation, PixelOperation::Source)
                        {
                            return Err(SurfaceError::Invalid(
                                "typed image has foreign pixel provenance".into(),
                            ));
                        }
                        #[cfg(any(feature = "browser", feature = "surface-images"))]
                        source.restore_pixel_artifact(self.limits.bytes)?;
                    }
                }
                SourceInterpretation::PixelArtifact { .. } => {
                    if source.profile.is_some()
                        || source.file_kind != Some(ArchivedFileKind::Image)
                        || source.file_metadata.is_none()
                        || source.pixel_info.is_none()
                    {
                        return Err(SurfaceError::Invalid(
                            "PixelArtifact source metadata is inconsistent".into(),
                        ));
                    }
                    #[cfg(any(feature = "browser", feature = "surface-images"))]
                    source.restore_pixel_artifact(self.limits.bytes)?;
                    #[cfg(not(any(feature = "browser", feature = "surface-images")))]
                    {
                        let info = source.pixel_info.as_ref().ok_or_else(|| {
                            SurfaceError::Invalid("PixelArtifact provenance is missing".into())
                        })?;
                        if info.sha256 != source.sha256 || info.width == 0 || info.height == 0 {
                            return Err(SurfaceError::Invalid(
                                "PixelArtifact provenance differs from its image payload".into(),
                            ));
                        }
                        if !matches!(
                            source.restore_file_document(self.limits.bytes)?,
                            FileDocument::Image(_)
                        ) {
                            return Err(SurfaceError::Invalid(
                                "PixelArtifact payload is not a typed image".into(),
                            ));
                        }
                    }
                }
                SourceInterpretation::FileDocument => {
                    if source.profile.is_some()
                        || source.file_kind.is_none()
                        || source.file_metadata.is_none()
                    {
                        return Err(SurfaceError::Invalid(
                            "typed media source profile or metadata is inconsistent".into(),
                        ));
                    }
                    if source.pixel_info.is_some() {
                        #[cfg(any(feature = "browser", feature = "surface-images"))]
                        source.restore_pixel_artifact(self.limits.bytes)?;
                        #[cfg(not(any(feature = "browser", feature = "surface-images")))]
                        {
                            let info = source.pixel_info.as_ref().ok_or_else(|| {
                                SurfaceError::Invalid("PixelArtifact provenance is missing".into())
                            })?;
                            if info.sha256 != source.sha256 || info.width == 0 || info.height == 0 {
                                return Err(SurfaceError::Invalid(
                                    "PixelArtifact provenance differs from its image payload"
                                        .into(),
                                ));
                            }
                            if !matches!(
                                source.restore_file_document(self.limits.bytes)?,
                                FileDocument::Image(_)
                            ) {
                                return Err(SurfaceError::Invalid(
                                    "PixelArtifact payload is not a typed image".into(),
                                ));
                            }
                        }
                    } else {
                        source.restore_file_document(self.limits.bytes)?;
                    }
                }
                _ => {
                    if source.profile.is_none()
                        || source.file_kind.is_some()
                        || source.file_metadata.is_some()
                        || source.pixel_info.is_some()
                    {
                        return Err(SurfaceError::Invalid(
                            "archived Document profile or media metadata is inconsistent".into(),
                        ));
                    }
                    source.restore(self.limits.bytes)?;
                }
            }
            if source.profile == Some(DocumentProfile::network_observation_v1())
                && source.file_kind.is_none()
            {
                let document = source.restore(self.limits.bytes)?;
                validate_network_payloads(self, &document)?;
            }
            let source_bytes = u64::try_from(source_bytes.len())
                .map_err(|_| SurfaceError::Limit("outcome source size"))?;
            total = total
                .checked_add(source_bytes)
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
            let source = self.sources.iter().find(|source| {
                source.key == key
                    || source
                        .document_archive
                        .as_ref()
                        .is_some_and(|reference| reference.to_string() == key)
                    || source
                        .file_archive
                        .as_ref()
                        .is_some_and(|reference| reference.to_string() == key)
            });
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

    /// Restores one retained source-backed text/DOM/JSON Document by its stable key.
    pub fn source_document(&self, key: &str, maximum: u64) -> Result<Document, SurfaceError> {
        self.sources
            .iter()
            .find(|source| source_matches_key(source, key))
            .ok_or(SurfaceError::Unknown)?
            .restore(maximum)
    }

    /// Restores one retained typed file payload by its stable key.
    pub fn source_file_document(
        &self,
        key: &str,
        maximum: u64,
    ) -> Result<FileDocument, SurfaceError> {
        self.sources
            .iter()
            .find(|source| source_matches_key(source, key))
            .ok_or(SurfaceError::Unknown)?
            .restore_file_document(maximum)
    }

    /// Restores a retained pixel artifact, including derived pixel provenance.
    #[cfg(any(feature = "browser", feature = "surface-images"))]
    pub fn source_pixel_artifact(
        &self,
        key: &str,
        maximum: u64,
    ) -> Result<PixelArtifact, SurfaceError> {
        self.sources
            .iter()
            .find(|source| source_matches_key(source, key))
            .ok_or(SurfaceError::Unknown)?
            .restore_pixel_artifact(maximum)
    }
}

fn source_matches_key(source: &ArchivedSource, key: &str) -> bool {
    source.key == key
        || source
            .document_archive
            .as_ref()
            .is_some_and(|reference| reference.to_string() == key)
        || source
            .file_archive
            .as_ref()
            .is_some_and(|reference| reference.to_string() == key)
}

fn validate_network_payloads(outcome: &Outcome, document: &Document) -> Result<(), SurfaceError> {
    let window = NetworkWindow::from_document(document)?;
    for payload in &window.payloads {
        if !matches!(
            payload.state,
            NetworkPayloadState::Retained | NetworkPayloadState::Truncated
        ) {
            continue;
        }
        let key = payload.document_id.as_deref().ok_or_else(|| {
            SurfaceError::Invalid("retained network body lacks a source key".into())
        })?;
        if key != payload.id {
            return Err(SurfaceError::Invalid(
                "network payload id and source key differ".into(),
            ));
        }
        let Some(source) = outcome
            .sources
            .iter()
            .find(|source| source_matches_key(source, key))
        else {
            if outcome.complete {
                return Err(SurfaceError::Invalid(
                    "retained network body source is missing from the Outcome".into(),
                ));
            }
            continue;
        };
        let digest = payload.sha256.as_deref().ok_or_else(|| {
            SurfaceError::Invalid("retained network payload lacks a digest".into())
        })?;
        let bytes = source.restore_bytes(outcome.limits.bytes)?;
        let projection_matches = match payload.document_kind {
            Some(NetworkPayloadKind::Html) => {
                source.profile == Some(DocumentProfile::source_html()) && source.file_kind.is_none()
            }
            Some(NetworkPayloadKind::Json) => {
                source.profile == Some(DocumentProfile::source_json()) && source.file_kind.is_none()
            }
            Some(NetworkPayloadKind::File) => {
                source.profile.is_none() && source.file_kind.is_some()
            }
            None => false,
        };
        if !projection_matches
            || source.sha256 != digest
            || u64::try_from(bytes.len())
                .map_err(|_| SurfaceError::Limit("network payload byte count"))?
                != payload.retained_bytes
        {
            return Err(SurfaceError::Invalid(
                "retained network body metadata differs from its archived source".into(),
            ));
        }
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::ArchivedSource;
    use crate::{
        documents::{
            BinaryDocument, Document, DocumentId, DocumentProfile, FileDocument, FileLimits,
            FileMetadata,
        },
        surface::{ArchiveLimits, Outcome},
    };
    use std::error::Error;

    const PNG_SIGNATURE: [u8; 8] = [0x89, b'P', b'N', b'G', 0x0d, 0x0a, 0x1a, 0x0a];

    #[test]
    fn typed_source_restore_preserves_forced_binary_classification_and_metadata()
    -> Result<(), Box<dyn Error>> {
        let metadata = FileMetadata::new()
            .with_filename("known-image.bin")?
            .with_declared_media_type("application/octet-stream")?
            .with_source("fixture:known-png-signature")?;
        let binary = BinaryDocument::from_bytes_with_metadata(
            "forced-binary-image",
            PNG_SIGNATURE.to_vec(),
            metadata,
            FileLimits::default(),
        )?;
        assert_eq!(binary.metadata().detected_media_type(), Some("image/png"));
        let original = FileDocument::Binary(binary);
        let retained = ArchivedSource::new_file_document("payload", &original, None);

        let restored = retained.restore_file_document(1024)?;
        assert_eq!(restored, original);
        let FileDocument::Binary(restored_binary) = restored else {
            return Err("typed binary source changed its media family".into());
        };
        assert_eq!(restored_binary.bytes(), &PNG_SIGNATURE);
        assert_eq!(
            restored_binary.metadata().declared_media_type(),
            Some("application/octet-stream")
        );
        assert_eq!(
            restored_binary.metadata().detected_media_type(),
            Some("image/png")
        );
        Ok(())
    }

    #[test]
    fn network_payload_dependencies_use_typed_profile_and_exact_state_contract()
    -> Result<(), Box<dyn Error>> {
        let network_document = |payloads: serde_json::Value| -> Result<Document, Box<dyn Error>> {
            Ok(Document::from_profile(
                DocumentId::try_new("network-observation")?,
                DocumentProfile::network_observation_v1(),
                serde_json::to_vec(&serde_json::json!({
                    "schema": "yosoi.network.v1",
                    "schema_version": 1,
                    "response_window_id": "recording:2",
                    "payloads": payloads,
                }))?,
            )?)
        };

        let body = Document::html("body-document", b"<p>body</p>".to_vec())?;
        let payload_source = ArchivedSource::new("body-key", &body, None);
        let retained_payload = |state: &str,
                                id: &str,
                                document_id: &str,
                                provider_base64_encoded: bool,
                                text_utf8_normalized: bool| {
            serde_json::json!({
                "id": id,
                "state": state,
                "document_id": document_id,
                "document_kind": "html",
                "projection_basis": "requests_declared",
                "sha256": payload_source.sha256,
                "retained_bytes": body.byte_len(),
                "byte_provenance": "cdp_decoded_response_body",
                "provider_base64_encoded": provider_base64_encoded,
                "provider_reported_body_bytes": body.byte_len(),
                "declared_media_type": "text/html",
                "browser_effective_mime": null,
                "browser_effective_charset": null,
                "detected_media_type": null,
                "text_utf8_normalized": text_utf8_normalized,
            })
        };
        let unretained_payload =
            |state: &str,
             provider_base64_encoded: bool,
             text_utf8_normalized: bool,
             provider_reported_body_bytes: Option<u64>| {
                serde_json::json!({
                    "id": "opaque",
                    "state": state,
                    "document_id": null,
                    "document_kind": null,
                    "projection_basis": null,
                    "sha256": null,
                    "retained_bytes": 0,
                    "byte_provenance": "none",
                    "provider_base64_encoded": provider_base64_encoded,
                    "provider_reported_body_bytes": provider_reported_body_bytes,
                    "declared_media_type": null,
                    "browser_effective_mime": null,
                    "browser_effective_charset": null,
                    "detected_media_type": null,
                    "text_utf8_normalized": text_utf8_normalized,
                })
            };
        let retained_window = network_document(serde_json::json!([retained_payload(
            "retained", "body-key", "body-key", true, false
        )]))?;
        let complete = Outcome::new("network-check", ArchiveLimits::default())?
            .with_source(payload_source.clone())?
            .with_source(ArchivedSource::new("window", &retained_window, None))?;
        assert!(complete.complete);

        for state in ["not_requested", "unavailable", "unsupported"] {
            let window = network_document(serde_json::json!([unretained_payload(
                state,
                state == "unavailable",
                false,
                (state == "unavailable").then_some(body.byte_len()),
            )]))?;
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(ArchivedSource::new("window", &window, None))?;
        }

        let utf8_window = network_document(serde_json::json!([retained_payload(
            "truncated",
            "body-key",
            "body-key",
            false,
            true
        )]))?;
        Outcome::new("network-check", ArchiveLimits::default())?
            .with_source(payload_source.clone())?
            .with_source(ArchivedSource::new("window", &utf8_window, None))?;

        let mixed_encoding = network_document(serde_json::json!([retained_payload(
            "retained", "body-key", "body-key", true, true
        )]))?;
        assert!(
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(payload_source.clone())?
                .with_source(ArchivedSource::new("window", &mixed_encoding, None))
                .is_err()
        );

        let unretained_text = network_document(serde_json::json!([unretained_payload(
            "unavailable",
            false,
            true,
            Some(body.byte_len())
        )]))?;
        assert!(
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(ArchivedSource::new("window", &unretained_text, None))
                .is_err()
        );

        let mismatched = network_document(serde_json::json!([retained_payload(
            "truncated",
            "payload-id",
            "other-key",
            false,
            true
        )]))?;
        assert!(
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(ArchivedSource::new("window", &mismatched, None))
                .is_err()
        );

        let mut unsupported_basis =
            retained_payload("retained", "body-key", "body-key", true, false);
        unsupported_basis
            .as_object_mut()
            .ok_or("retained payload is not an object")?
            .insert("projection_basis".into(), serde_json::json!("unreviewed"));
        let unsupported_basis = network_document(serde_json::json!([unsupported_basis]))?;
        assert!(
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(payload_source.clone())?
                .with_source(ArchivedSource::new("window", &unsupported_basis, None))
                .is_err()
        );

        let mut wrong_length = retained_payload("retained", "body-key", "body-key", true, false);
        wrong_length
            .as_object_mut()
            .ok_or("retained payload is not an object")?
            .insert(
                "retained_bytes".into(),
                serde_json::json!(
                    body.byte_len()
                        .checked_add(1)
                        .ok_or("body length overflow")?
                ),
            );
        let wrong_length = network_document(serde_json::json!([wrong_length]))?;
        assert!(
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(payload_source.clone())?
                .with_source(ArchivedSource::new("window", &wrong_length, None))
                .is_err()
        );

        let mut unretained_source = unretained_payload("unavailable", false, false, None);
        unretained_source
            .as_object_mut()
            .ok_or("unretained payload is not an object")?
            .insert("document_kind".into(), serde_json::json!("file"));
        let unretained_source = network_document(serde_json::json!([unretained_source]))?;
        assert!(
            Outcome::new("network-check", ArchiveLimits::default())?
                .with_source(ArchivedSource::new("window", &unretained_source, None))
                .is_err()
        );

        let source_json = Document::json(
            "ordinary-json",
            serde_json::to_vec(&serde_json::json!({
                "schema": "yosoi.network.v1",
                "payloads": [{"state":"invented","document_id":"foreign"}],
            }))?,
        )?;
        Outcome::new("ordinary-json-check", ArchiveLimits::default())?
            .with_source(ArchivedSource::new("json", &source_json, None))?;
        Ok(())
    }
}
