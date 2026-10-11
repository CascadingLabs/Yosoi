use std::iter::once;

use crate::internal::contract_validation::portable::{
    PortableCandidateField, PortableContractFieldValue, PortableContractOutcome,
    PortableContractRecordIssue, PortableContractValue, PortableExtractionDiagnostic,
    PortableFieldIssue, PortableValidatedContractRecord,
};
use crate::internal::contracts::{Cardinality, ContractSchema, FieldSchema};
use crate::internal::documents::LocateOutcome;

use super::{ContractRunRecord, ContractRunRecordError};
use crate::internal::archive::dispatch::{ArchiveReference, ArchiveValue, sealed};
use crate::internal::archive::wire::{ARCHIVE_FORMAT_VERSION, RecordKind};
use crate::internal::archive::{
    Archive, ArchiveError, ContractRunArchiveRef, EvaluationRunRecord, LocatorRunRecord,
};

const CONTRACT_RUN_RECORD_VERSION: u32 = 2;

impl sealed::Value for ContractRunRecord {}

impl ArchiveValue for ContractRunRecord {
    type Reference = ContractRunArchiveRef;

    async fn write_to<'a>(
        archive: &'a Archive,
        value: &'a Self,
    ) -> Result<Self::Reference, ArchiveError> {
        value
            .validate_shape()
            .map_err(ArchiveError::InvalidContractRun)?;
        validate_references(archive, value).await?;
        let reference = ContractRunArchiveRef::new_current();
        archive
            .write_record(
                RecordKind::ContractRun,
                CONTRACT_RUN_RECORD_VERSION,
                reference.key(),
                value,
            )
            .await?;
        Ok(reference)
    }
}

impl sealed::Reference for ContractRunArchiveRef {}

impl ArchiveReference for ContractRunArchiveRef {
    type Value = ContractRunRecord;

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
                RecordKind::ContractRun,
                CONTRACT_RUN_RECORD_VERSION,
                reference.key(),
            )
            .await?;
        validate_references(archive, &record).await?;
        Ok(record)
    }
}

async fn validate_references(
    archive: &Archive,
    record: &ContractRunRecord,
) -> Result<(), ArchiveError> {
    let locator: LocatorRunRecord = archive.read(record.locator_run()).await?;
    let evaluation: EvaluationRunRecord = archive.read(locator.evaluation()).await?;
    if evaluation.contract_schema() != Some(record.contract_schema()) {
        return invalid(ContractRunRecordError::ContractSchemaNotInEvaluation);
    }
    let schema: ContractSchema = archive.read(record.contract_schema()).await?;
    if &schema != record.schema() {
        return invalid(ContractRunRecordError::ContractSchemaSnapshotMismatch);
    }
    validate_terminal_outcome(locator.outcome(), record.outcome())?;
    validate_document(locator.outcome(), record.outcome())?;
    validate_locator_schema(&schema, locator.outcome())?;
    validate_schema(&schema, record.outcome())
}

fn validate_locator_schema(
    schema: &ContractSchema,
    outcome: &LocateOutcome,
) -> Result<(), ArchiveError> {
    let LocateOutcome::Matched { result } = outcome else {
        return Ok(());
    };
    if let Some(finding) = result.findings().iter().find(|finding| {
        !schema
            .fields()
            .iter()
            .any(|field| field.id().as_str() == finding.output_id().as_str())
    }) {
        return invalid(ContractRunRecordError::LocatorOutputNotInSchema {
            output: finding.output_id().clone(),
        });
    }
    Ok(())
}

