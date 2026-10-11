use crate::internal::contracts::{ContractSchema, ContractSchemaError, FieldId};
use crate::internal::documents::{DocumentId, Finding, ProjectedValue, RegionLineage};
use serde::{Deserialize, Serialize};
use std::collections::BTreeMap;
use std::fmt::{self, Formatter};
use std::marker::PhantomData;

#[doc(hidden)]
#[derive(Clone, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct CandidateInput {
    document_id: DocumentId,
    region: Option<RegionLineage>,
    fields: BTreeMap<FieldId, Vec<Finding>>,
}

impl fmt::Debug for CandidateInput {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CandidateInput")
            .field("has_region", &self.region.is_some())
            .field("field_count", &self.fields.len())
            .finish_non_exhaustive()
    }
}

impl CandidateInput {
    pub const fn new(
        document_id: DocumentId,
        region: Option<RegionLineage>,
        fields: BTreeMap<FieldId, Vec<Finding>>,
    ) -> Self {
        Self {
            document_id,
            region,
            fields,
        }
    }
    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    pub const fn region(&self) -> Option<&RegionLineage> {
        self.region.as_ref()
    }
    pub fn findings(&self, field: &FieldId) -> &[Finding] {
        self.fields.get(field).map_or(&[], Vec::as_slice)
    }
    pub const fn fields(&self) -> &BTreeMap<FieldId, Vec<Finding>> {
        &self.fields
    }
}

/// Owned field evidence for one runtime-described Contract candidate.
pub type RuntimeCandidate = CandidateInput;

/// Owned ordered findings for one field before conversion to the declared type `T`.
pub struct CandidateField<T> {
    id: FieldId,
    findings: Vec<Finding>,
    value_type: PhantomData<fn() -> T>,
}

impl<T> Clone for CandidateField<T> {
    fn clone(&self) -> Self {
        Self {
            id: self.id.clone(),
            findings: self.findings.clone(),
            value_type: PhantomData,
        }
    }
}

impl<T> fmt::Debug for CandidateField<T> {
    fn fmt(&self, formatter: &mut Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CandidateField")
            .field("id", &self.id)
            .field("candidate_count", &self.findings.len())
            .finish_non_exhaustive()
    }
}

impl<T> CandidateField<T> {
    #[doc(hidden)]
    pub fn from_input(id: &'static str, input: &CandidateInput) -> Self {
        let id = FieldId::from_derive(id);
        Self {
            findings: input.findings(&id).to_vec(),
            id,
            value_type: PhantomData,
        }
    }
    #[doc(hidden)]
    pub fn from_runtime(id: FieldId, findings: &[Finding]) -> Self {
        Self {
            id,
            findings: findings.to_vec(),
            value_type: PhantomData,
        }
    }
    /// Borrows the authored field identity associated with these findings.
    pub const fn id(&self) -> &FieldId {
        &self.id
    }
    /// Iterates borrowed projection values in evidence order without converting them to `T`.
    pub fn values(&self) -> impl ExactSizeIterator<Item = &ProjectedValue> {
        self.findings.iter().map(Finding::value)
    }
    /// Borrows original findings, including coordinates and evidence completeness.
    pub fn evidence(&self) -> &[Finding] {
        &self.findings
    }
    /// Returns whether no findings are retained, without asserting complete document absence.
    pub const fn is_absent(&self) -> bool {
        self.findings.is_empty()
    }
    /// Returns whether the finding collection is empty; inspect terminal and completeness states separately.
    pub const fn is_empty(&self) -> bool {
        self.findings.is_empty()
    }
    /// Returns retained finding count, not an accepted or converted value count.
    pub const fn len(&self) -> usize {
        self.findings.len()
    }
}

#[doc(hidden)]
pub trait CandidateView: Clone {
    fn document_id(&self) -> &DocumentId;
    fn region(&self) -> Option<&RegionLineage>;
    fn value_count(&self) -> Option<u64>;
}

/// Typed record schema linking authored meaning to generated candidate evidence.
///
/// Implemented by the public Contract derive. Schema declaration does not
/// locate evidence or validate values; extraction and validation are explicit phases.
pub trait Contract: Sized {
    /// Owned generated candidate shape holding field findings and grouping provenance.
    type Candidate: CandidateView;
    #[doc(hidden)]
    type Extracted;
    /// Borrows stable portable metadata, returning a schema error for invalid declarations.
    fn schema() -> Result<&'static ContractSchema, ContractSchemaError>;
    #[doc(hidden)]
    fn candidate_from(input: &CandidateInput) -> Self::Candidate;
}
