use crate::{ContractSchema, ContractSchemaError, FieldId};
use std::collections::BTreeMap;
use std::fmt::{self, Formatter};
use std::marker::PhantomData;
use yosoi_documents::{DocumentId, Finding, ProjectedValue, RegionLineage};

#[doc(hidden)]
#[derive(Clone)]
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
}

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
    pub const fn id(&self) -> &FieldId {
        &self.id
    }
    pub fn values(&self) -> impl ExactSizeIterator<Item = &ProjectedValue> {
        self.findings.iter().map(Finding::value)
    }
    pub fn evidence(&self) -> &[Finding] {
        &self.findings
    }
    pub const fn is_absent(&self) -> bool {
        self.findings.is_empty()
    }
    pub const fn is_empty(&self) -> bool {
        self.findings.is_empty()
    }
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

pub trait Contract: Sized {
    type Candidate: CandidateView;
    #[doc(hidden)]
    type Extracted;
    fn schema() -> Result<&'static ContractSchema, ContractSchemaError>;
    #[doc(hidden)]
    fn candidate_from(input: &CandidateInput) -> Self::Candidate;
}
