//! In-memory association between a finalized Web Capture and exact payload bytes.

use std::{collections::BTreeMap, fmt};

use thiserror::Error;
use yosoi_types::{ArtifactAvailability, Sha256Digest};

use crate::{WebArtifact, WebArtifactRef, WebCapture};

/// Error returned while validating or finalizing capture payloads.
#[derive(Debug, Error, PartialEq, Eq)]
pub enum CaptureBundleError {
    /// The reference belongs to another capture activity.
    #[error("payload reference is foreign to the capture")]
    ForeignReference,
    /// The reference was already admitted successfully.
    #[error("payload reference was already admitted")]
    Duplicate,
    /// The reference names this capture but no matching manifest artifact.
    #[error("payload reference belongs to this capture but has no manifest artifact")]
    Orphaned,
    /// Bytes were supplied for an artifact deliberately discarded at capture time.
    #[error("discarded artifact cannot expose payload bytes")]
    Discarded,
    /// Bytes were supplied for an artifact unavailable at capture time.
    #[error("unavailable artifact cannot expose payload bytes")]
    Unavailable,
    /// A retained or truncated artifact had no admitted payload.
    #[error("retained or truncated artifact is missing its payload")]
    Missing,
    /// Supplied bytes disagreed with the exact retained extent.
    #[error("payload size does not match artifact metadata")]
    SizeMismatch,
    /// Supplied bytes disagreed with the exact retained digest.
    #[error("payload digest does not match artifact metadata")]
    DigestMismatch,
}

/// Immutable in-memory capture metadata and its verified retained payloads.
///
/// This type deliberately has no Serde representation and does not clone large
/// payloads implicitly. The finalized [`WebCapture`] remains the metadata
/// authority; this bundle only proves and resolves its retained bytes.
#[derive(PartialEq, Eq)]
pub struct CaptureBundle {
    capture: WebCapture,
    payloads: BTreeMap<WebArtifactRef, Vec<u8>>,
}

impl fmt::Debug for CaptureBundle {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CaptureBundle")
            .field("capture_id", &self.capture.id())
            .field("payload_count", &self.payloads.len())
            .field("payloads", &"<redacted>")
            .finish()
    }
}

impl CaptureBundle {
    /// Returns the already finalized capture metadata.
    pub const fn capture(&self) -> &WebCapture {
        &self.capture
    }

    /// Borrows exact retained bytes for a typed artifact reference.
    pub fn payload(&self, reference: WebArtifactRef) -> Option<&[u8]> {
        self.payloads.get(&reference).map(Vec::as_slice)
    }

    /// Iterates non-lossily over typed references and exact retained bytes.
    pub fn payloads(&self) -> impl Iterator<Item = (WebArtifactRef, &[u8])> {
        self.payloads
            .iter()
            .map(|(reference, bytes)| (*reference, bytes.as_slice()))
    }

    /// Consumes the in-memory association without defining a storage or archive format.
    pub fn into_parts(self) -> (WebCapture, Vec<(WebArtifactRef, Vec<u8>)>) {
        (self.capture, self.payloads.into_iter().collect())
    }

    /// Starts payload admission for an already finalized capture.
    pub const fn builder(capture: WebCapture) -> CaptureBundleBuilder {
        CaptureBundleBuilder {
            capture,
            payloads: BTreeMap::new(),
        }
    }
}

/// Unpublished payload staging for one finalized capture.
///
/// Failed inserts do not reserve a reference. `finalize` consumes the builder,
/// so neither a successful nor failed finalization can publish a partial bundle
/// and then be reused.
pub struct CaptureBundleBuilder {
    capture: WebCapture,
    payloads: BTreeMap<WebArtifactRef, Vec<u8>>,
}

impl fmt::Debug for CaptureBundleBuilder {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CaptureBundleBuilder")
            .field("capture_id", &self.capture.id())
            .field("payload_count", &self.payloads.len())
            .field("payloads", &"<redacted>")
            .finish()
    }
}

impl CaptureBundleBuilder {
    /// Validates and stages one payload without publishing a bundle.
    pub fn insert(
        &mut self,
        reference: WebArtifactRef,
        bytes: Vec<u8>,
    ) -> Result<(), CaptureBundleError> {
        let artifact = find_artifact(&self.capture, reference)?;
        validate_availability(&artifact)?;
        if self.payloads.contains_key(&reference) {
            return Err(CaptureBundleError::Duplicate);
        }
        validate_payload(&artifact, &bytes)?;
        self.payloads.insert(reference, bytes);
        Ok(())
    }

    /// Verifies exhaustive payload presence and publishes an immutable bundle.
    pub fn finalize(self) -> Result<CaptureBundle, CaptureBundleError> {
        for artifact in self.capture.artifacts().results().all_artifacts() {
            if matches!(
                artifact.metadata().record().availability(),
                ArtifactAvailability::Retained | ArtifactAvailability::Truncated
            ) {
                let bytes = self
                    .payloads
                    .get(&artifact.reference())
                    .ok_or(CaptureBundleError::Missing)?;
                validate_payload(&artifact, bytes)?;
            }
        }
        Ok(CaptureBundle {
            capture: self.capture,
            payloads: self.payloads,
        })
    }
}

fn find_artifact(
    capture: &WebCapture,
    reference: WebArtifactRef,
) -> Result<WebArtifact, CaptureBundleError> {
    if reference.as_untyped().activity_id() != capture.id().activity_id() {
        return Err(CaptureBundleError::ForeignReference);
    }
    capture
        .artifacts()
        .results()
        .all_artifacts()
        .into_iter()
        .find(|artifact| artifact.reference() == reference)
        .ok_or(CaptureBundleError::Orphaned)
}

const fn validate_availability(artifact: &WebArtifact) -> Result<(), CaptureBundleError> {
    match artifact.metadata().record().availability() {
        ArtifactAvailability::Retained | ArtifactAvailability::Truncated => Ok(()),
        ArtifactAvailability::Discarded => Err(CaptureBundleError::Discarded),
        ArtifactAvailability::Unavailable => Err(CaptureBundleError::Unavailable),
    }
}

fn validate_payload(artifact: &WebArtifact, bytes: &[u8]) -> Result<(), CaptureBundleError> {
    let retained = artifact
        .metadata()
        .extent()
        .retained_bytes()
        .ok_or(CaptureBundleError::SizeMismatch)?;
    let supplied = u64::try_from(bytes.len()).map_err(|_| CaptureBundleError::SizeMismatch)?;
    if retained.get() != supplied {
        return Err(CaptureBundleError::SizeMismatch);
    }
    let digest = artifact
        .metadata()
        .content_digest()
        .ok_or(CaptureBundleError::DigestMismatch)?;
    if Sha256Digest::digest(bytes) != digest {
        return Err(CaptureBundleError::DigestMismatch);
    }
    Ok(())
}
