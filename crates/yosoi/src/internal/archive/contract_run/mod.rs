use std::{collections::BTreeSet, fmt};

use crate::internal::contract_validation::{ArchivedContract, ContractOutcome, portable};
use crate::internal::contracts::{ContractSchema, FieldId};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use crate::internal::archive::{ContractSchemaArchiveRef, LocatorRunArchiveRef};

mod archive;
mod error;

pub use error::ContractRunRecordError;
pub use portable::{
    PortableCandidateField as ArchivedCandidateField,
    PortableContractField as ArchivedContractField,
    PortableContractFieldValue as ArchivedContractFieldValue,
    PortableContractOutcome as ArchivedContractOutcome,
    PortableContractRecordIssue as ArchivedContractRecordIssue,
    PortableContractValue as ArchivedContractValue,
    PortableExtractionDiagnostic as ArchivedExtractionDiagnostic,
    PortableExtractionFailure as ArchivedExtractionFailure,
    PortableExtractionLimit as ArchivedExtractionLimit, PortableFieldIssue as ArchivedFieldIssue,
    PortableFieldIssueKind as ArchivedFieldIssueKind,
    PortableValidatedContractRecord as ArchivedValidatedContractRecord,
    PortableValidationCode as ArchivedValidationCode,
    PortableValidationFailure as ArchivedValidationFailure,
};

use portable::{
    PortableCandidateField, PortableContractField, PortableContractOutcome, PortableFieldIssue,
};

/// Immutable result of applying one Contract to one archived LocatorRun.
///
/// The record stores a self-describing ContractSchema snapshot so callers can
/// inspect the file directly and recover typed values without separately
/// loading or passing schema data. The typed schema reference remains as
/// provenance and is checked whenever Archive reads or writes this record.
#[derive(Clone, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ContractRunRecord {
    locator_run: LocatorRunArchiveRef,
    contract_schema: ContractSchemaArchiveRef,
    schema: ContractSchema,
    outcome: PortableContractOutcome,
}

impl fmt::Debug for ContractRunRecord {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ContractRunRecord")
            .field("locator_run", &self.locator_run)
            .field("contract_schema", &self.contract_schema)
            .field("outcome_status", &self.outcome.status())
            .finish_non_exhaustive()
    }
}

impl ContractRunRecord {
    /// Captures a typed Contract outcome without exposing Archive codecs.
    pub fn new<T>(
        locator_run: LocatorRunArchiveRef,
        contract_schema: ContractSchemaArchiveRef,
        outcome: &ContractOutcome<T>,
    ) -> Result<Self, ContractRunRecordError>
    where
        T: ArchivedContract,
    {
        let schema = T::schema()
            .map_err(|source| ContractRunRecordError::InvalidContractSchema { source })?
            .clone();
        Self::from_archived_parts(locator_run, contract_schema, schema, outcome.to_archived())
    }

    /// Restores every successfully validated Contract value in record order.
    ///
    /// Validation issues and terminal failures remain available on `outcome`;
    /// this method returns only values which passed validation originally.
    pub fn values<T>(&self) -> Result<Vec<T>, ContractRunRecordError>
    where
        T: ArchivedContract,
    {
        let compiled =
            T::schema().map_err(|_| ContractRunRecordError::InvalidCompiledContractSchema)?;
        let compiled_identity = compiled
            .identity()
            .map_err(|_| ContractRunRecordError::InvalidCompiledContractSchema)?;
        let archived_identity = self
            .schema
            .identity()
            .map_err(|source| ContractRunRecordError::InvalidContractSchema { source })?;
        if compiled_identity != archived_identity {
            return Err(ContractRunRecordError::CompiledContractSchemaMismatch);
        }
        let PortableContractOutcome::Evaluated { records, .. } = &self.outcome else {
            return Ok(Vec::new());
        };
        records
            .iter()
            .map(|record| {
                record
                    .decode(&self.schema)
                    .map_err(ContractRunRecordError::from_decode)
            })
            .collect()
    }

    pub const fn locator_run(&self) -> &LocatorRunArchiveRef {
        &self.locator_run
    }

    pub const fn contract_schema(&self) -> &ContractSchemaArchiveRef {
        &self.contract_schema
    }

    /// Returns the schema snapshot stored beside this result.
    pub const fn schema(&self) -> &ContractSchema {
        &self.schema
    }

    /// Returns the code-independent archived outcome for inspection and tools.
    pub const fn outcome(&self) -> &ArchivedContractOutcome {
        &self.outcome
    }

    pub(in crate::internal::archive) fn from_archived_parts(
        locator_run: LocatorRunArchiveRef,
        contract_schema: ContractSchemaArchiveRef,
        schema: ContractSchema,
        outcome: PortableContractOutcome,
    ) -> Result<Self, ContractRunRecordError> {
        let record = Self {
            locator_run,
            contract_schema,
            schema,
            outcome,
        };
        record.validate_shape()?;
        Ok(record)
    }

    pub(in crate::internal::archive) fn validate_shape(
        &self,
    ) -> Result<(), ContractRunRecordError> {
        if let PortableContractOutcome::Evaluated {
            records, issues, ..
        } = &self.outcome
        {
            for record in records {
                validate_unique_fields(record.fields().iter().map(PortableContractField::id))?;
                validate_unique_fields(record.evidence().iter().map(PortableCandidateField::id))?;
            }
            for issue in issues {
                if issue.fields().is_empty() {
                    return Err(ContractRunRecordError::EmptyRecordIssue);
                }
                validate_unique_fields(issue.fields().iter().map(PortableFieldIssue::field))?;
                validate_unique_fields(
                    issue
                        .candidate_fields()
                        .iter()
                        .map(PortableCandidateField::id),
                )?;
            }
        }
        Ok(())
    }
}

#[cfg(test)]
mod tests;

impl<'de> Deserialize<'de> for ContractRunRecord {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct Wire {
            locator_run: LocatorRunArchiveRef,
            contract_schema: ContractSchemaArchiveRef,
            schema: ContractSchema,
            outcome: PortableContractOutcome,
        }
        let wire = Wire::deserialize(deserializer)?;
        Self::from_archived_parts(
            wire.locator_run,
            wire.contract_schema,
            wire.schema,
            wire.outcome,
        )
        .map_err(D::Error::custom)
    }
}

fn validate_unique_fields<'a>(
    fields: impl Iterator<Item = &'a FieldId>,
) -> Result<(), ContractRunRecordError> {
    let mut seen = BTreeSet::new();
    for field in fields {
        if !seen.insert(field.clone()) {
            return Err(ContractRunRecordError::DuplicateField {
                field: field.clone(),
            });
        }
    }
    Ok(())
}
