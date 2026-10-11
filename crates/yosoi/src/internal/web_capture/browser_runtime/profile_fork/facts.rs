#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

pub(super) const fn map_contract_store_error(
    error: BrowserProfileChildContractStoreError,
) -> BrowserProfileForkServiceError {
    match error {
        BrowserProfileChildContractStoreError::Conflict => {
            BrowserProfileForkServiceError::ChildConflict
        }
        BrowserProfileChildContractStoreError::Expired => {
            BrowserProfileForkServiceError::ChildExpired
        }
        BrowserProfileChildContractStoreError::NotCommitted => {
            BrowserProfileForkServiceError::ChildNotCommitted
        }
        BrowserProfileChildContractStoreError::NotFound => {
            BrowserProfileForkServiceError::ChildContractNotFound
        }
        BrowserProfileChildContractStoreError::Io
        | BrowserProfileChildContractStoreError::InvalidStore
        | BrowserProfileChildContractStoreError::ReservationMismatch => {
            BrowserProfileForkServiceError::ContractStoreUnavailable
        }
    }
}

pub(super) const fn map_lease_error(
    error: BrowserProfileLeaseError,
) -> BrowserProfileForkServiceError {
    match error {
        BrowserProfileLeaseError::GenerationAllocatorUnavailable
        | BrowserProfileLeaseError::GenerationExhausted
        | BrowserProfileLeaseError::StaleGeneration => {
            BrowserProfileForkServiceError::GenerationUnavailable
        }
        _ => BrowserProfileForkServiceError::FenceUnavailable,
    }
}

pub(super) fn provider_failure_facts(
    error: &ManagedProfileForkError,
) -> BrowserProfileForkFailureFacts {
    use provider::managed_profile::{ManagedProfileForkErrorKind, ManagedProfileForkOperation};

    let (mut reason, attempted_bytes) = match &error.kind {
        ManagedProfileForkErrorKind::AggregateByteQuotaExceeded {
            attempted_bytes, ..
        } => (
            BrowserProfileForkFailureReason::AggregateByteQuotaExceeded,
            Some(*attempted_bytes),
        ),
        ManagedProfileForkErrorKind::SourceMissing
        | ManagedProfileForkErrorKind::LeaseNotRegistered => {
            (BrowserProfileForkFailureReason::SourceUnavailable, None)
        }
        ManagedProfileForkErrorKind::ChildAlreadyExists { .. }
        | ManagedProfileForkErrorKind::InvalidChildId { .. }
        | ManagedProfileForkErrorKind::DuplicateChildId { .. }
        | ManagedProfileForkErrorKind::InvalidCopyCount { .. } => {
            (BrowserProfileForkFailureReason::ChildConflict, None)
        }
        ManagedProfileForkErrorKind::Io {
            operation:
                ManagedProfileForkOperation::MoveChildIntoPlace
                | ManagedProfileForkOperation::SerializeManifest
                | ManagedProfileForkOperation::WriteManifestTemporary
                | ManagedProfileForkOperation::ReplaceManifest,
            ..
        } => (BrowserProfileForkFailureReason::RegistrationFailed, None),
        ManagedProfileForkErrorKind::InvalidManifest
        | ManagedProfileForkErrorKind::ManifestSerializationFailed => {
            (BrowserProfileForkFailureReason::RegistrationFailed, None)
        }
        _ => (BrowserProfileForkFailureReason::CopyFailed, None),
    };
    if !error.facts.cleanup_succeeded {
        reason = BrowserProfileForkFailureReason::CleanupIncomplete;
    }
    BrowserProfileForkFailureFacts::new(
        reason,
        error
            .facts
            .child_index
            .and_then(|index| u8::try_from(index).ok()),
        error.facts.copied_bytes,
        attempted_bytes,
        error.facts.cleanup_succeeded,
    )
}

pub(super) const fn failure_reason_for_domain(
    error: BrowserProfileForkError,
) -> BrowserProfileForkFailureReason {
    match error {
        BrowserProfileForkError::StaleSourceGeneration => {
            BrowserProfileForkFailureReason::StaleSourceGeneration
        }
        BrowserProfileForkError::SourceLeaseExpired => {
            BrowserProfileForkFailureReason::SourceLeaseExpired
        }
        BrowserProfileForkError::ChildExpiryReached => {
            BrowserProfileForkFailureReason::ChildExpiryReached
        }
        _ => BrowserProfileForkFailureReason::SourceUnavailable,
    }
}

pub(super) fn failure_receipt(
    request: &BrowserProfileForkRequest,
    reason: BrowserProfileForkFailureReason,
    child_index: Option<u8>,
    copied_bytes: u64,
    attempted_bytes: Option<u64>,
    cleanup_succeeded: bool,
    failed_at: DateTime<Utc>,
) -> Result<BrowserProfileForkFailureReceipt, BrowserProfileForkServiceError> {
    BrowserProfileForkFailureReceipt::from_failure_facts(
        request,
        BrowserProfileForkFailureFacts::new(
            reason,
            child_index,
            copied_bytes,
            attempted_bytes,
            cleanup_succeeded,
        ),
        &failed_at,
    )
    .map_err(BrowserProfileForkServiceError::InvalidDomainReceipt)
}

pub(super) fn child_contracts_for_request(
    request: &BrowserProfileForkRequest,
    state: BrowserProfileChildContractState,
) -> Vec<BrowserProfileChildLeaseContract> {
    request
        .children()
        .iter()
        .map(|identity| BrowserProfileChildLeaseContract {
            identity: identity.clone(),
            lineage: request.lineage().clone(),
            expires_at: *request.child_expires_at(),
            state,
        })
        .collect()
}