fn validate_terminal_outcome(
    locator: &LocateOutcome,
    contract: &PortableContractOutcome,
) -> Result<(), ArchiveError> {
    let valid = matches!(
        (locator, contract),
        (
            LocateOutcome::Matched { .. },
            PortableContractOutcome::Evaluated { .. }
                | PortableContractOutcome::ExtractionRejected { .. }
                | PortableContractOutcome::ValidationRejected { .. }
        ) | (
            LocateOutcome::NoMatch { .. },
            PortableContractOutcome::NoMatch { .. }
        ) | (
            LocateOutcome::Indeterminate { .. },
            PortableContractOutcome::Indeterminate { .. }
        ) | (
            LocateOutcome::Failed { .. },
            PortableContractOutcome::LocateFailed { .. }
        )
    );
    if !valid {
        return invalid(ContractRunRecordError::LocatorOutcomeMismatch);
    }
    if let (
        LocateOutcome::Failed { failure: expected },
        PortableContractOutcome::LocateFailed { failure: found },
    ) = (locator, contract)
        && expected != found
    {
        return invalid(ContractRunRecordError::LocatorOutcomeMismatch);
    }
    if let (
        LocateOutcome::Indeterminate {
            completeness: expected_completeness,
            reason_code: expected_reason,
            ..
        },
        PortableContractOutcome::Indeterminate {
            completeness: found_completeness,
            reason_code: found_reason,
            ..
        },
    ) = (locator, contract)
        && (expected_completeness != found_completeness || expected_reason != found_reason)
    {
        return invalid(ContractRunRecordError::LocatorOutcomeMismatch);
    }
    Ok(())
}

fn validate_document(
    locator: &LocateOutcome,
    contract: &PortableContractOutcome,
) -> Result<(), ArchiveError> {
    let locator_document = match locator {
        LocateOutcome::Matched { result } => Some(result.document_id()),
        LocateOutcome::NoMatch { document_id }
        | LocateOutcome::Indeterminate { document_id, .. } => Some(document_id),
        LocateOutcome::Failed { .. } => None,
    };
    if let (Some(expected), Some(found)) = (locator_document, contract.document_id())
        && expected != found
    {
        return invalid(ContractRunRecordError::DocumentMismatch);
    }
    if let PortableContractOutcome::Evaluated {
        document_id,
        records,
        issues,
        ..
    } = contract
        && (records
            .iter()
            .any(|record| record.document_id() != document_id)
            || issues
                .iter()
                .any(|issue| issue.document_id() != document_id)
            || records
                .iter()
                .flat_map(PortableValidatedContractRecord::evidence)
                .chain(
                    issues
                        .iter()
                        .flat_map(PortableContractRecordIssue::candidate_fields),
                )
                .flat_map(PortableCandidateField::evidence)
                .any(|finding| finding.document_id() != document_id)
            || issues
                .iter()
                .flat_map(PortableContractRecordIssue::fields)
                .any(|field| {
                    field
                        .evidence()
                        .iter()
                        .any(|finding| finding.document_id() != document_id)
                }))
    {
        return invalid(ContractRunRecordError::IssueEvidenceDocumentMismatch);
    }
    if let (
        LocateOutcome::Matched { result },
        PortableContractOutcome::Evaluated {
            records, issues, ..
        },
    ) = (locator, contract)
        && records
            .iter()
            .filter_map(PortableValidatedContractRecord::region)
            .chain(
                issues
                    .iter()
                    .filter_map(PortableContractRecordIssue::region),
            )
            .any(|region| !result.regions().contains(region))
    {
        return invalid(ContractRunRecordError::UnknownRegion);
    }
    if let (
        LocateOutcome::Matched { result },
        PortableContractOutcome::Evaluated {
            records, issues, ..
        },
    ) = (locator, contract)
        && records
            .iter()
            .flat_map(PortableValidatedContractRecord::evidence)
            .chain(
                issues
                    .iter()
                    .flat_map(PortableContractRecordIssue::candidate_fields),
            )
            .flat_map(PortableCandidateField::evidence)
            .chain(
                issues
                    .iter()
                    .flat_map(PortableContractRecordIssue::fields)
                    .flat_map(PortableFieldIssue::evidence),
            )
            .any(|finding| !result.findings().contains(finding))
    {
        return invalid(ContractRunRecordError::EvidenceNotInLocatorRun);
    }
    Ok(())
}

