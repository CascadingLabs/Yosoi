use serde::{Deserialize, Serialize};

use crate::internal::policy::{
    EffectivePolicyIdentity, PolicyError,
    policy::{
        AcquisitionKind, DiscoveryDocuments, DocumentRequest, Documents, EffectivePage,
        EffectiveSearch, Filters, Limits, Locators, Map, PageDiscovery, Request, Robots, Scope,
        Subdomains, Tuning,
    },
    policy_value::Policy,
};

const POLICY_SCHEMA_VERSION: u16 = 5;
const LEGACY_POLICY_SCHEMA_VERSION_V4_SEARCH: u16 = 4;
const LEGACY_POLICY_SCHEMA_VERSION_V2: u16 = 2;
const LEGACY_POLICY_SCHEMA_VERSION_V3_MAP: u16 = 3;

impl Policy {
    /// Computes the pre-Search v2 identity used to verify historical archives.
    ///
    /// Archive readers call this only for Policy records written with the
    /// legacy archive schema, before a Search section existed.
    #[doc(hidden)]
    pub fn archived_v2_identity(&self) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.validate()?;
        if self.search.is_enabled() {
            return Err(PolicyError::LegacyIdentityCannotIncludeSearch);
        }
        if self.map != Map::default() {
            return Err(PolicyError::LegacyIdentityCannotIncludeMap);
        }
        let effective_page = self.page.effective();
        let acquisitions = effective_page
            .acquisitions
            .iter()
            .map(|acquisition| EffectiveAcquisitionIdentityRef {
                acquisition: acquisition.acquisition,
                documents: &acquisition.documents,
            })
            .collect();
        let json = serde_json::to_string(&LegacyEffectivePolicyIdentityEnvelopeV2Ref {
            schema_version: LEGACY_POLICY_SCHEMA_VERSION_V2,
            policy: LegacyEffectivePolicyIdentityBodyV2Ref {
                page: EffectivePageIdentityRef { acquisitions },
                request: &self.request,
                documents: &self.documents,
                locators: &self.locators,
                tuning: self.tuning,
            },
        })
        .map_err(|error| PolicyError::Serialization(error.to_string()))?;
        Ok(EffectivePolicyIdentity::from_legacy_v2_json(&json))
    }

    /// Computes the Map-era v3 identity for a historical Policy archive.
    /// The v3 projection included Map but preceded Search.
    #[doc(hidden)]
    pub fn archived_v3_map_identity(&self) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.validate()?;
        if self.search.is_enabled() {
            return Err(PolicyError::LegacyIdentityCannotIncludeSearch);
        }
        let effective_page = self.page.effective();
        let acquisitions = effective_page
            .acquisitions
            .iter()
            .map(|acquisition| EffectiveAcquisitionIdentityRef {
                acquisition: acquisition.acquisition,
                documents: &acquisition.documents,
            })
            .collect();
        let json = serde_json::to_string(&LegacyEffectivePolicyIdentityEnvelopeV3MapRef {
            schema_version: LEGACY_POLICY_SCHEMA_VERSION_V3_MAP,
            policy: LegacyEffectivePolicyIdentityBodyV3MapRef {
                page: EffectivePageIdentityRef { acquisitions },
                request: &self.request,
                documents: &self.documents,
                locators: &self.locators,
                tuning: self.tuning,
                map: &self.map,
            },
        })
        .map_err(|error| PolicyError::Serialization(error.to_string()))?;
        Ok(EffectivePolicyIdentity::from_legacy_v3_map_json(&json))
    }

    /// Computes the original Map-era v3 identity before `Map.robots` existed.
    #[doc(hidden)]
    pub fn archived_v3_map_pre_robots_identity(
        &self,
    ) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.validate()?;
        if self.search.is_enabled() {
            return Err(PolicyError::LegacyIdentityCannotIncludeSearch);
        }
        if self.map.robots != Robots::Ignore {
            return Err(PolicyError::LegacyIdentityCannotIncludeRobots);
        }
        let effective_page = self.page.effective();
        let acquisitions = effective_page
            .acquisitions
            .iter()
            .map(|acquisition| EffectiveAcquisitionIdentityRef {
                acquisition: acquisition.acquisition,
                documents: &acquisition.documents,
            })
            .collect();
        let map = &self.map;
        let json = serde_json::to_string(&LegacyEffectivePolicyIdentityEnvelopeV3PreRobotsRef {
            schema_version: LEGACY_POLICY_SCHEMA_VERSION_V3_MAP,
            policy: LegacyEffectivePolicyIdentityBodyV3PreRobotsRef {
                page: EffectivePageIdentityRef { acquisitions },
                request: &self.request,
                documents: &self.documents,
                locators: &self.locators,
                tuning: self.tuning,
                map: LegacyMapPreRobotsRef {
                    scope: &map.scope,
                    pages: &map.pages,
                    subdomains: &map.subdomains,
                    limits: &map.limits,
                    documents: &map.documents,
                    filters: &map.filters,
                },
            },
        })
        .map_err(|error| PolicyError::Serialization(error.to_string()))?;
        Ok(EffectivePolicyIdentity::from_legacy_v3_map_json(&json))
    }
}

/// Validated policy behavior with all Current document selections expanded.
///
/// The effective page records the caller's Current or Exact selection and the
/// concrete ordered documents resolved for this snapshot. Effective identity
/// excludes that authored marker and hashes only the resolved behavior.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectivePolicy {
    /// Ordered acquisitions with exact effective document requests.
    pub page: EffectivePage,
    /// Shared deadline, domain-specific bounds, and Direct HTTP redirects.
    pub request: Request,
    /// Immutable document parser limits.
    pub documents: Documents,
    /// Locator plan and evaluation limits.
    pub locators: Locators,
    /// Requested execution tuning.
    pub tuning: Tuning,
    /// Map discovery and inventory behavior.
    pub map: Map,
    /// Resolved Search provider routes and resource bounds.
    pub search: EffectiveSearch,
}

