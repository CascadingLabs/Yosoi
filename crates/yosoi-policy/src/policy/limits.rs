use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};
use std::num::NonZeroU32;
use yosoi_types::{ByteLimit, ByteLimitError, CaptureDeadline, CaptureDeadlineError};

use crate::PolicyError;

/// Positive byte limit that is addressable by an in-memory platform buffer.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AddressableByteLimit(u64);

impl AddressableByteLimit {
    /// Returns the exact byte limit as a platform-sized value.
    pub fn as_usize(self) -> Result<usize, PolicyError> {
        usize::try_from(self.0).map_err(|_| PolicyError::ByteLimitNotAddressable)
    }

    /// Converts to the shared positive byte-limit primitive.
    pub fn to_byte_limit(self) -> Result<ByteLimit, ByteLimitError> {
        ByteLimit::try_from(self.0)
    }

    /// Returns the exact canonical byte limit.
    pub const fn get(self) -> u64 {
        self.0
    }

    pub(super) const fn default_content_coded() -> Self {
        Self(8_000_000)
    }

    pub(super) const fn default_representation() -> Self {
        Self(16_000_000)
    }

    pub(super) const fn default_unicode_utf8() -> Self {
        Self(32_000_000)
    }

    pub(super) const fn default_browser_bytes() -> Self {
        Self(16_000_000)
    }

    pub(super) const fn default_document_input() -> Self {
        Self(67_108_864)
    }

    pub(super) const fn default_locator_query() -> Self {
        Self(65_536)
    }

    pub(super) const fn default_locator_output() -> Self {
        Self(16_777_216)
    }
}

impl TryFrom<u64> for AddressableByteLimit {
    type Error = PolicyError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err(PolicyError::ZeroByteLimit);
        }
        usize::try_from(value).map_err(|_| PolicyError::ByteLimitNotAddressable)?;
        Ok(Self(value))
    }
}

impl Serialize for AddressableByteLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for AddressableByteLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u64::deserialize(deserializer)?;
        Self::try_from(value).map_err(D::Error::custom)
    }
}

/// Positive event limit addressable by the navigation capture implementation.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct EventLimit(u64);

impl EventLimit {
    /// Returns the exact event limit.
    pub const fn get(self) -> u64 {
        self.0
    }

    /// Converts to the platform-sized event count used by capture providers.
    pub fn as_usize(self) -> Result<usize, PolicyError> {
        usize::try_from(self.0).map_err(|_| PolicyError::EventLimitNotAddressable)
    }
}

impl TryFrom<u64> for EventLimit {
    type Error = PolicyError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err(PolicyError::ZeroEventLimit);
        }
        usize::try_from(value).map_err(|_| PolicyError::EventLimitNotAddressable)?;
        Ok(Self(value))
    }
}

impl Default for EventLimit {
    fn default() -> Self {
        Self(10_000)
    }
}

impl Serialize for EventLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for EventLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u64::deserialize(deserializer)?;
        Self::try_from(value).map_err(D::Error::custom)
    }
}

/// Positive maximum number of browser resources admitted to one capture.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct ResourceLimit(u32);

impl ResourceLimit {
    /// Returns the exact resource limit.
    pub const fn get(self) -> u32 {
        self.0
    }

    /// Converts to the provider's nonzero resource bound.
    pub fn to_nonzero(self) -> Result<NonZeroU32, PolicyError> {
        NonZeroU32::new(self.0).ok_or(PolicyError::ZeroResourceLimit)
    }

    pub(super) const fn default_resource_count() -> Self {
        Self(1_000)
    }
}

impl TryFrom<u32> for ResourceLimit {
    type Error = PolicyError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err(PolicyError::ZeroResourceLimit);
        }
        usize::try_from(value).map_err(|_| PolicyError::ResourceLimitNotAddressable)?;
        Ok(Self(value))
    }
}

impl Serialize for ResourceLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u32(self.0)
    }
}

impl<'de> Deserialize<'de> for ResourceLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u32::deserialize(deserializer)?;
        Self::try_from(value).map_err(D::Error::custom)
    }
}

/// Positive maximum number of nodes in an accessibility-tree response.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct AccessibilityNodeLimit(u32);

impl AccessibilityNodeLimit {
    /// Returns the exact accessibility-node limit.
    pub const fn get(self) -> u32 {
        self.0
    }

    /// Converts to the provider's nonzero node bound.
    pub fn to_nonzero(self) -> Result<NonZeroU32, PolicyError> {
        NonZeroU32::new(self.0).ok_or(PolicyError::ZeroAccessibilityNodeLimit)
    }

    pub(super) const fn default_accessibility_node_count() -> Self {
        Self(10_000)
    }
}

impl TryFrom<u32> for AccessibilityNodeLimit {
    type Error = PolicyError;

    fn try_from(value: u32) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err(PolicyError::ZeroAccessibilityNodeLimit);
        }
        usize::try_from(value).map_err(|_| PolicyError::AccessibilityNodeLimitNotAddressable)?;
        Ok(Self(value))
    }
}

impl Serialize for AccessibilityNodeLimit {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u32(self.0)
    }
}

impl<'de> Deserialize<'de> for AccessibilityNodeLimit {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u32::deserialize(deserializer)?;
        Self::try_from(value).map_err(D::Error::custom)
    }
}

/// Positive maximum elapsed attempt time in microseconds.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd)]
pub struct MaximumElapsed(u64);

impl MaximumElapsed {
    /// Returns the positive elapsed bound in microseconds.
    pub const fn as_microseconds(self) -> u64 {
        self.0
    }

    /// Converts to the shared monotonic capture-deadline primitive.
    pub fn to_capture_deadline(self) -> Result<CaptureDeadline, CaptureDeadlineError> {
        CaptureDeadline::try_from(self.0)
    }
}

impl TryFrom<u64> for MaximumElapsed {
    type Error = PolicyError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        if value == 0 {
            return Err(PolicyError::ZeroMaximumElapsed);
        }
        Ok(Self(value))
    }
}

impl Default for MaximumElapsed {
    fn default() -> Self {
        Self(10_000_000)
    }
}

impl MaximumElapsed {
    pub(super) const fn default_search() -> Self {
        Self(30_000_000)
    }

    pub(super) const fn default_search_browser_request() -> Self {
        Self(20_000_000)
    }
}

impl Serialize for MaximumElapsed {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        serializer.serialize_u64(self.0)
    }
}

impl<'de> Deserialize<'de> for MaximumElapsed {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u64::deserialize(deserializer)?;
        Self::try_from(value).map_err(D::Error::custom)
    }
}
