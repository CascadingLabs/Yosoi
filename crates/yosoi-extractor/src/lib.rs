//! Deterministic Contract-aware assembly over landed locator findings.
//!
//! Extraction preserves candidate values and evidence. It performs no value
//! conversion, cardinality enforcement, defaults, or semantic validation.

use serde::Serialize;
use std::collections::{BTreeMap, HashMap};
use std::fmt::{self, Formatter};
use thiserror::Error;
use yosoi_contracts::{
    CandidateInput, Contract, ContractSchema, ContractSchemaError, FieldId, RecordScope,
};
use yosoi_documents::{
    DocumentId, IncompleteEvidence, LocateFailure, LocateOutcome, OutputId, RegionLineage,
};

mod limits;

use limits::{check_len, check_next_len, increment};

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

#[derive(Clone, Debug, Eq, Hash, PartialEq)]
enum RecordKey {
    Page,
    Region(RegionLineage),
}

#[derive(Clone, Debug)]
struct CandidateBuilder {
    key: RecordKey,
    fields: BTreeMap<FieldId, Vec<yosoi_documents::Finding>>,
}

impl CandidateBuilder {
    const fn new(key: RecordKey) -> Self {
        Self {
            key,
            fields: BTreeMap::new(),
        }
    }

    fn push(
        &mut self,
        field: FieldId,
        finding: &yosoi_documents::Finding,
        limits: ExtractionLimits,
        retained_evidence: &mut u64,
    ) -> Result<(), ExtractionFailure> {
        let values = self.fields.entry(field).or_default();
        check_next_len(
            values.len(),
            ExtractionLimit::ValuesPerField,
            limits.max_values_per_field,
        )?;
        increment(
            retained_evidence,
            ExtractionLimit::RetainedEvidence,
            limits.max_retained_evidence,
        )?;
        values.push(finding.clone());
        Ok(())
    }
}

pub fn extract_contract_with_limit<T: Contract>(
    located: &LocateOutcome,
    maximum_findings: u64,
) -> Extracted<T> {
    extract_contract_with_limits(located, ExtractionLimits::uniform(maximum_findings))
}

#[doc(hidden)]
pub fn extract_contract_with_limits<T: Contract>(
    located: &LocateOutcome,
    limits: ExtractionLimits,
) -> Extracted<T> {
    match located {
        LocateOutcome::Matched { result } => match T::schema() {
            Ok(schema) => extract_findings::<T>(
                schema,
                result.document_id(),
                result.regions(),
                result.findings(),
                limits,
            ),
            Err(error) => Extracted::Rejected {
                failure: ExtractionFailure::InvalidContractSchema(error),
            },
        },
        LocateOutcome::NoMatch { document_id } => Extracted::NoMatch {
            document_id: document_id.clone(),
        },
        LocateOutcome::Indeterminate {
            document_id,
            completeness,
            reason_code,
        } => Extracted::Indeterminate {
            document_id: document_id.clone(),
            completeness: completeness.clone(),
            reason_code: reason_code.clone(),
        },
        LocateOutcome::Failed { failure } => Extracted::LocateFailed {
            failure: failure.clone(),
        },
    }
}

/// Extracts candidates from a validated runtime schema using the shared
/// grouping and resource accounting path used by derive-backed Contracts.
#[doc(hidden)]
pub fn extract_schema_with_limits(
    schema: &ContractSchema,
    located: &LocateOutcome,
    limits: ExtractionLimits,
) -> SchemaExtracted {
    match located {
        LocateOutcome::Matched { result } => extract_candidates(
            schema,
            result.document_id(),
            result.regions(),
            result.findings(),
            limits,
        ),
        LocateOutcome::NoMatch { document_id } => SchemaExtracted::NoMatch {
            document_id: document_id.clone(),
        },
        LocateOutcome::Indeterminate {
            document_id,
            completeness,
            reason_code,
        } => SchemaExtracted::Indeterminate {
            document_id: document_id.clone(),
            completeness: completeness.clone(),
            reason_code: reason_code.clone(),
        },
        LocateOutcome::Failed { failure } => SchemaExtracted::LocateFailed {
            failure: failure.clone(),
        },
    }
}

