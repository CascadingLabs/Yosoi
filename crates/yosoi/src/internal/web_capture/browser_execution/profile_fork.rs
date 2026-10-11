//! Provider-neutral requests and receipts for bounded managed-profile forks.
//!
//! Fork receipts record lineage, quotas, and a requested child expiry. They do
//! not create a child lease: child tenancy and fencing must use the existing
//! [`crate::internal::web_capture::BrowserProfileLeaseGenerationRegistry`] and the
//! managed-profile lease flow.

use thiserror::Error;

mod failure;
mod identity;
mod receipt;
mod request;
mod validation;

pub use failure::*;
pub use identity::*;
pub use receipt::*;
pub use request::*;

/// Validation failures for a provider-neutral profile-fork request or receipt.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserProfileForkError {
    #[error("managed-profile fork maximum copy count is invalid")]
    InvalidMaximumCopies,
    #[error("managed-profile fork aggregate byte quota must be positive")]
    InvalidAggregateByteQuota,
    #[error("managed-profile checkpoint does not match the source lease")]
    CheckpointSourceMismatch,
    #[error("managed-profile lineage does not identify the request checkpoint")]
    LineageCheckpointMismatch,
    #[error("managed-profile child does not belong to the request lineage")]
    ChildLineageMismatch,
    #[error("managed-profile child count exceeds the resolved maximum")]
    ChildCountExceedsMaximum,
    #[error("managed-profile child identifiers are duplicated")]
    DuplicateChildIdentity,
    #[error("managed-profile child profile identifiers are duplicated")]
    DuplicateChildProfile,
    #[error("a child cannot use the source profile identifier")]
    ChildProfileMatchesSource,
    #[error("managed-profile source lease is not active at request creation")]
    SourceLeaseInactiveAtRequest,
    #[error("managed-profile source lease is not active yet")]
    SourceLeaseNotYetActive,
    #[error("managed-profile source lease has expired")]
    SourceLeaseExpired,
    #[error("managed-profile source generation is stale")]
    StaleSourceGeneration,
    #[error("managed-profile lease generation registry is unavailable")]
    GenerationRegistryUnavailable,
    #[error("managed-profile fork request is not active yet")]
    RequestNotYetActive,
    #[error("managed-profile child expiry must follow the request time")]
    InvalidChildExpiry,
    #[error("managed-profile child expiry has been reached")]
    ChildExpiryReached,
    #[error("managed-profile fork completed before the request time")]
    FinishedBeforeRequest,
    #[error("managed-profile fork success facts do not match the request")]
    SuccessFactsMismatch,
    #[error("managed-profile fork copied-byte total exceeds its quota")]
    CopiedBytesExceedQuota,
    #[error("managed-profile fork failure facts do not match the declared quota")]
    InvalidFailureFacts,
    #[error("managed-profile fork failure refers to an unknown child index")]
    InvalidFailureChildIndex,
}
