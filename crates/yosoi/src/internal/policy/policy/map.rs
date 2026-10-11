mod filters;
mod limits;

pub use filters::Filters;
pub use limits::{Budget, Limits};

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use crate::internal::policy::PolicyError;

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
