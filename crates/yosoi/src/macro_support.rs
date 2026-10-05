//! Linkage support for Contract derive expansions, not an authoring API.

pub use crate::contracts::{
    CandidateField, CandidateInput, CandidateView, Cardinality, Contract, ContractLocatorError,
    ContractOutcome, ContractSchema, ContractSchemaError, ContractValue, Extracted,
    ExtractionDiagnostic, FieldId, FieldSchema, RecordIssue, RecordScope, ValidatedRecord,
};
pub use crate::documents::{Document, DocumentId};
pub use crate::locators::{LocateOutcome, PinnedLocator, PinnedOutputLocator, Plan, RegionLineage};
pub use yosoi_engine::{
    ArchivedContract, ExtractorOutput, FieldIssueDraft, ValidationBudget, ValidationLimits,
    compile_contract_plan, extract_contract, extract_contract_with_limit, read_many, read_optional,
    read_required,
};
pub mod __private {
    pub use yosoi_engine::__private::{
        PortableCandidateField, PortableContractDecodeError, PortableContractField,
        PortableContractFieldShape, PortableContractScalar, PortableValidatedContractRecord,
    };
}