fn extract_findings<T: Contract>(
    schema: &ContractSchema,
    document_id: &DocumentId,
    regions: &[RegionLineage],
    findings: &[yosoi_documents::Finding],
    limits: ExtractionLimits,
) -> Extracted<T> {
    match extract_candidates(schema, document_id, regions, findings, limits) {
        SchemaExtracted::Candidates {
            document_id,
            candidates,
            diagnostics,
        } => Extracted::Candidates {
            document_id,
            candidates: candidates.iter().map(T::candidate_from).collect(),
            diagnostics,
        },
        SchemaExtracted::Rejected { failure } => Extracted::Rejected { failure },
        SchemaExtracted::NoMatch { document_id } => Extracted::NoMatch { document_id },
        SchemaExtracted::Indeterminate {
            document_id,
            completeness,
            reason_code,
        } => Extracted::Indeterminate {
            document_id,
            completeness,
            reason_code,
        },
        SchemaExtracted::LocateFailed { failure } => Extracted::LocateFailed { failure },
    }
}

fn extract_candidates(
    schema: &ContractSchema,
    document_id: &DocumentId,
    regions: &[RegionLineage],
    findings: &[yosoi_documents::Finding],
    limits: ExtractionLimits,
) -> SchemaExtracted {
    let mut builders = Vec::<CandidateBuilder>::new();
    let mut builder_indices = HashMap::<RecordKey, usize>::new();
    let mut diagnostics = Vec::new();
    let mut scanned_findings = 0_u64;
    let mut matching_findings = 0_u64;
    let mut retained_evidence = 0_u64;
    let mut diagnostic_count = 0_u64;

    if let Err(failure) = check_len(
        regions.len(),
        ExtractionLimit::ScannedRegions,
        limits.max_scanned_regions,
    ) {
        return SchemaExtracted::Rejected { failure };
    }

    if schema.scope() == RecordScope::Repeated {
        for region in regions
            .iter()
            .filter(|region| region.region_id().as_str() == schema.id().as_str())
        {
            if let Err(failure) = check_next_len(
                builders.len(),
                ExtractionLimit::Candidates,
                limits.max_candidates,
            ) {
                return SchemaExtracted::Rejected { failure };
            }
            let key = RecordKey::Region(region.clone());
            let index = builders.len();
            if builder_indices.insert(key.clone(), index).is_some() {
                return SchemaExtracted::Rejected {
                    failure: ExtractionFailure::GroupingIndexInvariant,
                };
            }
            builders.push(CandidateBuilder::new(key));
        }
    }

    for finding in findings {
        if let Err(failure) = increment(
            &mut scanned_findings,
            ExtractionLimit::ScannedFindings,
            limits.max_scanned_findings,
        ) {
            return SchemaExtracted::Rejected { failure };
        }
        let Some(field) = schema.field_for_output(finding.output_id()) else {
            continue;
        };
        if let Err(failure) = increment(
            &mut matching_findings,
            ExtractionLimit::MatchingFindings,
            limits.max_matching_findings,
        ) {
            return SchemaExtracted::Rejected { failure };
        }
        let key = match (schema.scope(), finding.parent_region()) {
            (RecordScope::Page, None) => RecordKey::Page,
            (RecordScope::Repeated, Some(region))
                if region.region_id().as_str() == schema.id().as_str() =>
            {
                RecordKey::Region(region.clone())
            }
            _ => {
                if let Err(failure) = increment(
                    &mut diagnostic_count,
                    ExtractionLimit::Diagnostics,
                    limits.max_diagnostics,
                ) {
                    return SchemaExtracted::Rejected { failure };
                }
                diagnostics.push(ExtractionDiagnostic::IncompatibleLineage {
                    output: finding.output_id().clone(),
                });
                continue;
            }
        };

        if let Some(index) = builder_indices.get(&key).copied() {
            let Some(builder) = builders.get_mut(index) else {
                return SchemaExtracted::Rejected {
                    failure: ExtractionFailure::GroupingIndexInvariant,
                };
            };
            if let Err(failure) =
                builder.push(field.id().clone(), finding, limits, &mut retained_evidence)
            {
                return SchemaExtracted::Rejected { failure };
            }
        } else {
            if let Err(failure) = check_next_len(
                builders.len(),
                ExtractionLimit::Candidates,
                limits.max_candidates,
            ) {
                return SchemaExtracted::Rejected { failure };
            }
            let mut builder = CandidateBuilder::new(key);
            if let Err(failure) =
                builder.push(field.id().clone(), finding, limits, &mut retained_evidence)
            {
                return SchemaExtracted::Rejected { failure };
            }
            let index = builders.len();
            builder_indices.insert(builder.key.clone(), index);
            builders.push(builder);
        }
    }

    let candidates = builders
        .into_iter()
        .map(|builder| {
            let region = match builder.key {
                RecordKey::Page => None,
                RecordKey::Region(region) => Some(region),
            };
            CandidateInput::new(document_id.clone(), region, builder.fields)
        })
        .collect();

    SchemaExtracted::Candidates {
        document_id: document_id.clone(),
        candidates,
        diagnostics,
    }
}
