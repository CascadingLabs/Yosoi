use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use super::super::{BrowserProfileLeaseGenerationRegistry, BrowserProfileLeaseReceipt};
use super::validation::validate_fork_bindings;
use super::{
    BrowserProfileCheckpointIdentity, BrowserProfileChildIdentity, BrowserProfileForkError,
    BrowserProfileLineageIdentity, ResolvedBrowserProfileForkLimits,
};

/// Provider-neutral request for copying one fenced profile into bounded child
/// profiles. It declares expiry metadata but does not issue child leases.
#[derive(Clone, Debug, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileForkRequest {
    pub(super) source_lease: BrowserProfileLeaseReceipt,
    pub(super) checkpoint: BrowserProfileCheckpointIdentity,
    pub(super) lineage: BrowserProfileLineageIdentity,
    pub(super) children: Vec<BrowserProfileChildIdentity>,
    pub(super) limits: ResolvedBrowserProfileForkLimits,
    pub(super) requested_at: DateTime<Utc>,
    pub(super) child_expires_at: DateTime<Utc>,
}

impl BrowserProfileForkRequest {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        source_lease: BrowserProfileLeaseReceipt,
        checkpoint: BrowserProfileCheckpointIdentity,
        lineage: BrowserProfileLineageIdentity,
        children: Vec<BrowserProfileChildIdentity>,
        limits: ResolvedBrowserProfileForkLimits,
        requested_at: DateTime<Utc>,
        child_expires_at: DateTime<Utc>,
    ) -> Result<Self, BrowserProfileForkError> {
        if checkpoint.source_profile_id() != source_lease.profile_id()
            || checkpoint.source_generation() != source_lease.generation()
        {
            return Err(BrowserProfileForkError::CheckpointSourceMismatch);
        }
        validate_fork_bindings(&checkpoint, &lineage, &children, limits)?;
        if &requested_at < source_lease.acquired_at() || &requested_at >= source_lease.expires_at()
        {
            return Err(BrowserProfileForkError::SourceLeaseInactiveAtRequest);
        }
        if child_expires_at <= requested_at {
            return Err(BrowserProfileForkError::InvalidChildExpiry);
        }
        Ok(Self {
            source_lease,
            checkpoint,
            lineage,
            children,
            limits,
            requested_at,
            child_expires_at,
        })
    }

    /// Rechecks that the source lease is current and that both declared time
    /// windows still permit the fork immediately before provider work begins.
    pub fn authorize_source(
        &self,
        generations: &BrowserProfileLeaseGenerationRegistry,
        now: &DateTime<Utc>,
    ) -> Result<(), BrowserProfileForkError> {
        if now < &self.requested_at {
            return Err(BrowserProfileForkError::RequestNotYetActive);
        }
        if now < self.source_lease.acquired_at() {
            return Err(BrowserProfileForkError::SourceLeaseNotYetActive);
        }
        if now >= self.source_lease.expires_at() {
            return Err(BrowserProfileForkError::SourceLeaseExpired);
        }
        if now >= &self.child_expires_at {
            return Err(BrowserProfileForkError::ChildExpiryReached);
        }
        let current = generations
            .is_current(
                self.source_lease.profile_id(),
                self.source_lease.generation(),
            )
            .map_err(|_| BrowserProfileForkError::GenerationRegistryUnavailable)?;
        if !current {
            return Err(BrowserProfileForkError::StaleSourceGeneration);
        }
        Ok(())
    }

    pub const fn source_lease(&self) -> &BrowserProfileLeaseReceipt {
        &self.source_lease
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

    pub const fn requested_at(&self) -> &DateTime<Utc> {
        &self.requested_at
    }

    pub const fn child_expires_at(&self) -> &DateTime<Utc> {
        &self.child_expires_at
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileForkRequestWire {
    source_lease: BrowserProfileLeaseReceipt,
    checkpoint: BrowserProfileCheckpointIdentity,
    lineage: BrowserProfileLineageIdentity,
    children: Vec<BrowserProfileChildIdentity>,
    limits: ResolvedBrowserProfileForkLimits,
    requested_at: DateTime<Utc>,
    child_expires_at: DateTime<Utc>,
}

impl TryFrom<BrowserProfileForkRequestWire> for BrowserProfileForkRequest {
    type Error = BrowserProfileForkError;

    fn try_from(value: BrowserProfileForkRequestWire) -> Result<Self, Self::Error> {
        Self::new(
            value.source_lease,
            value.checkpoint,
            value.lineage,
            value.children,
            value.limits,
            value.requested_at,
            value.child_expires_at,
        )
    }
}

impl<'de> Deserialize<'de> for BrowserProfileForkRequest {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserProfileForkRequestWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