fn validate_schema(
    schema: &ContractSchema,
    outcome: &PortableContractOutcome,
) -> Result<(), ArchiveError> {
    let PortableContractOutcome::Evaluated {
        records,
        issues,
        extraction_diagnostics,
        ..
    } = outcome
    else {
        return Ok(());
    };
    for record in records {
        if record.fields().len() != schema.fields().len() {
            return invalid(ContractRunRecordError::SchemaFieldMismatch);
        }
        for (field, expected) in record.fields().iter().zip(schema.fields()) {
            if field.id() != expected.id() {
                return invalid(ContractRunRecordError::SchemaFieldMismatch);
            }
            validate_field_value(expected, field.value())?;
        }
        validate_candidate_fields(schema, record.evidence())?;
    }
    for issue in issues {
        validate_candidate_fields(schema, issue.candidate_fields())?;
        for field in issue.fields() {
            if !schema
                .fields()
                .iter()
                .any(|schema| schema.id() == field.field())
            {
                return invalid(ContractRunRecordError::UnknownIssueField {
                    field: field.field().clone(),
                });
            }
            if field
                .evidence()
                .iter()
                .any(|finding| finding.output_id().as_str() != field.field().as_str())
            {
                return invalid(ContractRunRecordError::IssueEvidenceFieldMismatch);
            }
        }
    }
    for diagnostic in extraction_diagnostics {
        let PortableExtractionDiagnostic::IncompatibleLineage { output } = diagnostic;
        if !schema
            .fields()
            .iter()
            .any(|field| field.id().as_str() == output.as_str())
        {
            return invalid(ContractRunRecordError::UnknownDiagnosticOutput {
                output: output.clone(),
            });
        }
    }
    Ok(())
}

fn validate_candidate_fields(
    schema: &ContractSchema,
    fields: &[PortableCandidateField],
) -> Result<(), ArchiveError> {
    if fields.len() != schema.fields().len() {
        return invalid(ContractRunRecordError::SchemaFieldMismatch);
    }
    for (field, expected) in fields.iter().zip(schema.fields()) {
        if field.id() != expected.id() {
            return invalid(ContractRunRecordError::SchemaFieldMismatch);
        }
        if field
            .evidence()
            .iter()
            .any(|finding| finding.output_id().as_str() != field.id().as_str())
        {
            return invalid(ContractRunRecordError::IssueEvidenceFieldMismatch);
        }
    }
    Ok(())
}

fn validate_field_value(
    schema: &FieldSchema,
    value: &PortableContractFieldValue,
) -> Result<(), ArchiveError> {
    let cardinality_matches = matches!(
        (schema.cardinality(), value),
        (
            Cardinality::ExactlyOne,
            PortableContractFieldValue::ExactlyOne { .. }
        ) | (
            Cardinality::ZeroOrOne,
            PortableContractFieldValue::ZeroOrOne { .. }
        ) | (Cardinality::Many, PortableContractFieldValue::Many { .. })
    );
    if !cardinality_matches {
        return invalid(ContractRunRecordError::CardinalityMismatch {
            field: schema.id().clone(),
        });
    }
    let values: Box<dyn Iterator<Item = &PortableContractValue> + '_> = match value {
        PortableContractFieldValue::ExactlyOne { value } => Box::new(once(value)),
        PortableContractFieldValue::ZeroOrOne { value } => Box::new(value.iter()),
        PortableContractFieldValue::Many { values } => Box::new(values.iter()),
    };
    for value in values {
        validate_scalar(schema, value)?;
    }
    Ok(())
}

fn validate_scalar(
    schema: &FieldSchema,
    value: &PortableContractValue,
) -> Result<(), ArchiveError> {
    match (schema.value_type(), value) {
        ("string", PortableContractValue::String { .. }) => Ok(()),
        ("money.usd", PortableContractValue::MoneyUsd { minor_units })
            if !minor_units.is_negative() =>
        {
            Ok(())
        }
        ("money.usd", PortableContractValue::MoneyUsd { .. }) => {
            invalid(ContractRunRecordError::InvalidArchivedScalar {
                field: schema.id().clone(),
            })
        }
        _ => invalid(ContractRunRecordError::ValueTypeMismatch {
            field: schema.id().clone(),
            expected: schema.value_type().to_owned(),
        }),
    }
}

const fn invalid<T>(error: ContractRunRecordError) -> Result<T, ArchiveError> {
    Err(ArchiveError::InvalidContractRun(error))
}
