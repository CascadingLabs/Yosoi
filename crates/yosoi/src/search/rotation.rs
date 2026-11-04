//! Archive persistence for the immutable Auto selection metadata.
use super::{AutoRotationTrace, SearchReplayError, SearchResponse};
use crate::{
    archive::{Archive, DocumentArchiveRef},
    documents::{Document, DocumentProfile},
};
use serde::{Deserialize, Serialize};

const MAX_ROTATION_BYTES: usize = 256 * 1024;

/// Portable reference to one immutable Auto rotation record in Archive.
/// Reading this reference restores evidence only, never a reservation or cursor.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AutoRotationRef {
    /// Logical reference version, currently one.
    pub version: u16,
    /// Exact JSON Document reference protected by Archive integrity checks.
    pub document: DocumentArchiveRef,
}

impl AutoRotationTrace {
    /// Saves the validated, content-free selection record as an immutable JSON Document.
    /// This works without retained page captures, including all-ineligible searches.
    pub async fn write_to(&self, archive: &Archive) -> Result<AutoRotationRef, SearchReplayError> {
        if !self.validate() {
            return Err(SearchReplayError::InvalidBounds);
        }
        let bytes = serde_json::to_vec(self).map_err(SearchReplayError::Metadata)?;
        if bytes.len() > MAX_ROTATION_BYTES {
            return Err(SearchReplayError::InvalidBounds);
        }
        let document = Document::json(format!("search-rotation-{}", self.search_request_id), bytes)
            .map_err(|_| SearchReplayError::InvalidBounds)?;
        Ok(AutoRotationRef {
            version: 1,
            document: archive.write_document(&document).await?,
        })
    }

    /// Restores and validates the original routing decision without opening Registry,
    /// contacting a provider, charging a budget or advancing rotation.
    pub async fn read_from(
        archive: &Archive,
        reference: &AutoRotationRef,
    ) -> Result<Self, SearchReplayError> {
        if reference.version != 1 {
            return Err(SearchReplayError::UnsupportedVersion(reference.version));
        }
        let document = archive.read_document(&reference.document).await?;
        if document.profile() != DocumentProfile::source_json()
            || document.bytes().len() > MAX_ROTATION_BYTES
        {
            return Err(SearchReplayError::InvalidBounds);
        }
        let trace: Self =
            serde_json::from_slice(document.bytes()).map_err(SearchReplayError::Metadata)?;
        if !trace.validate() {
            return Err(SearchReplayError::InvalidBounds);
        }
        Ok(trace)
    }
}

impl SearchResponse {
    /// Saves the Auto routing audit independently of page-capture retention.
    /// Returns None when routing was All or stopped before Registry evaluation.
    pub async fn save_rotation(
        &self,
        archive: &Archive,
    ) -> Result<Option<AutoRotationRef>, SearchReplayError> {
        match self.rotation() {
            Some(trace) => trace.write_to(archive).await.map(Some),
            None => Ok(None),
        }
    }
}

/// Portable diagnostic bundle linking one Auto audit to its retained parser inputs.
/// Capture records contain query/page URLs; saving the bundle is explicit retention.
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub struct SearchEvidence {
    /// Logical diagnostic bundle schema, currently one.
    pub schema_version: u16,
    /// Immutable parent decision, including decisions with no page captures.
    pub rotation: Option<AutoRotationRef>,
    /// Original, recovery and resolution document replay records.
    pub records: Vec<super::SearchReplay>,
}

impl SearchResponse {
    /// Saves one routing audit and links every retained capture to that exact record.
    /// No network work or cursor mutation occurs. Cancellation or a later write failure
    /// may leave unreferenced immutable documents; no partial bundle is returned.
    pub async fn save_diagnostics(
        &self,
        archive: &Archive,
    ) -> Result<SearchEvidence, SearchReplayError> {
        let rotation = self.save_rotation(archive).await?;
        let mut records = Vec::new();
        for provider in self.providers() {
            for capture in provider.captures() {
                if records.len() >= 256 {
                    return Err(SearchReplayError::InvalidBounds);
                }
                let mut record = capture.save(archive).await?;
                record.rotation.clone_from(&rotation);
                records.push(record);
            }
        }
        Ok(SearchEvidence {
            schema_version: 1,
            rotation,
            records,
        })
    }
}
