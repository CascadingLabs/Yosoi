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

/// Candidate assembly result before cardinality, conversion, and semantic validation.
pub enum Extracted<T: Contract> {
    /// Located findings were grouped into candidates, possibly with nonfatal diagnostics.
    Candidates {
        /// Identity of the document supplying the grouped findings.
        document_id: DocumentId,
        /// Owned candidate evidence; values have not yet been converted or validated.
        candidates: Vec<T::Candidate>,
        /// Nonfatal grouping issues preventing an unqualified all-accepted claim.
        diagnostics: Vec<ExtractionDiagnostic>,
    },
    /// Complete locator evidence established no candidates within the requested scope.
    NoMatch {
        /// Document whose evidence supports this scope-specific absence claim.
        document_id: DocumentId,
    },
    /// Incomplete locator evidence prevents establishing candidate absence.
    Indeterminate {
        /// Identity of the examined evidence document.
        document_id: DocumentId,
        /// Partial or unknown coverage limiting the result.
        completeness: IncompleteEvidence,
        /// Structural explanation of why extraction remains indeterminate.
        reason_code: String,
    },
    /// Locator execution failed before usable candidate assembly.
    LocateFailed {
        /// Typed locator failure, distinct from complete no-match evidence.
        failure: LocateFailure,
    },
    /// Candidate assembly failed schema, accounting, or grouping checks.
    Rejected {
        /// Typed extraction rejection; this is not an accepted partial candidate set.
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
    /// Borrows assembled candidates, or an empty slice for other terminal states.
    ///
    /// This accessor alone cannot distinguish complete no-match, indeterminate
    /// evidence, or extraction failure. Inspect the enum before claiming absence.
    pub fn candidates(&self) -> &[T::Candidate] {
        match self {
            Self::Candidates { candidates, .. } => candidates,
            _ => &[],
        }
    }

    /// Borrows nonfatal candidate-grouping diagnostics when assembly produced candidates.
    /// Returns an empty slice for other states without claiming successful extraction.
    pub fn diagnostics(&self) -> &[ExtractionDiagnostic] {
        match self {
            Self::Candidates { diagnostics, .. } => diagnostics,
            _ => &[],
        }
    }
}

/// Nonfatal structural issue while mapping located findings into Contract candidate groups.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum ExtractionDiagnostic {
    /// Finding lineage is incompatible with the Contract's page or repeated-region grouping.
    IncompatibleLineage {
        /// Authored locator output whose evidence could not enter a compatible group.
        output: OutputId,
    },
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

/// Resource counter charged during candidate assembly, before value validation.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ExtractionLimit {
    /// Repeated-region lineage entries scanned for candidate grouping.
    ScannedRegions,
    /// Locator findings scanned while matching Contract output identifiers.
    ScannedFindings,
    /// Findings matching authored Contract fields and eligible for grouping.
    MatchingFindings,
    /// Distinct candidate records assembled from located evidence.
    Candidates,
    /// Finding values retained for one Contract field within a candidate.
    ValuesPerField,
    /// Finding evidence references retained across assembled candidates.
    RetainedEvidence,
    /// Nonfatal grouping diagnostics retained for caller inspection.
    Diagnostics,
}

/// Schema or resource failure rejecting candidate assembly as an operation.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum ExtractionFailure {
    /// The Contract schema fails structural validation before extraction can proceed.
    #[error(transparent)]
    InvalidContractSchema(#[from] ContractSchemaError),
    /// A resource count cannot fit the unsigned extraction accounting representation.
    #[error("extraction {limit:?} count cannot be represented as u64")]
    CountOverflow {
        /// Resource whose count could not be represented.
        limit: ExtractionLimit,
    },
    /// Grouping state no longer corresponds to deterministic candidate order.
    #[error("extraction grouping index no longer matches candidate order")]
    GroupingIndexInvariant,
    /// A configured assembly resource budget was exceeded.
    #[error("extraction {limit:?} limit exceeded: maximum {maximum}, observed {observed}")]
    LimitExceeded {
        /// Resource whose budget was exceeded.
        limit: ExtractionLimit,
        /// Maximum permitted count in units of that resource.
        maximum: u64,
        /// Recorded or attempted count in the same units.
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