impl EffectivePolicy {
    /// Validates the stored effective behavior and computes its versioned identity.
    pub fn effective_identity(&self) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.page.validate()?;
        self.request.validate()?;
        self.map.validate()?;
        self.search.validate()?;
        let acquisitions = self
            .page
            .acquisitions
            .iter()
            .map(|acquisition| EffectiveAcquisitionIdentityRef {
                acquisition: acquisition.acquisition,
                documents: &acquisition.documents,
            })
            .collect();
        let json = serde_json::to_string(&EffectivePolicyIdentityEnvelopeRef {
            schema_version: POLICY_SCHEMA_VERSION,
            policy: EffectivePolicyIdentityBodyRef {
                page: EffectivePageIdentityRef { acquisitions },
                request: &self.request,
                documents: &self.documents,
                locators: &self.locators,
                tuning: self.tuning,
                map: &self.map,
                search: &self.search,
            },
        })
        .map_err(|error| PolicyError::Serialization(error.to_string()))?;
        Ok(EffectivePolicyIdentity::from_canonical_json(&json))
    }

    /// Computes the Search-era v4 identity before `Map.robots` existed.
    #[doc(hidden)]
    pub fn archived_v4_search_pre_robots_identity(
        &self,
    ) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.page.validate()?;
        self.request.validate()?;
        self.map.validate()?;
        self.search.validate()?;
        if self.map.robots != Robots::Ignore {
            return Err(PolicyError::LegacyIdentityCannotIncludeRobots);
        }
        let acquisitions = self
            .page
            .acquisitions
            .iter()
            .map(|acquisition| EffectiveAcquisitionIdentityRef {
                acquisition: acquisition.acquisition,
                documents: &acquisition.documents,
            })
            .collect();
        let map = &self.map;
        let json = serde_json::to_string(&LegacyEffectivePolicyIdentityEnvelopeV4PreRobotsRef {
            schema_version: LEGACY_POLICY_SCHEMA_VERSION_V4_SEARCH,
            policy: LegacyEffectivePolicyIdentityBodyV4PreRobotsRef {
                page: EffectivePageIdentityRef { acquisitions },
                request: &self.request,
                documents: &self.documents,
                locators: &self.locators,
                tuning: self.tuning,
                map: LegacyMapPreRobotsRef {
                    scope: &map.scope,
                    pages: &map.pages,
                    subdomains: &map.subdomains,
                    limits: &map.limits,
                    documents: &map.documents,
                    filters: &map.filters,
                },
                search: &self.search,
            },
        })
        .map_err(|error| PolicyError::Serialization(error.to_string()))?;
        Ok(EffectivePolicyIdentity::from_legacy_v4_json(&json))
    }

    pub(in crate::internal::policy) fn identity(
        &self,
    ) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.effective_identity()
    }
}

#[derive(Serialize)]
struct EffectivePolicyIdentityEnvelopeRef<'a> {
    schema_version: u16,
    policy: EffectivePolicyIdentityBodyRef<'a>,
}

#[derive(Serialize)]
struct EffectivePolicyIdentityBodyRef<'a> {
    page: EffectivePageIdentityRef<'a>,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
    map: &'a Map,
    search: &'a EffectiveSearch,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityEnvelopeV4PreRobotsRef<'a> {
    schema_version: u16,
    policy: LegacyEffectivePolicyIdentityBodyV4PreRobotsRef<'a>,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityBodyV4PreRobotsRef<'a> {
    page: EffectivePageIdentityRef<'a>,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
    map: LegacyMapPreRobotsRef<'a>,
    search: &'a EffectiveSearch,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityEnvelopeV2Ref<'a> {
    schema_version: u16,
    policy: LegacyEffectivePolicyIdentityBodyV2Ref<'a>,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityBodyV2Ref<'a> {
    page: EffectivePageIdentityRef<'a>,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityEnvelopeV3MapRef<'a> {
    schema_version: u16,
    policy: LegacyEffectivePolicyIdentityBodyV3MapRef<'a>,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityBodyV3MapRef<'a> {
    page: EffectivePageIdentityRef<'a>,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
    map: &'a Map,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityEnvelopeV3PreRobotsRef<'a> {
    schema_version: u16,
    policy: LegacyEffectivePolicyIdentityBodyV3PreRobotsRef<'a>,
}

#[derive(Serialize)]
struct LegacyEffectivePolicyIdentityBodyV3PreRobotsRef<'a> {
    page: EffectivePageIdentityRef<'a>,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
    map: LegacyMapPreRobotsRef<'a>,
}

#[derive(Serialize)]
struct LegacyMapPreRobotsRef<'a> {
    scope: &'a Scope,
    pages: &'a PageDiscovery,
    subdomains: &'a Subdomains,
    limits: &'a Limits,
    documents: &'a DiscoveryDocuments,
    filters: &'a Filters,
}

#[derive(Serialize)]
struct EffectivePageIdentityRef<'a> {
    acquisitions: Vec<EffectiveAcquisitionIdentityRef<'a>>,
}

#[derive(Serialize)]
struct EffectiveAcquisitionIdentityRef<'a> {
    acquisition: AcquisitionKind,
    documents: &'a [DocumentRequest],
}
