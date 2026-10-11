use std::{
    fmt,
    num::{NonZeroU8, NonZeroU64},
    str::FromStr,
};

use crate::internal::types::{ActivityId, OccurrenceIdParseError};
use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use super::super::{BrowserProfileId, BrowserProfileLeaseGeneration, BrowserProfileLeaseReceipt};
use super::BrowserProfileForkError;

/// Maximum child count accepted by one Yosoi profile-fork request.
pub const MAX_BROWSER_PROFILE_FORK_CHILDREN: usize = 16;

macro_rules! fork_identity {
    ($name:ident) => {
        /// Validated immutable identifier for a managed-profile fork entity.
        #[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
        #[serde(transparent)]
        pub struct $name(ActivityId);

        impl $name {
            /// Creates a fresh random v4 identifier.
            pub fn random() -> Self {
                Self(ActivityId::random())
            }

            /// Wraps an already validated Yosoi activity identity.
            pub const fn new(value: ActivityId) -> Self {
                Self(value)
            }

            /// Returns the identity bytes in network byte order.
            pub const fn as_bytes(&self) -> &[u8; 16] {
                self.0.as_bytes()
            }
        }

        impl fmt::Display for $name {
            fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                self.0.fmt(formatter)
            }
        }

        impl FromStr for $name {
            type Err = OccurrenceIdParseError;

            fn from_str(value: &str) -> Result<Self, Self::Err> {
                value.parse::<ActivityId>().map(Self)
            }
        }
    };
}

fork_identity!(BrowserProfileCheckpointId);
fork_identity!(BrowserProfileChildId);
fork_identity!(BrowserProfileLineageId);

/// Stable identity of the source profile state from which children are copied.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileCheckpointIdentity {
    id: BrowserProfileCheckpointId,
    source_profile_id: BrowserProfileId,
    source_generation: BrowserProfileLeaseGeneration,
}

impl BrowserProfileCheckpointIdentity {
    pub fn new(id: BrowserProfileCheckpointId, source_lease: &BrowserProfileLeaseReceipt) -> Self {
        Self {
            id,
            source_profile_id: source_lease.profile_id().clone(),
            source_generation: source_lease.generation(),
        }
    }

    pub const fn id(&self) -> BrowserProfileCheckpointId {
        self.id
    }

    pub const fn source_profile_id(&self) -> &BrowserProfileId {
        &self.source_profile_id
    }

    pub const fn source_generation(&self) -> BrowserProfileLeaseGeneration {
        self.source_generation
    }
}

/// Lineage edge binding descendants to one immutable source checkpoint.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileLineageIdentity {
    id: BrowserProfileLineageId,
    checkpoint: BrowserProfileCheckpointIdentity,
}

impl BrowserProfileLineageIdentity {
    pub fn new(id: BrowserProfileLineageId, checkpoint: &BrowserProfileCheckpointIdentity) -> Self {
        Self {
            id,
            checkpoint: checkpoint.clone(),
        }
    }

    pub const fn id(&self) -> BrowserProfileLineageId {
        self.id
    }

    pub const fn checkpoint(&self) -> &BrowserProfileCheckpointIdentity {
        &self.checkpoint
    }
}

/// Stable logical identity and registry key for one fork child.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct BrowserProfileChildIdentity {
    id: BrowserProfileChildId,
    profile_id: BrowserProfileId,
    lineage_id: BrowserProfileLineageId,
    checkpoint_id: BrowserProfileCheckpointId,
}

impl BrowserProfileChildIdentity {
    pub const fn new(
        id: BrowserProfileChildId,
        profile_id: BrowserProfileId,
        lineage: &BrowserProfileLineageIdentity,
    ) -> Self {
        Self {
            id,
            profile_id,
            lineage_id: lineage.id(),
            checkpoint_id: lineage.checkpoint().id(),
        }
    }

    pub const fn id(&self) -> BrowserProfileChildId {
        self.id
    }

    pub const fn profile_id(&self) -> &BrowserProfileId {
        &self.profile_id
    }

    pub const fn lineage_id(&self) -> BrowserProfileLineageId {
        self.lineage_id
    }

    pub const fn checkpoint_id(&self) -> BrowserProfileCheckpointId {
        self.checkpoint_id
    }
}

/// Resolved per-request child-count and aggregate copied-byte bounds.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ResolvedBrowserProfileForkLimits {
    max_copies: NonZeroU8,
    aggregate_byte_quota: NonZeroU64,
}

impl ResolvedBrowserProfileForkLimits {
    pub fn new(
        max_copies: usize,
        aggregate_byte_quota: u64,
    ) -> Result<Self, BrowserProfileForkError> {
        if !(1..=MAX_BROWSER_PROFILE_FORK_CHILDREN).contains(&max_copies) {
            return Err(BrowserProfileForkError::InvalidMaximumCopies);
        }
        let max_copies =
            u8::try_from(max_copies).map_err(|_| BrowserProfileForkError::InvalidMaximumCopies)?;
        let max_copies =
            NonZeroU8::new(max_copies).ok_or(BrowserProfileForkError::InvalidMaximumCopies)?;
        let aggregate_byte_quota = NonZeroU64::new(aggregate_byte_quota)
            .ok_or(BrowserProfileForkError::InvalidAggregateByteQuota)?;
        Ok(Self {
            max_copies,
            aggregate_byte_quota,
        })
    }

    pub const fn max_copies(self) -> u8 {
        self.max_copies.get()
    }

    pub const fn aggregate_byte_quota(self) -> u64 {
        self.aggregate_byte_quota.get()
    }
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct ResolvedBrowserProfileForkLimitsWire {
    max_copies: u8,
    aggregate_byte_quota: u64,
}

impl TryFrom<ResolvedBrowserProfileForkLimitsWire> for ResolvedBrowserProfileForkLimits {
    type Error = BrowserProfileForkError;

    fn try_from(value: ResolvedBrowserProfileForkLimitsWire) -> Result<Self, Self::Error> {
        Self::new(usize::from(value.max_copies), value.aggregate_byte_quota)
    }
}

impl<'de> Deserialize<'de> for ResolvedBrowserProfileForkLimits {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        ResolvedBrowserProfileForkLimitsWire::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}
