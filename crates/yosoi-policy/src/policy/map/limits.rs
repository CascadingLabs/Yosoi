use std::time::Duration;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use crate::PolicyError;

/// Positive Map budget. Zero never means unlimited.
#[derive(Clone, Copy, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
pub struct Budget(u32);

impl Budget {
    /// Constructs a positive budget.
    pub const fn new(value: u32) -> Result<Self, PolicyError> {
        if value == 0 {
            return Err(PolicyError::ZeroMapBudget);
        }
        Ok(Self(value))
    }

    /// Returns the exact positive budget.
    pub const fn get(self) -> u32 {
        self.0
    }
}

impl<'de> Deserialize<'de> for Budget {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let value = u32::deserialize(deserializer)?;
        Self::new(value).map_err(D::Error::custom)
    }
}

/// Positive count, byte, concurrency, and elapsed-time bounds for Map.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Limits {
    /// Maximum number of link-following levels below the seed page.
    pub max_link_depth: u16,
    /// Maximum distinct hosts admitted to the inventory.
    pub max_hosts: Budget,
    /// Maximum distinct URLs admitted to the inventory.
    pub max_urls: Budget,
    /// Maximum recorded URL relationships.
    pub max_relationships: Budget,
    /// Maximum recorded provenance observations.
    pub max_observations: Budget,
    /// Maximum queued URLs waiting for inspection.
    pub max_pending: Budget,
    /// Maximum outgoing acquisition requests.
    pub max_requests: Budget,
    /// Maximum sitemap documents inspected.
    pub max_sitemaps: Budget,
    /// Maximum nested sitemap index depth.
    pub max_sitemap_depth: u16,
    /// Maximum bytes admitted from one response.
    pub max_response_bytes: Budget,
    /// Maximum response bytes admitted across the operation.
    pub max_total_response_bytes: Budget,
    /// Maximum response document bytes retained for later use.
    pub max_retained_document_bytes: Budget,
    /// Maximum number of concurrent requests.
    pub max_concurrency: Budget,
    /// Maximum total elapsed time for the Map operation.
    #[serde(with = "duration_value")]
    pub maximum_elapsed: Duration,
    /// Maximum UTF-8 byte length of one normalized URL.
    pub max_url_bytes: Budget,
    /// Maximum aggregate bytes in the serialized inventory.
    pub max_inventory_bytes: Budget,
    /// Maximum entries accepted by one parsed discovery document.
    pub max_parser_entries: Budget,
    /// Maximum UTF-8 byte length of one hostname.
    pub max_hostname_bytes: Budget,
}

impl Limits {
    pub(super) const fn validate(&self) -> Result<(), PolicyError> {
        if self.maximum_elapsed.is_zero() {
            return Err(PolicyError::ZeroMapMaximumElapsed);
        }
        Ok(())
    }
}

impl Default for Limits {
    fn default() -> Self {
        Self {
            max_link_depth: 2,
            max_hosts: Budget(50),
            max_urls: Budget(500),
            max_relationships: Budget(2_000),
            max_observations: Budget(4_000),
            max_pending: Budget(500),
            max_requests: Budget(100),
            max_sitemaps: Budget(20),
            max_sitemap_depth: 3,
            max_response_bytes: Budget(2_097_152),
            max_total_response_bytes: Budget(20_971_520),
            max_retained_document_bytes: Budget(8_388_608),
            max_concurrency: Budget(2),
            maximum_elapsed: Duration::from_secs(30),
            max_url_bytes: Budget(8_192),
            max_inventory_bytes: Budget(4_194_304),
            max_parser_entries: Budget(10_000),
            max_hostname_bytes: Budget(253),
        }
    }
}

impl<'de> Deserialize<'de> for Limits {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct LimitsValues {
            max_link_depth: u16,
            max_hosts: Budget,
            max_urls: Budget,
            max_relationships: Budget,
            max_observations: Budget,
            max_pending: Budget,
            max_requests: Budget,
            max_sitemaps: Budget,
            max_sitemap_depth: u16,
            max_response_bytes: Budget,
            max_total_response_bytes: Budget,
            max_retained_document_bytes: Budget,
            max_concurrency: Budget,
            #[serde(with = "duration_value")]
            maximum_elapsed: Duration,
            max_url_bytes: Budget,
            max_inventory_bytes: Budget,
            max_parser_entries: Budget,
            max_hostname_bytes: Budget,
        }

        let values = LimitsValues::deserialize(deserializer)?;
        let limits = Self {
            max_link_depth: values.max_link_depth,
            max_hosts: values.max_hosts,
            max_urls: values.max_urls,
            max_relationships: values.max_relationships,
            max_observations: values.max_observations,
            max_pending: values.max_pending,
            max_requests: values.max_requests,
            max_sitemaps: values.max_sitemaps,
            max_sitemap_depth: values.max_sitemap_depth,
            max_response_bytes: values.max_response_bytes,
            max_total_response_bytes: values.max_total_response_bytes,
            max_retained_document_bytes: values.max_retained_document_bytes,
            max_concurrency: values.max_concurrency,
            maximum_elapsed: values.maximum_elapsed,
            max_url_bytes: values.max_url_bytes,
            max_inventory_bytes: values.max_inventory_bytes,
            max_parser_entries: values.max_parser_entries,
            max_hostname_bytes: values.max_hostname_bytes,
        };
        limits.validate().map_err(D::Error::custom)?;
        Ok(limits)
    }
}

mod duration_value {
    use std::time::Duration;

    use serde::{Deserialize, Deserializer, Serialize, Serializer, de::Error as _};

    use crate::PolicyError;

    #[derive(Serialize, Deserialize)]
    #[serde(deny_unknown_fields)]
    struct DurationParts {
        seconds: u64,
        nanoseconds: u32,
    }

    pub(super) fn serialize<S>(value: &Duration, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        DurationParts {
            seconds: value.as_secs(),
            nanoseconds: value.subsec_nanos(),
        }
        .serialize(serializer)
    }

    pub(super) fn deserialize<'de, D>(deserializer: D) -> Result<Duration, D::Error>
    where
        D: Deserializer<'de>,
    {
        let parts = DurationParts::deserialize(deserializer)?;
        if parts.nanoseconds >= 1_000_000_000 {
            return Err(D::Error::custom(PolicyError::InvalidMapDuration));
        }
        let value = Duration::new(parts.seconds, parts.nanoseconds);
        if value.is_zero() {
            return Err(D::Error::custom(PolicyError::ZeroMapMaximumElapsed));
        }
        Ok(value)
    }
}
