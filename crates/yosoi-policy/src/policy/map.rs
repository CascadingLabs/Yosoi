use std::{fmt, time::Duration};

use serde::{
    Deserialize, Deserializer, Serialize,
    de::{Error as _, SeqAccess, Visitor},
};

use crate::PolicyError;

const MAX_FILTER_ITEMS: usize = 128;
const MAX_FILTER_STRING_BYTES: usize = 1_024;

/// Map-specific policy shared by discovery operations.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Map {
    /// Host and path boundary for discovered entries.
    pub scope: Scope,
    /// Whether Map follows links from inspected pages.
    pub pages: PageDiscovery,
    /// Whether Map applies discovered robots rules when exploring pages.
    pub robots: Robots,
    /// Whether Map performs passive subdomain discovery.
    pub subdomains: Subdomains,
    /// Positive request, response, inventory, and time budgets.
    pub limits: Limits,
    /// Discovery response document retention behavior.
    pub documents: DiscoveryDocuments,
    /// URL components used to exclude matching URLs from the inventory.
    pub filters: Filters,
}

impl Map {
    /// Validates all Map-local limits, filters, and scope dependencies.
    pub fn validate(&self) -> Result<(), PolicyError> {
        self.limits.validate()?;
        self.filters.validate()?;
        if matches!(self.subdomains, Subdomains::Passive)
            && !matches!(self.scope.hosts, HostScope::RegistrableDomain)
        {
            return Err(PolicyError::PassiveSubdomainsRequireRegistrableDomain);
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for Map {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct MapValues {
            scope: Scope,
            pages: PageDiscovery,
            #[serde(default)]
            robots: Robots,
            subdomains: Subdomains,
            limits: Limits,
            documents: DiscoveryDocuments,
            #[serde(default)]
            filters: Filters,
        }

        let values = MapValues::deserialize(deserializer)?;
        let map = Self {
            scope: values.scope,
            pages: values.pages,
            robots: values.robots,
            subdomains: values.subdomains,
            limits: values.limits,
            documents: values.documents,
            filters: values.filters,
        };
        map.validate().map_err(D::Error::custom)?;
        Ok(map)
    }
}

/// Host and path dimensions of Map's discovery scope.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Scope {
    /// Which hosts are in scope.
    pub hosts: HostScope,
    /// Which paths on an in-scope host are in scope.
    pub paths: PathScope,
}

/// Hostnames Map may include.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum HostScope {
    /// Only the seed URL's host.
    #[default]
    SeedHost,
    /// The seed's registrable domain and its subdomains.
    RegistrableDomain,
}

/// Paths Map may include on an in-scope host.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PathScope {
    /// The seed path and its descendants.
    #[default]
    SeedSubtree,
    /// Every path on the seed origin.
    EntireOrigin,
}

/// Whether Map follows links from inspected pages.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum PageDiscovery {
    /// Do not inspect pages for further links.
    Disabled,
    /// Inspect pages and follow discovered links within scope.
    #[default]
    Explore,
}

/// Whether Map applies discovered robots rules while exploring pages.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Robots {
    /// Do not filter page requests using robots rules.
    #[default]
    Ignore,
    /// Apply robots rules to page requests within the allowed scope.
    Respect,
}

/// Whether Map performs passive subdomain discovery.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Subdomains {
    /// Do not perform passive subdomain discovery.
    #[default]
    Disabled,
    /// Discover hosts below the seed's registrable domain.
    Passive,
}

/// Whether discovery response documents are retained after inspection.
#[derive(Clone, Copy, Debug, Default, Eq, PartialEq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum DiscoveryDocuments {
    /// Discard response documents after inspecting them.
    #[default]
    DiscardAfterInspection,
    /// Retain response documents within the declared byte budget.
    RetainWithinBudget,
}

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
    const fn validate(&self) -> Result<(), PolicyError> {
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

/// URL components omitted from a Map inventory.
#[derive(Clone, Debug, Default, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Filters {
    /// Query parameter names whose presence excludes a discovered URL.
    pub excluded_query_keys: Vec<String>,
    /// Path prefixes whose matching URLs are excluded.
    pub excluded_path_prefixes: Vec<String>,
}

impl Filters {
    /// Validates the number and UTF-8 size of every filter string.
    pub fn validate(&self) -> Result<(), PolicyError> {
        if self.excluded_query_keys.len() > MAX_FILTER_ITEMS
            || self.excluded_path_prefixes.len() > MAX_FILTER_ITEMS
        {
            return Err(PolicyError::TooManyMapFilters);
        }
        if self
            .excluded_query_keys
            .iter()
            .chain(&self.excluded_path_prefixes)
            .any(|value| value.len() > MAX_FILTER_STRING_BYTES)
        {
            return Err(PolicyError::MapFilterStringTooLong);
        }
        if self.excluded_path_prefixes.iter().any(String::is_empty) {
            return Err(PolicyError::EmptyMapPathPrefix);
        }
        Ok(())
    }
}

impl<'de> Deserialize<'de> for Filters {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct FiltersValues {
            #[serde(default)]
            excluded_query_keys: BoundedStrings<MAX_FILTER_ITEMS>,
            #[serde(default)]
            excluded_path_prefixes: BoundedStrings<MAX_FILTER_ITEMS>,
        }

        let values = FiltersValues::deserialize(deserializer)?;
        let filters = Self {
            excluded_query_keys: values.excluded_query_keys.0,
            excluded_path_prefixes: values.excluded_path_prefixes.0,
        };
        filters.validate().map_err(D::Error::custom)?;
        Ok(filters)
    }
}

struct BoundedStrings<const MAX: usize>(Vec<String>);

impl<const MAX: usize> Default for BoundedStrings<MAX> {
    fn default() -> Self {
        Self(Vec::new())
    }
}

impl<'de, const MAX: usize> Deserialize<'de> for BoundedStrings<MAX> {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        struct BoundedStringsVisitor<const MAX: usize>;

        impl<'de, const MAX: usize> Visitor<'de> for BoundedStringsVisitor<MAX> {
            type Value = BoundedStrings<MAX>;

            fn expecting(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
                write!(formatter, "a sequence of at most {MAX} strings")
            }

            fn visit_seq<A>(self, mut sequence: A) -> Result<Self::Value, A::Error>
            where
                A: SeqAccess<'de>,
            {
                let mut values = Vec::with_capacity(MAX.min(8));
                while let Some(value) = sequence.next_element::<String>()? {
                    if values.len() >= MAX {
                        return Err(A::Error::custom("too many Map filter strings"));
                    }
                    values.push(value);
                }
                Ok(BoundedStrings(values))
            }
        }

        deserializer.deserialize_seq(BoundedStringsVisitor::<MAX>)
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
