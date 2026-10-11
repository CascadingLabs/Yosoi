#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

/// Result of one requested copy batch, expressed only in Yosoi domain receipts.
#[derive(Clone, Debug, Eq, PartialEq)]
pub enum ManagedProfileForkOutcome {
    Completed(BrowserProfileForkReceipt),
    Failed(BrowserProfileForkFailureReceipt),
}

/// Runtime adapter failures that occur before provider result facts exist.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserProfileForkServiceError {
    #[error("managed-profile fork source lease duration must be positive")]
    InvalidSourceLeaseDuration,
    #[error("managed-profile source is unavailable or owned by a live browser")]
    SourceUnavailable,
    #[error("managed-profile generation authority is unavailable")]
    GenerationUnavailable,
    #[error("managed-profile lifecycle store is unavailable or invalid")]
    LifecycleStoreUnavailable,
    #[error("managed-profile lease fence could not be created")]
    FenceUnavailable,
    #[error("managed-profile fork request does not match its held source lease")]
    SourceLeaseMismatch,
    #[error("managed-profile fork request time has not arrived")]
    RequestNotYetActive,
    #[error("managed-profile child contract registry is unavailable")]
    ContractRegistryUnavailable,
    #[error("managed-profile child contract store is unavailable or invalid")]
    ContractStoreUnavailable,
    #[error("managed-profile child contract already exists")]
    ChildConflict,
    #[error("managed-profile child contract is not registered")]
    ChildContractNotFound,
    #[error("managed-profile child contract has expired")]
    ChildExpired,
    #[error("managed-profile child contract is not committed")]
    ChildNotCommitted,
    #[error("managed-profile fork receipt rejected neutral facts")]
    InvalidDomainReceipt(BrowserProfileForkError),
}
