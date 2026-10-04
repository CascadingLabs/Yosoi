//! Provider wire adapters for canonical acquisition scope enums.

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use yosoi_types::{BudgetScope, LimitEnforcement};

/// VoidCrawl's frozen snake-case wire adapter for canonical limit enforcement.
///
/// The newtype keeps provider JSON byte-compatible without giving the provider
/// a second semantic enum owner.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct BrowserLimitScope(LimitEnforcement);

#[allow(non_upper_case_globals)]
impl BrowserLimitScope {
    pub const StreamingAdmission: Self = Self(LimitEnforcement::StreamingAdmission);
    pub const RetentionAfterProviderMaterialization: Self =
        Self(LimitEnforcement::RetentionAfterProviderMaterialization);

    pub const fn canonical(self) -> LimitEnforcement {
        self.0
    }
}

impl Serialize for BrowserLimitScope {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(match self.0 {
            LimitEnforcement::StreamingAdmission => "streaming_admission",
            LimitEnforcement::RetentionAfterProviderMaterialization => {
                "retention_after_provider_materialization"
            }
        })
    }
}

impl<'de> Deserialize<'de> for BrowserLimitScope {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        match String::deserialize(deserializer)?.as_str() {
            "streaming_admission" => Ok(Self::StreamingAdmission),
            "retention_after_provider_materialization" => {
                Ok(Self::RetentionAfterProviderMaterialization)
            }
            _ => Err(D::Error::custom("unknown browser limit scope")),
        }
    }
}

/// VoidCrawl's frozen snake-case wire adapter for canonical budget scope.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct BrowserBudgetScope(BudgetScope);

#[allow(non_upper_case_globals)]
impl BrowserBudgetScope {
    pub const PerPayload: Self = Self(BudgetScope::PerPayload);
    pub const CaptureAggregate: Self = Self(BudgetScope::CaptureAggregate);

    pub const fn canonical(self) -> BudgetScope {
        self.0
    }
}

impl Serialize for BrowserBudgetScope {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: serde::Serializer,
    {
        serializer.serialize_str(match self.0 {
            BudgetScope::PerPayload => "per_payload",
            BudgetScope::CaptureAggregate => "capture_aggregate",
        })
    }
}

impl<'de> Deserialize<'de> for BrowserBudgetScope {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        match String::deserialize(deserializer)?.as_str() {
            "per_payload" => Ok(Self::PerPayload),
            "capture_aggregate" => Ok(Self::CaptureAggregate),
            _ => Err(D::Error::custom("unknown browser budget scope")),
        }
    }
}
