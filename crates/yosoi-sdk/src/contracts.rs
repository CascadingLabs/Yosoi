//! Describe typed records and inspect extraction and validation outcomes.

pub use yosoi::{
    CandidateField, CandidateInput, CandidateView, Cardinality, Contract, ContractId,
    ContractIdentity, ContractLocatorError, ContractOutcome, ContractSchema, ContractSchemaError,
    ContractValue, Currency, Extracted, ExtractionDiagnostic, ExtractionFailure, ExtractionLimit,
    FieldId, FieldIssue, FieldIssueKind, FieldSchema, Money, RecordIssue, RecordScope,
    ValidatedRecord, ValidationCode, ValidationFailure,
};
