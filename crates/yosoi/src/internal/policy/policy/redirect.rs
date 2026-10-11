use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use std::num::NonZeroU32;

use crate::internal::policy::PolicyError;

/// Positive maximum number of Direct HTTP redirect transitions.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct RedirectHopLimit(u32);

impl RedirectHopLimit {
    /// Returns the exact positive hop bound.
    pub const fn get(self) -> u32 {
        self.0
    }

    pub(in crate::internal::policy) fn nonzero(self) -> Result<NonZeroU32, PolicyError> {
        NonZeroU32::new(self.0).ok_or(PolicyError::ZeroRedirectHopLimit)
    }
}

impl Default for RedirectHopLimit {
    fn default() -> Self {
        Self(10)
    }
}

impl TryFrom<u32> for RedirectHopLimit {
    type Error = PolicyError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        NonZeroU32::new(value)
            .map(|_| Self(value))
            .ok_or(PolicyError::ZeroRedirectHopLimit)
    }
}

impl Serialize for RedirectHopLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u32(self.0)
    }
}

impl<'de> Deserialize<'de> for RedirectHopLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u32::deserialize(deserializer)?;
        Self::try_from(value).map_err(D::Error::custom)
    }
}

/// Target schemes/origins that Direct HTTP redirect transitions may admit.
#[derive(Clone, Copy, Debug, Default, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case", deny_unknown_fields)]
pub enum DirectHttpRedirectTargets {
    /// Permit redirect targets using HTTP or HTTPS, including cross-origin URLs.
    #[default]
    AllowHttpAndHttps,
    /// Permit redirect targets only when they remain same-origin.
    SameOrigin,
}

/// Automatic redirect behavior for Direct HTTP only.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub enum DirectHttpRedirects {
    /// Return the first response without following its location.
    Disabled,
    /// Follow no more than the configured positive number of transitions.
    Follow {
        max_hops: RedirectHopLimit,
        targets: DirectHttpRedirectTargets,
    },
}

impl Default for DirectHttpRedirects {
    fn default() -> Self {
        Self::Follow {
            max_hops: RedirectHopLimit::default(),
            targets: DirectHttpRedirectTargets::default(),
        }
    }
}
