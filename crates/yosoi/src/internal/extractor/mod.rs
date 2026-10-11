//! Deterministic Contract-aware assembly over landed locator findings.
//!
//! Extraction preserves candidate values and evidence. It performs no value
//! conversion, cardinality enforcement, defaults, or semantic validation.

use crate::internal::contracts::{CandidateInput, Contract, ContractSchemaError};
use crate::internal::documents::{DocumentId, IncompleteEvidence, LocateFailure, OutputId};
use serde::Serialize;
use std::fmt::{self, Formatter};
use thiserror::Error;

mod execution;
mod limits;

pub use execution::extract_contract_with_limit;
#[doc(hidden)]
pub use execution::{extract_contract_with_limits, extract_schema_with_limits};

pub enum Extracted<T: Contract> {
    Candidates {
        document_id: DocumentId,
        candidates: Vec<T::Candidate>,
        diagnostics: Vec<ExtractionDiagnostic>,
    },
    NoMatch {
        document_id: DocumentId,
    },
    Indeterminate {
        document_id: DocumentId,
        completeness: IncompleteEvidence,
        reason_code: String,
    },
    LocateFailed {
        failure: LocateFailure,
    },
    Rejected {
        failure: ExtractionFailure,
    },
}

/// Schema-driven candidates shared by derive-backed and runtime Contracts.
#[doc(hidden)]
#[derive(Clone, Debug, Serialize)]
#[serde(tag = "status", rename_all = "snake_case")]
pub enum SchemaExtracted {
    Candidates {
        document_id: DocumentId,
        candidates: Vec<CandidateInput>,
        diagnostics: Vec<ExtractionDiagnostic>,
    },
    NoMatch {
        document_id: DocumentId,
    },
    Indeterminate {
        document_id: DocumentId,
        completeness: IncompleteEvidence,
        reason_code: String,
    },
    LocateFailed {
        failure: LocateFailure,
    },
    Rejected {
        failure: ExtractionFailure,
    },
}

impl<T: Contract> fmt::Debug for Extracted<T> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        match self {
            Self::Candidates {
                candidates,
                diagnostics,
                ..
            } => formatter
                .debug_struct("Extracted::Candidates")
                .field("candidate_count", &candidates.len())
                .field("diagnostic_count", &diagnostics.len())
                .finish_non_exhaustive(),
            Self::NoMatch { .. } => formatter
                .debug_struct("Extracted::NoMatch")
                .finish_non_exhaustive(),
            Self::Indeterminate { .. } => formatter
                .debug_struct("Extracted::Indeterminate")
                .finish_non_exhaustive(),
            Self::LocateFailed { .. } => formatter
                .debug_struct("Extracted::LocateFailed")
                .finish_non_exhaustive(),
            Self::Rejected { failure } => formatter
                .debug_tuple("Extracted::Rejected")
                .field(failure)
                .finish(),
        }
    }
}

impl<T: Contract> Extracted<T> {
    pub fn candidates(&self) -> &[T::Candidate] {
        match self {
            Self::Candidates { candidates, .. } => candidates,
            _ => &[],
        }
    }

    pub fn diagnostics(&self) -> &[ExtractionDiagnostic] {
        match self {
            Self::Candidates { diagnostics, .. } => diagnostics,
            _ => &[],
        }
    }
}

#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ExtractionDiagnostic {
    IncompatibleLineage { output: OutputId },
}

#[doc(hidden)]
#[derive(Clone, Copy, Debug, Eq, PartialEq)]
pub struct ExtractionLimits {
    pub max_scanned_regions: u64,
    pub max_scanned_findings: u64,
    pub max_matching_findings: u64,
    pub max_candidates: u64,
    pub max_values_per_field: u64,
    pub max_retained_evidence: u64,
    pub max_diagnostics: u64,
}

impl ExtractionLimits {
    pub const fn uniform(maximum: u64) -> Self {
        Self {
            max_scanned_regions: maximum,
            max_scanned_findings: maximum,
            max_matching_findings: maximum,
            max_candidates: maximum,
            max_values_per_field: maximum,
            max_retained_evidence: maximum,
            max_diagnostics: maximum,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtractionLimit {
    ScannedRegions,
    ScannedFindings,
    MatchingFindings,
    Candidates,
    ValuesPerField,
    RetainedEvidence,
    Diagnostics,
}

#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ExtractionFailure {
    #[error(transparent)]
    InvalidContractSchema(#[from] ContractSchemaError),
    #[error("extraction {limit:?} count cannot be represented as u64")]
    CountOverflow { limit: ExtractionLimit },
    #[error("extraction grouping index no longer matches candidate order")]
    GroupingIndexInvariant,
    #[error("extraction {limit:?} limit exceeded: maximum {maximum}, observed {observed}")]
    LimitExceeded {
        limit: ExtractionLimit,
        maximum: u64,
        observed: u64,
    },
}

impl Serialize for ExtractionFailure {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        use serde::ser::SerializeStruct;
        let mut state = serializer.serialize_struct("ExtractionFailure", 4)?;
        match self {
            Self::InvalidContractSchema(error) => {
                state.serialize_field("kind", "invalid_contract_schema")?;
                state.serialize_field("message", &error.to_string())?;
            }
            Self::CountOverflow { limit } => {
                state.serialize_field("kind", "count_overflow")?;
                state.serialize_field("limit", limit)?;
            }
            Self::GroupingIndexInvariant => {
                state.serialize_field("kind", "grouping_index_invariant")?;
            }
            Self::LimitExceeded {
                limit,
                maximum,
                observed,
            } => {
                state.serialize_field("kind", "limit_exceeded")?;
                state.serialize_field("limit", limit)?;
                state.serialize_field("maximum", maximum)?;
                state.serialize_field("observed", observed)?;
            }
        }
        state.end()
    }
}

#[cfg(test)]
mod integration_tests;
