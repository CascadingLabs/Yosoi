use std::sync::Arc;

use crate::{EffectivePolicy, EffectivePolicyIdentity, Policy, PolicyError};

/// Immutable, validated policy values and their deterministic identity.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct PolicySnapshot {
    policy: Arc<Policy>,
    effective_policy: Arc<EffectivePolicy>,
    identity: EffectivePolicyIdentity,
}

impl PolicySnapshot {
    /// Validates and snapshots a caller-owned policy declaration.
    ///
    /// The declaration remains available to the caller; the snapshot owns a
    /// validated clone, a Current-expanded behavior snapshot, and its
    /// deterministic effective identity.
    pub fn from_policy(policy: &Policy) -> Result<Self, PolicyError> {
        let effective_policy = policy.effective_policy()?;
        let identity = effective_policy.identity()?;
        Ok(Self {
            policy: Arc::new(policy.clone()),
            effective_policy: Arc::new(effective_policy),
            identity,
        })
    }

    /// Returns the immutable policy value held by this snapshot.
    pub fn policy(&self) -> &Policy {
        &self.policy
    }

    /// Returns the immutable policy behavior with Current selections expanded.
    pub fn effective_policy(&self) -> &EffectivePolicy {
        &self.effective_policy
    }

    /// Returns the deterministic identity computed for this snapshot.
    pub const fn identity(&self) -> EffectivePolicyIdentity {
        self.identity
    }
}
