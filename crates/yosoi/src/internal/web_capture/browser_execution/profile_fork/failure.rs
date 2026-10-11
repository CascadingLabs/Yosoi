use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use super::validation::{validate_failure_facts, validate_fork_bindings};
use super::{
    BrowserProfileCheckpointIdentity, BrowserProfileChildIdentity, BrowserProfileForkError,
    BrowserProfileForkRequest, BrowserProfileLineageIdentity, ResolvedBrowserProfileForkLimits,
};

/// Provider-neutral failure categories safe to retain in a receipt.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileForkFailureReason {
    StaleSourceGeneration,
    SourceLeaseExpired,
    ChildExpiryReached,
    AggregateByteQuotaExceeded,
    SourceUnavailable,
    ChildConflict,
    CopyFailed,
    RegistrationFailed,
    CleanupIncomplete,
}

/// Provider-neutral operational facts for a failed fork attempt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileForkFailureFacts {
    reason: BrowserProfileForkFailureReason,
    child_index: Option<u8>,
    copied_bytes: u64,
    attempted_bytes: Option<u64>,
    cleanup_succeeded: bool,
}

impl BrowserProfileForkFailureFacts {
    pub const fn new(
        reason: BrowserProfileForkFailureReason,
        child_index: Option<u8>,
        copied_bytes: u64,
        attempted_bytes: Option<u64>,
        cleanup_succeeded: bool,
    ) -> Self {
        Self {
            reason,
            child_index,
            copied_bytes,
            attempted_bytes,
            cleanup_succeeded,
        }
    }

    pub const fn reason(&self) -> BrowserProfileForkFailureReason {
        self.reason
    }

    pub const fn child_index(&self) -> Option<u8> {
        self.child_index
    }

    pub const fn copied_bytes(&self) -> u64 {
        self.copied_bytes
    }

    pub const fn attempted_bytes(&self) -> Option<u64> {
        self.attempted_bytes
    }

    pub const fn cleanup_succeeded(&self) -> bool {
        self.cleanup_succeeded
    }
}

/// Secret-safe failed fork receipt containing only domain identities and
/// bounded operational facts, never provider paths or raw provider messages.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileForkFailureReceipt {
    checkpoint: BrowserProfileCheckpointIdentity,
    lineage: BrowserProfileLineageIdentity,
    children: Vec<BrowserProfileChildIdentity>,
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: DateTime<Utc>,
    child_expires_at: DateTime<Utc>,
    failed_at: DateTime<Utc>,
    facts: BrowserProfileForkFailureFacts,
}

impl BrowserProfileForkFailureReceipt {
    pub fn from_failure_facts(
        request: &BrowserProfileForkRequest,
        facts: BrowserProfileForkFailureFacts,
        failed_at: &DateTime<Utc>,
    ) -> Result<Self, BrowserProfileForkError> {
        validate_failure_facts(
            &request.children,
            request.limits,
            &request.requested_at,
            &request.child_expires_at,
            failed_at,
            &facts,
        )?;
        validate_fork_bindings(
            &request.checkpoint,
            &request.lineage,
            &request.children,
            request.limits,
        )?;
        Ok(Self {
            checkpoint: request.checkpoint.clone(),
            lineage: request.lineage.clone(),
            children: request.children.clone(),
            limits: request.limits,
            requested_at: request.requested_at,
            child_expires_at: request.child_expires_at,
            failed_at: *failed_at,
            facts,
        })
    }

    pub const fn facts(&self) -> &BrowserProfileForkFailureFacts {
        &self.facts
    }

    pub const fn checkpoint(&self) -> &BrowserProfileCheckpointIdentity {
        &self.checkpoint
    }

    pub const fn lineage(&self) -> &BrowserProfileLineageIdentity {
        &self.lineage
    }

    pub fn children(&self) -> &[BrowserProfileChildIdentity] {
        &self.children
    }

    pub const fn limits(&self) -> ResolvedBrowserProfileForkLimits {
        self.limits
    }

    pub const fn child_expires_at(&self) -> &DateTime<Utc> {
        &self.child_expires_at
    }

    pub const fn failed_at(&self) -> &DateTime<Utc> {
        &self.failed_at
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileForkFailureReceiptWire {
    checkpoint: BrowserProfileCheckpointIdentity,
    lineage: BrowserProfileLineageIdentity,
    children: Vec<BrowserProfileChildIdentity>,
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: DateTime<Utc>,
    child_expires_at: DateTime<Utc>,
    failed_at: DateTime<Utc>,
    facts: BrowserProfileForkFailureFacts,
}

impl TryFrom<BrowserProfileForkFailureReceiptWire> for BrowserProfileForkFailureReceipt {
    type Error = BrowserProfileForkError;

    fn try_from(value: BrowserProfileForkFailureReceiptWire) -> Result<Self, Self::Error> {
        validate_failure_facts(
            &value.children,
            value.limits,
            &value.requested_at,
            &value.child_expires_at,
            &value.failed_at,
            &value.facts,
        )?;
        if value.child_expires_at <= value.requested_at {
            return Err(BrowserProfileForkError::InvalidChildExpiry);
        }
        validate_fork_bindings(
            &value.checkpoint,
            &value.lineage,
            &value.children,
            value.limits,
        )?;
        Ok(Self {
            checkpoint: value.checkpoint,
            lineage: value.lineage,
            children: value.children,
            limits: value.limits,
            requested_at: value.requested_at,
            child_expires_at: value.child_expires_at,
            failed_at: value.failed_at,
            facts: value.facts,
        })
    }
}

impl<'de> Deserialize<'de> for BrowserProfileForkFailureReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserProfileForkFailureReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
