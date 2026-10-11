use std::fmt;

use crate::internal::documents::{Document, DocumentId, LocateOutcome};
use serde::{Deserialize, Deserializer, Serialize};
use thiserror::Error;

use crate::internal::archive::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::internal::archive::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::internal::archive::{
    Archive, ArchiveError, DocumentArchiveRef, EvaluationRunArchiveRef, LocatorRunArchiveRef,
};

const LOCATOR_RUN_RECORD_VERSION: u32 = 1;

/// Immutable output of applying one archived Plan to one archived Document.
#[derive(Clone, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct LocatorRunRecord {
    evaluation: EvaluationRunArchiveRef,
    document: DocumentArchiveRef,
    outcome: LocateOutcome,
}

impl fmt::Debug for LocatorRunRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        let status = match &self.outcome {
            LocateOutcome::Matched { .. } => "matched",
            LocateOutcome::NoMatch { .. } => "no_match",
            LocateOutcome::Indeterminate { .. } => "indeterminate",
            LocateOutcome::Failed { .. } => "failed",
        };
        formatter
            .debug_struct("LocatorRunRecord")
            .field("evaluation", &self.evaluation)
            .field("document", &self.document)
            .field("outcome_status", &status)
            .finish()
    }
}

impl LocatorRunRecord {
    pub const fn new(
        evaluation: EvaluationRunArchiveRef,
        document: DocumentArchiveRef,
        outcome: LocateOutcome,
    ) -> Self {
        Self {
            evaluation,
            document,
            outcome,
        }
    }

    pub const fn evaluation(&self) -> &EvaluationRunArchiveRef {
        &self.evaluation
    }

    pub const fn document(&self) -> &DocumentArchiveRef {
        &self.document
    }

    pub const fn outcome(&self) -> &LocateOutcome {
        &self.outcome
    }
}

impl<'de> Deserialize<'de> for LocatorRunRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            evaluation: EvaluationRunArchiveRef,
            document: DocumentArchiveRef,
            outcome: LocateOutcome,
        }

        let wire = Wire::deserialize(deserializer)?;
        Ok(Self::new(wire.evaluation, wire.document, wire.outcome))
    }
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum LocatorRunRecordError {
    #[error("LocatorRun Document is not an input of its EvaluationRun")]
    DocumentNotInEvaluation,
    #[error("LocatorRun outcome belongs to Document {outcome}, not archived Document {archived}")]
    OutcomeDocumentMismatch {
        archived: DocumentId,
        outcome: DocumentId,
    },
}

impl sealed::Value for LocatorRunRecord {}

impl ArchiveValue for LocatorRunRecord {
    type Reference = LocatorRunArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        validate_references(archive, value).await?;
        let reference = LocatorRunArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::LocatorRun,
                LOCATOR_RUN_RECORD_VERSION,
                reference.key(),
                value,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for LocatorRunArchiveRef {}

impl ArchiveReference for LocatorRunArchiveRef {
    type Value = LocatorRunRecord;

    async fn read_from<'a>(
        archive: &'a Archive,
        reference: &'a Self,
    ) -> Result<Self::Value, ArchiveError> {
        if reference.format_version() != ARCHIVE_FORMAT_VERSION {
            return Err(ArchiveError::UnsupportedFormat {
                found: reference.format_version(),
                supported: ARCHIVE_FORMAT_VERSION,
            });
        }
        let record = archive
            .read_record(
                RecordKind::LocatorRun,
                LOCATOR_RUN_RECORD_VERSION,
                reference.key(),
            )
            .await?;
        validate_references(archive, &record).await?;
        Ok(record)
    }
}

async fn validate_references(
    archive: &Archive,
    record: &LocatorRunRecord,
) -> Result<(), ArchiveError> {
    let evaluation = archive.read(record.evaluation()).await?;
    if !evaluation
        .documents()
        .iter()
        .any(|input| input.document() == record.document())
    {
        return Err(ArchiveError::InvalidLocatorRun(
            LocatorRunRecordError::DocumentNotInEvaluation,
        ));
    }
    let document: Document = archive.read(record.document()).await?;
    if let Some(outcome_document) = outcome_document_id(record.outcome())
        && outcome_document != document.id()
    {
        return Err(ArchiveError::InvalidLocatorRun(
            LocatorRunRecordError::OutcomeDocumentMismatch {
                archived: document.id().clone(),
                outcome: outcome_document.clone(),
            },
        ));
    }
    Ok(())
}

const fn outcome_document_id(outcome: &LocateOutcome) -> Option<&DocumentId> {
    match outcome {
        LocateOutcome::Matched { result } => Some(result.document_id()),
        LocateOutcome::NoMatch { document_id }
        | LocateOutcome::Indeterminate { document_id, .. } => Some(document_id),
        LocateOutcome::Failed { .. } => None,
    }
}
