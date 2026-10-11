use std::collections::BTreeSet;

use crate::internal::web_capture::{CaptureBundle, WebArtifactRef};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use crate::internal::archive::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::internal::archive::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::internal::archive::{
    Archive, ArchiveError, CaptureArchiveRef, ContractSchemaArchiveRef, DocumentArchiveRef,
    EvaluationRunArchiveRef, PlanArchiveRef, PolicyArchiveRef,
};

const EVALUATION_RUN_RECORD_VERSION: u32 = 1;

/// Maximum ordered Documents bound to one offline evaluation record.
pub const MAX_EVALUATION_DOCUMENTS: u64 = 64;

/// One normalized Document selected from a capture for offline evaluation.
///
/// The Document record owns exact evaluator-ready bytes. `source_artifact` is
/// optional provenance back to retained Capture evidence; it is never used as a
/// substitute for the archived Document payload.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ArchivedDocumentInput {
    document: DocumentArchiveRef,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    source_artifact: Option<WebArtifactRef>,
}

impl ArchivedDocumentInput {
    pub const fn new(
        document: DocumentArchiveRef,
        source_artifact: Option<WebArtifactRef>,
    ) -> Self {
        Self {
            document,
            source_artifact,
        }
    }

    pub const fn document(&self) -> &DocumentArchiveRef {
        &self.document
    }

    pub const fn source_artifact(&self) -> Option<WebArtifactRef> {
        self.source_artifact
    }
}

/// Durable inputs for one repeatable offline evaluation.
///
/// This record links data and definitions only. It contains no generated Rust,
/// executable Contract, request target, provider handle, or replay instruction.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EvaluationRunRecord {
    capture: CaptureArchiveRef,
    policy: PolicyArchiveRef,
    plan: PlanArchiveRef,
    #[serde(default, skip_serializing_if = "Option::is_none")]
    contract_schema: Option<ContractSchemaArchiveRef>,
    documents: Vec<ArchivedDocumentInput>,
}

impl EvaluationRunRecord {
    pub fn try_new(
        capture: CaptureArchiveRef,
        policy: PolicyArchiveRef,
        plan: PlanArchiveRef,
        contract_schema: Option<ContractSchemaArchiveRef>,
        documents: Vec<ArchivedDocumentInput>,
    ) -> Result<Self, EvaluationRunError> {
        let record = Self {
            capture,
            policy,
            plan,
            contract_schema,
            documents,
        };
        record.validate()?;
        Ok(record)
    }

    pub fn validate(&self) -> Result<(), EvaluationRunError> {
        if self.documents.is_empty() {
            return Err(EvaluationRunError::NoDocuments);
        }
        let observed = u64::try_from(self.documents.len()).map_err(|_| {
            EvaluationRunError::TooManyDocuments {
                maximum: MAX_EVALUATION_DOCUMENTS,
                observed: u64::MAX,
            }
        })?;
        if observed > MAX_EVALUATION_DOCUMENTS {
            return Err(EvaluationRunError::TooManyDocuments {
                maximum: MAX_EVALUATION_DOCUMENTS,
                observed,
            });
        }
        let mut seen = BTreeSet::new();
        for input in &self.documents {
            if !seen.insert(input.document.clone()) {
                return Err(EvaluationRunError::DuplicateDocument {
                    document: input.document.clone(),
                });
            }
            if input.source_artifact.is_some_and(|artifact| {
                artifact.as_untyped().activity_id() != self.capture.capture_id().activity_id()
            }) {
                return Err(EvaluationRunError::ForeignSourceArtifact);
            }
        }
        Ok(())
    }

    pub const fn capture(&self) -> &CaptureArchiveRef {
        &self.capture
    }

    pub const fn policy(&self) -> &PolicyArchiveRef {
        &self.policy
    }

    pub const fn plan(&self) -> &PlanArchiveRef {
        &self.plan
    }

    pub const fn contract_schema(&self) -> Option<&ContractSchemaArchiveRef> {
        self.contract_schema.as_ref()
    }

    pub fn documents(&self) -> &[ArchivedDocumentInput] {
        &self.documents
    }
}

impl<'de> Deserialize<'de> for EvaluationRunRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            capture: CaptureArchiveRef,
            policy: PolicyArchiveRef,
            plan: PlanArchiveRef,
            #[serde(default)]
            contract_schema: Option<ContractSchemaArchiveRef>,
            documents: Vec<ArchivedDocumentInput>,
        }

        let wire = Wire::deserialize(deserializer)?;
        Self::try_new(
            wire.capture,
            wire.policy,
            wire.plan,
            wire.contract_schema,
            wire.documents,
        )
        .map_err(D::Error::custom)
    }
}

#[derive(Clone, Debug, Error, Eq, PartialEq)]
pub enum EvaluationRunError {
    #[error("an EvaluationRunRecord requires at least one archived Document")]
    NoDocuments,
    #[error("an EvaluationRunRecord permits at most {maximum} Documents, observed {observed}")]
    TooManyDocuments { maximum: u64, observed: u64 },
    #[error("archived Document {document} appears more than once in the evaluation order")]
    DuplicateDocument { document: DocumentArchiveRef },
    #[error("source artifact provenance must belong to the EvaluationRun Capture")]
    ForeignSourceArtifact,
}

impl sealed::Value for EvaluationRunRecord {}

impl ArchiveValue for EvaluationRunRecord {
    type Reference = EvaluationRunArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        value
            .validate()
            .map_err(ArchiveError::InvalidEvaluationRun)?;
        validate_references(archive, value).await?;
        let reference = EvaluationRunArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::EvaluationRun,
                EVALUATION_RUN_RECORD_VERSION,
                reference.key(),
                value,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for EvaluationRunArchiveRef {}

impl ArchiveReference for EvaluationRunArchiveRef {
    type Value = EvaluationRunRecord;

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
        let record: EvaluationRunRecord = archive
            .read_record(
                RecordKind::EvaluationRun,
                EVALUATION_RUN_RECORD_VERSION,
                reference.key(),
            )
            .await?;
        validate_references(archive, &record).await?;
        Ok(record)
    }
}

async fn validate_references(
    archive: &Archive,
    record: &EvaluationRunRecord,
) -> Result<(), ArchiveError> {
    let capture: CaptureBundle = archive.read(&record.capture).await?;
    let _ = archive.read(&record.policy).await?;
    let _ = archive.read(&record.plan).await?;
    if let Some(schema) = &record.contract_schema {
        let _ = archive.read(schema).await?;
    }
    for input in &record.documents {
        let _ = archive.read(&input.document).await?;
        if let Some(artifact) = input.source_artifact
            && capture.payload(artifact).is_none()
        {
            return Err(ArchiveError::EvaluationSourcePayloadUnavailable { artifact });
        }
    }
    Ok(())
}
