use chrono::{DateTime, Utc};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use super::super::{BrowserProfileLeaseGeneration, BrowserProfileLeaseId, BrowserProfileOwnerId};

/// Validated public identity for a managed profile.
///
/// This carries the registry key only. Filesystem paths remain private to the
/// browser manager and are never included in profile lease receipts.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct BrowserProfileId(String);

impl BrowserProfileId {
    pub fn new(value: impl Into<String>) -> Result<Self, BrowserProfileLeaseError> {
        let value = value.into();
        let valid_characters = value
            .chars()
            .all(|character| character.is_ascii_alphanumeric() || "-_.".contains(character));
        if value.is_empty()
            || value.len() > 128
            || value == "."
            || value == ".."
            || !valid_characters
        {
            return Err(BrowserProfileLeaseError::InvalidProfileId);
        }
        Ok(Self(value))
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl<'de> Deserialize<'de> for BrowserProfileId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = String::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}

/// Scope granted by one managed-profile lease.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileLeaseScope {
    ExclusiveManagedBrowser,
}

/// Final outcome for a managed-profile lease.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum BrowserProfileLeaseTerminalOutcome {
    Released,
    ExpiredAndReleased,
    OwnershipUncertain,
}

impl BrowserProfileLeaseTerminalOutcome {
    pub const fn quarantine_required(self) -> bool {
        matches!(self, Self::ExpiredAndReleased | Self::OwnershipUncertain)
    }
}

/// Secret-safe identity, scope, fencing generation, and wall-clock window for
/// one exclusive managed-profile tenancy.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileLeaseReceipt {
    profile_id: BrowserProfileId,
    lease_id: BrowserProfileLeaseId,
    owner_id: BrowserProfileOwnerId,
    scope: BrowserProfileLeaseScope,
    generation: BrowserProfileLeaseGeneration,
    acquired_at: DateTime<Utc>,
    expires_at: DateTime<Utc>,
}

impl BrowserProfileLeaseReceipt {
    #[allow(clippy::too_many_arguments)]
    pub fn new(
        profile_id: BrowserProfileId,
        lease_id: BrowserProfileLeaseId,
        owner_id: BrowserProfileOwnerId,
        scope: BrowserProfileLeaseScope,
        generation: BrowserProfileLeaseGeneration,
        acquired_at: DateTime<Utc>,
        expires_at: DateTime<Utc>,
    ) -> Result<Self, BrowserProfileLeaseError> {
        if expires_at <= acquired_at {
            return Err(BrowserProfileLeaseError::InvalidWallClockWindow);
        }
        Ok(Self {
            profile_id,
            lease_id,
            owner_id,
            scope,
            generation,
            acquired_at,
            expires_at,
        })
    }

    pub const fn profile_id(&self) -> &BrowserProfileId {
        &self.profile_id
    }

    pub const fn lease_id(&self) -> BrowserProfileLeaseId {
        self.lease_id
    }

    pub const fn owner_id(&self) -> BrowserProfileOwnerId {
        self.owner_id
    }

    pub const fn scope(&self) -> BrowserProfileLeaseScope {
        self.scope
    }

    pub const fn generation(&self) -> BrowserProfileLeaseGeneration {
        self.generation
    }

    pub const fn acquired_at(&self) -> &DateTime<Utc> {
        &self.acquired_at
    }

    pub const fn expires_at(&self) -> &DateTime<Utc> {
        &self.expires_at
    }
}

/// Secret-safe final facts for one managed-profile lease.
#[derive(Clone, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileLeaseTerminalReceipt {
    lease: BrowserProfileLeaseReceipt,
    outcome: BrowserProfileLeaseTerminalOutcome,
    finished_at: DateTime<Utc>,
}

impl BrowserProfileLeaseTerminalReceipt {
    pub fn new(
        lease: BrowserProfileLeaseReceipt,
        outcome: BrowserProfileLeaseTerminalOutcome,
        finished_at: DateTime<Utc>,
    ) -> Result<Self, BrowserProfileLeaseError> {
        if finished_at < *lease.acquired_at() {
            return Err(BrowserProfileLeaseError::InvalidTerminalTime);
        }
        if outcome == BrowserProfileLeaseTerminalOutcome::ExpiredAndReleased
            && finished_at < *lease.expires_at()
        {
            return Err(BrowserProfileLeaseError::ExpiredBeforeDeadline);
        }
        Ok(Self {
            lease,
            outcome,
            finished_at,
        })
    }

    pub const fn lease(&self) -> &BrowserProfileLeaseReceipt {
        &self.lease
    }

    pub const fn outcome(&self) -> BrowserProfileLeaseTerminalOutcome {
        self.outcome
    }

    pub const fn finished_at(&self) -> &DateTime<Utc> {
        &self.finished_at
    }
}

/// Errors for managed-profile identity, lease fencing, and receipt validation.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum BrowserProfileLeaseError {
    #[error("managed-profile identity is invalid")]
    InvalidProfileId,
    #[error("managed-profile lease duration must be positive")]
    ZeroDuration,
    #[error("managed-profile lease deadline overflowed")]
    DeadlineOverflow,
    #[error("managed-profile lease window is invalid")]
    InvalidWallClockWindow,
    #[error("managed-profile terminal receipt time is invalid")]
    InvalidTerminalTime,
    #[error("managed-profile expiry receipt predates its declared expiry")]
    ExpiredBeforeDeadline,
    #[error("managed-profile lease has expired")]
    Expired,
    #[error("managed-profile lease generation is stale")]
    StaleGeneration,
    #[error("managed-profile lease generation is exhausted")]
    GenerationExhausted,
    #[error("managed-profile generation allocator is unavailable")]
    GenerationAllocatorUnavailable,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileLeaseReceiptWire {
    profile_id: BrowserProfileId,
    lease_id: BrowserProfileLeaseId,
    owner_id: BrowserProfileOwnerId,
    scope: BrowserProfileLeaseScope,
    generation: BrowserProfileLeaseGeneration,
    acquired_at: DateTime<Utc>,
    expires_at: DateTime<Utc>,
}

impl TryFrom<BrowserProfileLeaseReceiptWire> for BrowserProfileLeaseReceipt {
    type Error = BrowserProfileLeaseError;

    fn try_from(value: BrowserProfileLeaseReceiptWire) -> Result<Self, Self::Error> {
        Self::new(
            value.profile_id,
            value.lease_id,
            value.owner_id,
            value.scope,
            value.generation,
            value.acquired_at,
            value.expires_at,
        )
    }
}

impl<'de> Deserialize<'de> for BrowserProfileLeaseReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserProfileLeaseReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct BrowserProfileLeaseTerminalReceiptWire {
    lease: BrowserProfileLeaseReceipt,
    outcome: BrowserProfileLeaseTerminalOutcome,
    finished_at: DateTime<Utc>,
}

impl TryFrom<BrowserProfileLeaseTerminalReceiptWire> for BrowserProfileLeaseTerminalReceipt {
    type Error = BrowserProfileLeaseError;

    fn try_from(value: BrowserProfileLeaseTerminalReceiptWire) -> Result<Self, Self::Error> {
        Self::new(value.lease, value.outcome, value.finished_at)
    }
}

impl<'de> Deserialize<'de> for BrowserProfileLeaseTerminalReceipt {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        BrowserProfileLeaseTerminalReceiptWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
