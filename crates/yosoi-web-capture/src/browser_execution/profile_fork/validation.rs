use std::collections::HashSet;

use chrono::{DateTime, Utc};

#[allow(
    clippy::wildcard_imports,
    reason = "private split module shares its facade's implementation context"
)]
use super::*;

pub(super) fn validate_fork_bindings(
    checkpoint: &BrowserProfileCheckpointIdentity,
    lineage: &BrowserProfileLineageIdentity,
    children: &[BrowserProfileChildIdentity],
    limits: ResolvedBrowserProfileForkLimits,
) -> Result<(), BrowserProfileForkError> {
    if lineage.checkpoint() != checkpoint {
        return Err(BrowserProfileForkError::LineageCheckpointMismatch);
    }
    if children.is_empty() || children.len() > usize::from(limits.max_copies()) {
        return Err(BrowserProfileForkError::ChildCountExceedsMaximum);
    }
    let mut child_ids = HashSet::with_capacity(children.len());
    let mut profile_ids = HashSet::with_capacity(children.len());
    for child in children {
        if child.lineage_id() != lineage.id() || child.checkpoint_id() != checkpoint.id() {
            return Err(BrowserProfileForkError::ChildLineageMismatch);
        }
        if child.profile_id() == checkpoint.source_profile_id() {
            return Err(BrowserProfileForkError::ChildProfileMatchesSource);
        }
        if !child_ids.insert(child.id()) {
            return Err(BrowserProfileForkError::DuplicateChildIdentity);
        }
        if !profile_ids.insert(child.profile_id().clone()) {
            return Err(BrowserProfileForkError::DuplicateChildProfile);
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)]
pub(super) fn validate_receipt_bindings(
    checkpoint: &BrowserProfileCheckpointIdentity,
    lineage: &BrowserProfileLineageIdentity,
    children: &[BrowserProfileChildIdentity],
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: &DateTime<Utc>,
    child_expires_at: &DateTime<Utc>,
    finished_at: &DateTime<Utc>,
    copied_bytes: u64,
) -> Result<(), BrowserProfileForkError> {
    validate_fork_bindings(checkpoint, lineage, children, limits)?;
    if child_expires_at <= requested_at {
        return Err(BrowserProfileForkError::InvalidChildExpiry);
    }
    if finished_at < requested_at {
        return Err(BrowserProfileForkError::FinishedBeforeRequest);
    }
    if finished_at >= child_expires_at {
        return Err(BrowserProfileForkError::ChildExpiryReached);
    }
    if copied_bytes > limits.aggregate_byte_quota() {
        return Err(BrowserProfileForkError::CopiedBytesExceedQuota);
    }
    Ok(())
}

pub(super) fn validate_failure_facts(
    children: &[BrowserProfileChildIdentity],
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: &DateTime<Utc>,
    child_expires_at: &DateTime<Utc>,
    failed_at: &DateTime<Utc>,
    facts: &BrowserProfileForkFailureFacts,
) -> Result<(), BrowserProfileForkError> {
    if failed_at < requested_at {
        return Err(BrowserProfileForkError::FinishedBeforeRequest);
    }
    if facts
        .child_index()
        .is_some_and(|index| usize::from(index) >= children.len())
    {
        return Err(BrowserProfileForkError::InvalidFailureChildIndex);
    }
    if facts.copied_bytes() > limits.aggregate_byte_quota() {
        return Err(BrowserProfileForkError::InvalidFailureFacts);
    }
    if facts.reason() == BrowserProfileForkFailureReason::AggregateByteQuotaExceeded
        && facts
            .attempted_bytes()
            .is_none_or(|attempted| attempted <= limits.aggregate_byte_quota())
    {
        return Err(BrowserProfileForkError::InvalidFailureFacts);
    }
    if facts.reason() == BrowserProfileForkFailureReason::ChildExpiryReached
        && failed_at < child_expires_at
    {
        return Err(BrowserProfileForkError::InvalidFailureFacts);
    }
    if facts.reason() == BrowserProfileForkFailureReason::CleanupIncomplete
        && facts.cleanup_succeeded()
    {
        return Err(BrowserProfileForkError::InvalidFailureFacts);
    }
    Ok(())
}
