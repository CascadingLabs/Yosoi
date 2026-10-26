//! Surface values join the existing sealed Archive dispatch.

use super::{Archive, ArchiveError};
use crate::internal::archive::{ArchiveReference, ArchiveValue, sealed};
use crate::{
    documents::{Document, DocumentProfile},
    surface::{Outcome, OutcomeRef},
};
use std::{collections::BTreeMap, fmt::Display};

const MAX_OUTCOME_BYTES: usize = 256 * 1024 * 1024;

pub(super) async fn rehydrate(archive: &Archive, value: &mut Outcome) -> Result<(), ArchiveError> {
    // Only these versioned receipts contain Archive Document dependencies.
    // Never scan arbitrary result strings or copy an entire source directory.
    let mut wire = serde_json::to_value(&value.record).map_err(invalid)?;
    let mut remapped = BTreeMap::new();
    let operations = wire
        .get_mut("operations")
        .and_then(serde_json::Value::as_array_mut)
        .ok_or_else(|| invalid("missing record operations"))?;
    for operation in operations {
        let kind = operation
            .get("kind")
            .and_then(serde_json::Value::as_str)
            .unwrap_or_default();
        if !matches!(
            kind,
            "surface.capture" | "surface.video.source" | "surface.video.frame"
        ) {
            continue;
        }
        let reference = operation
            .pointer_mut("/result/document")
            .ok_or_else(|| invalid("missing retained document reference"))?;
        let key = reference
            .as_str()
            .ok_or_else(|| invalid("document reference is not text"))?
            .to_owned();
        if !remapped.contains_key(&key) {
            let source = value.sources.iter().find(|source| source.key == key);
            let Some(source) = source else {
                if value.complete {
                    return Err(invalid("portable outcome is missing a required document"));
                }
                // Incomplete outcomes remain inspectable. A replay must reject
                // missing evidence rather than fetching from another store.
                continue;
            };
            let document = source.restore(value.limits.bytes).map_err(invalid)?;
            let old = key.parse().map_err(invalid)?;
            let fresh = match archive.read_document(&old).await {
                Ok(existing) if existing == document => key.clone(),
                Ok(_) => {
                    return Err(invalid(
                        "retained reference conflicts with current Archive bytes",
                    ));
                }
                Err(
                    ArchiveError::RecordNotFound { .. }
                    | ArchiveError::DocumentPayloadMissing { .. },
                ) => archive.write_document(&document).await?.to_string(),
                Err(error) => return Err(error),
            };
            remapped.insert(key.clone(), fresh);
        }
        if let Some(fresh) = remapped.get(&key) {
            *reference = serde_json::Value::String(fresh.clone());
        }
    }
    for source in &mut value.sources {
        if let Some(fresh) = remapped.get(&source.key) {
            source.key.clone_from(fresh);
        }
    }
    value.record = serde_json::from_value(wire).map_err(invalid)?;
    Ok(())
}

fn invalid(error: impl Display) -> ArchiveError {
    ArchiveError::InvalidSurfaceOutcome(error.to_string())
}

impl sealed::Value for Outcome {}
impl ArchiveValue for Outcome {
    type Reference = OutcomeRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<OutcomeRef, ArchiveError> {
        value
            .validate()
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        let mut retained = value.clone();
        rehydrate(archive, &mut retained).await?;
        let bytes = serde_json::to_vec(&retained)
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        if bytes.len() > MAX_OUTCOME_BYTES {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "encoded outcome exceeds 256 MiB".into(),
            ));
        }
        let document = Document::json(format!("surface-outcome-{}", value.record.id()), bytes)
            .map_err(ArchiveError::InvalidDocument)?;
        Ok(OutcomeRef {
            document: archive.write_document(&document).await?,
            version: 1,
        })
    }
}

impl sealed::Reference for OutcomeRef {}
impl ArchiveReference for OutcomeRef {
    type Value = Outcome;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Outcome, ArchiveError> {
        if reference.version != 1 {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "unsupported outcome reference version".into(),
            ));
        }
        let document = archive.read_document(&reference.document).await?;
        if document.profile() != DocumentProfile::source_json()
            || document.bytes().len() > MAX_OUTCOME_BYTES
        {
            return Err(ArchiveError::InvalidSurfaceOutcome(
                "invalid outcome document profile or size".into(),
            ));
        }
        let value: Outcome = serde_json::from_slice(document.bytes())
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        value
            .validate()
            .map_err(|error| ArchiveError::InvalidSurfaceOutcome(error.to_string()))?;
        Ok(value)
    }
}
