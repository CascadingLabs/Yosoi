use std::{fmt, num::NonZeroU64, str::FromStr};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use yosoi_types::{ActivityId, OccurrenceIdParseError};

macro_rules! browser_execution_id {
    ($name:ident) => {
        #[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
        #[serde(transparent)]
        pub struct $name(ActivityId);

        impl $name {
            /// Generates a new Yosoi-owned random identity.
            pub fn random() -> Self {
                Self(ActivityId::random())
            }

            /// Returns the random UUID bytes in network byte order.
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

        impl<'de> Deserialize<'de> for $name {
            fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
            where
                D: Deserializer<'de>,
            {
                String::deserialize(deserializer)?
                    .parse()
                    .map_err(D::Error::custom)
            }
        }
    };
}

browser_execution_id!(BrowserExecutionManagerId);
browser_execution_id!(BrowserProcessSlotId);
browser_execution_id!(BrowserProfileLeaseId);
browser_execution_id!(BrowserProfileOwnerId);

/// Monotonically increasing Yosoi lease generation for one managed profile.
///
/// This is deliberately a different type from [`BrowserProcessGeneration`]: a
/// profile tenancy can outlive and recycle its Chromium process.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct BrowserProfileLeaseGeneration(NonZeroU64);

impl BrowserProfileLeaseGeneration {
    pub const fn new(value: NonZeroU64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

/// Monotonically increasing generation of one reusable browser process slot.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct BrowserProcessGeneration(NonZeroU64);

impl BrowserProcessGeneration {
    pub const fn new(value: NonZeroU64) -> Self {
        Self(value)
    }

    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

browser_execution_id!(BrowserExecutionId);
browser_execution_id!(BrowserContextLeaseId);
browser_execution_id!(BrowserSessionLeaseId);
browser_execution_id!(BrowserTabLeaseId);
browser_execution_id!(BrowserNavigationSchedulerId);
browser_execution_id!(BrowserNavigationRequestId);
