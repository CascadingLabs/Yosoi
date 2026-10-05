//! Explicit runtime validation from model-shaped candidates into Rust values.

mod issue;
mod outcome;
#[doc(hidden)]
pub mod portable;
mod runtime;
mod validation;
mod value;

#[doc(hidden)]
pub use issue::FieldIssueDraft;
pub use issue::{ContractIssues, FieldIssue, FieldIssueKind, ValidationCode, ValidationFailure};
pub use outcome::{ContractOutcome, RecordIssue, ValidatedRecord};
pub use portable::ArchivedContract;
pub use runtime::{
    RuntimeContract, RuntimeContractError, RuntimeContractOutcome, RuntimeExtracted,
    RuntimeFieldValue, RuntimeRecordIssue, RuntimeValidatedRecord, RuntimeValue,
};
pub use validation::{MAX_CONTRACT_FIELDS, MAX_VALIDATED_RECORDS};
#[doc(hidden)]
pub use validation::{ValidationBudget, ValidationLimits, read_many, read_optional, read_required};
#[doc(hidden)]
pub use value::RuntimeContractValue;
pub use value::{Currency, Money, RuntimeValueIssue};

/// Code-independent values used to inspect or manually implement archived Contracts.
pub mod archived {
    pub use super::portable::{
        PortableCandidateField as CandidateField,
        PortableContractDecodeError as ContractDecodeError, PortableContractField as ContractField,
        PortableContractFieldValue as ContractFieldValue,
        PortableContractOutcome as ContractOutcome,
        PortableContractRecordIssue as ContractRecordIssue, PortableContractValue as ContractValue,
        PortableExtractionDiagnostic as ExtractionDiagnostic,
        PortableExtractionFailure as ExtractionFailure, PortableExtractionLimit as ExtractionLimit,
        PortableFieldIssue as FieldIssue, PortableFieldIssueKind as FieldIssueKind,
        PortableValidatedContractRecord as ValidatedContractRecord,
        PortableValidationCode as ValidationCode, PortableValidationFailure as ValidationFailure,
    };
}

/// Model-shaped candidates awaiting explicit runtime validation.
pub type Extracted<T> = <T as yosoi_contracts::Contract>::Extracted;
