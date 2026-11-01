use serde::{Deserialize, Serialize};

use crate::{
    documents::{Document, ImageDocument},
    internal::archive::{
        Archive, ArchiveError, ImageDocumentArchiveRef,
        dispatch::{ArchiveReference, ArchiveValue, sealed},
    },
    surface::pixels::{PixelArtifact, PixelArtifactArchiveRef, PixelArtifactInfo},
};

const PIXEL_ARTIFACT_SCHEMA: &str = "yosoi.pixel-artifact.v1";

#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct PixelArtifactRecord {
    schema: String,
    image: ImageDocumentArchiveRef,
    info: PixelArtifactInfo,
}

impl sealed::Value for PixelArtifact {}

impl ArchiveValue for PixelArtifact {
    type Reference = PixelArtifactArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        value
            .validate()
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        let image = archive.write(value.document()).await?;
        let record = PixelArtifactRecord {
            schema: PIXEL_ARTIFACT_SCHEMA.into(),
            image,
            info: value.info().clone(),
        };
        let bytes = serde_json::to_vec(&record).map_err(|error| {
            ArchiveError::InvalidSurfaceOutcome(format!(
                "cannot encode pixel artifact record: {error}"
            ))
        })?;
        let document = Document::json(format!("pixel-artifact-{}", value.info().sha256), bytes)
            .map_err(ArchiveError::InvalidDocument)?;
        let document = archive.write_document(&document).await?;
        Ok(PixelArtifactArchiveRef { document })
    }
}

impl sealed::Reference for PixelArtifactArchiveRef {}

impl ArchiveReference for PixelArtifactArchiveRef {
    type Value = PixelArtifact;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        let record_document = archive.read_document(&reference.document).await?;
        if record_document.bytes().len() > 64 * 1024 {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "pixel artifact metadata exceeds 64 KiB".into(),
            ));
        }
        let record: PixelArtifactRecord =
            serde_json::from_slice(record_document.bytes()).map_err(|error| {
                ArchiveError::InvalidSurfaceOutcome(format!(
                    "invalid pixel artifact metadata: {error}"
                ))
            })?;
        if record.schema != PIXEL_ARTIFACT_SCHEMA {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "unsupported pixel artifact schema".into(),
            ));
        }
        let image: ImageDocument = archive.read(&record.image).await?;
        PixelArtifact::from_archived_parts(image, record.info)
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))
    }
}
