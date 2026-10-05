//! Derive-backed Contract declarations and portable schema metadata.
//!
//! Contracts define record meaning. They do not locate evidence, assemble
//! candidates, convert runtime values, or validate records.

mod candidate;
mod ids;
mod schema;

pub use candidate::{CandidateField, CandidateInput, CandidateView, Contract, RuntimeCandidate};
pub use ids::{ContractId, ContractSchemaError, FieldId};
pub use schema::{
    CONTRACT_SCHEMA_VERSION, Cardinality, ContractIdentity, ContractSchema, ContractValue,
    FieldSchema, RecordScope,
};
