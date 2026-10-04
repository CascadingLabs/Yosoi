use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};

use crate::PolicyError;

/// Positive potentially-large document or locator count.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct CountLimit(u64);

impl CountLimit {
    pub const fn get(self) -> u64 {
        self.0
    }

    pub(super) const fn validated(value: u64) -> Self {
        Self(value)
    }
}

impl TryFrom<u64> for CountLimit {
    type Error = PolicyError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        if value == 0 {
            Err(PolicyError::ZeroCountLimit)
        } else {
            Ok(Self(value))
        }
    }
}

impl Serialize for CountLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for CountLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::try_from(u64::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

/// Positive fixed-width step, depth, or region count.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct StepLimit(u32);

impl StepLimit {
    pub const fn get(self) -> u32 {
        self.0
    }

    pub(super) const fn validated(value: u32) -> Self {
        Self(value)
    }
}

impl TryFrom<u32> for StepLimit {
    type Error = PolicyError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        if value == 0 {
            Err(PolicyError::ZeroStepLimit)
        } else {
            Ok(Self(value))
        }
    }
}

impl Serialize for StepLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u32(self.0)
    }
}

impl<'de> Deserialize<'de> for StepLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::try_from(u32::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}
