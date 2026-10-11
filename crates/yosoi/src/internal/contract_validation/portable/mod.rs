use crate::internal::contracts::FieldId;
use crate::internal::documents::{
    DocumentId, Finding, IncompleteEvidence, LocateFailure, OutputId, RegionLineage,
};
use serde::{Deserialize, Serialize};

mod conversion;
mod error;
mod evidence;

pub use conversion::{
    ArchivedContract, PortableContractFieldShape, PortableContractScalar,
    RuntimeContractArchiveError,
};
pub use error::PortableContractDecodeError;
pub use evidence::PortableCandidateField;

/// Closed portable scalar vocabulary for persisted Contract results.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "type", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableContractValue {
    String { value: String },
    MoneyUsd { minor_units: i64 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "cardinality", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableContractFieldValue {
    ExactlyOne {
        value: PortableContractValue,
    },
    ZeroOrOne {
        value: Option<PortableContractValue>,
    },
    Many {
        values: Vec<PortableContractValue>,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PortableContractField {
    id: FieldId,
    value: PortableContractFieldValue,
}

impl PortableContractField {
    pub const fn new(id: FieldId, value: PortableContractFieldValue) -> Self {
        Self { id, value }
    }

    pub const fn id(&self) -> &FieldId {
        &self.id
    }

    pub const fn value(&self) -> &PortableContractFieldValue {
        &self.value
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PortableValidatedContractRecord {
    document_id: DocumentId,
    region: Option<RegionLineage>,
    fields: Vec<PortableContractField>,
    evidence: Vec<PortableCandidateField>,
}

impl PortableValidatedContractRecord {
    pub const fn new(
        document_id: DocumentId,
        region: Option<RegionLineage>,
        fields: Vec<PortableContractField>,
        evidence: Vec<PortableCandidateField>,
    ) -> Self {
        Self {
            document_id,
            region,
            fields,
            evidence,
        }
    }

    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }

    pub const fn region(&self) -> Option<&RegionLineage> {
        self.region.as_ref()
    }

    pub fn fields(&self) -> &[PortableContractField] {
        &self.fields
    }

    pub fn evidence(&self) -> &[PortableCandidateField] {
        &self.evidence
    }
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PortableValidationCode {
    NegativeMoney,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableFieldIssueKind {
    MissingRequired,
    ExcessCandidates { observed: u64 },
    IncompleteEvidence,
    UnsupportedProjectedValue,
    ConversionFailed,
    SemanticValidationFailed { code: PortableValidationCode },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PortableFieldIssue {
    field: FieldId,
    kind: PortableFieldIssueKind,
    evidence: Vec<Finding>,
}

impl PortableFieldIssue {
    pub const fn new(field: FieldId, kind: PortableFieldIssueKind, evidence: Vec<Finding>) -> Self {
        Self {
            field,
            kind,
            evidence,
        }
    }

    pub const fn field(&self) -> &FieldId {
        &self.field
    }

    pub const fn kind(&self) -> &PortableFieldIssueKind {
        &self.kind
    }

    pub fn evidence(&self) -> &[Finding] {
        &self.evidence
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct PortableContractRecordIssue {
    document_id: DocumentId,
    region: Option<RegionLineage>,
    candidate_fields: Vec<PortableCandidateField>,
    fields: Vec<PortableFieldIssue>,
}

impl PortableContractRecordIssue {
    pub const fn new(
        document_id: DocumentId,
        region: Option<RegionLineage>,
        candidate_fields: Vec<PortableCandidateField>,
        fields: Vec<PortableFieldIssue>,
    ) -> Self {
        Self {
            document_id,
            region,
            candidate_fields,
            fields,
        }
    }

    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }

    pub const fn region(&self) -> Option<&RegionLineage> {
        self.region.as_ref()
    }

    pub fn fields(&self) -> &[PortableFieldIssue] {
        &self.fields
    }

    pub fn candidate_fields(&self) -> &[PortableCandidateField] {
        &self.candidate_fields
    }
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableExtractionDiagnostic {
    IncompatibleLineage { output: OutputId },
}

#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum PortableExtractionLimit {
    ScannedRegions,
    ScannedFindings,
    MatchingFindings,
    Candidates,
    ValuesPerField,
    RetainedEvidence,
    Diagnostics,
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableExtractionFailure {
    InvalidContractSchema,
    CountOverflow {
        limit: PortableExtractionLimit,
    },
    GroupingIndexInvariant,
    LimitExceeded {
        limit: PortableExtractionLimit,
        maximum: u64,
        observed: u64,
    },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableValidationFailure {
    InvalidContractSchema,
    FieldCountOverflow,
    FieldLimitExceeded { maximum: u64, observed: u64 },
    RecordCountOverflow,
    RecordLimitExceeded { maximum: u64, observed: u64 },
    ConversionCountOverflow,
    ConversionLimitExceeded { maximum: u64, observed: u64 },
    IssueCountOverflow,
    IssueLimitExceeded { maximum: u64, observed: u64 },
    ProvenanceCountOverflow,
    ProvenanceLimitExceeded { maximum: u64, observed: u64 },
}

#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum PortableContractOutcome {
    Evaluated {
        document_id: DocumentId,
        records: Vec<PortableValidatedContractRecord>,
        issues: Vec<PortableContractRecordIssue>,
        extraction_diagnostics: Vec<PortableExtractionDiagnostic>,
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
    ExtractionRejected {
        failure: PortableExtractionFailure,
    },
    ValidationRejected {
        failure: PortableValidationFailure,
    },
}

impl PortableContractOutcome {
    #[doc(hidden)]
    pub const fn status(&self) -> &'static str {
        match self {
            Self::Evaluated { .. } => "evaluated",
            Self::NoMatch { .. } => "no_match",
            Self::Indeterminate { .. } => "indeterminate",
            Self::LocateFailed { .. } => "locate_failed",
            Self::ExtractionRejected { .. } => "extraction_rejected",
            Self::ValidationRejected { .. } => "validation_rejected",
        }
    }

    pub const fn document_id(&self) -> Option<&DocumentId> {
        match self {
            Self::Evaluated { document_id, .. }
            | Self::NoMatch { document_id }
            | Self::Indeterminate { document_id, .. } => Some(document_id),
            Self::LocateFailed { .. }
            | Self::ExtractionRejected { .. }
            | Self::ValidationRejected { .. } => None,
        }
    }
}
