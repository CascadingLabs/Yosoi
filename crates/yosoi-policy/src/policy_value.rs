use serde::{
    Deserialize, Deserializer, Serialize, Serializer, de::Error as _, ser::Error as SerError,
};

use crate::{
    EffectivePolicyIdentity, PolicyError,
    policy::{
        Acquisition, AcquisitionKind, DiscoveryDocuments, DocumentRequest, Documents,
        EffectivePage, EffectiveSearch, Filters, Limits, Locators, Map, Page, PageDiscovery,
        ProfileSelection, ProviderDefaultsStatus, Request, Robots, Scope, Search, Subdomains,
        Tuning,
    },
};

const POLICY_SCHEMA_VERSION: u16 = 5;
const LEGACY_POLICY_SCHEMA_VERSION_V4_SEARCH: u16 = 4;
const LEGACY_POLICY_SCHEMA_VERSION_V2: u16 = 2;
const LEGACY_POLICY_SCHEMA_VERSION_V3_MAP: u16 = 3;

/// Complete page, request, document, and locator policy values.
///
/// The fields remain public so applications can author ordinary struct values.
/// Validation runs before serialization and identity calculation.
#[derive(Clone, Debug, Default, Eq, PartialEq)]
pub struct Policy {
    /// Ordered acquisition and document-selection choices.
    pub page: Page,
    /// Shared deadline, domain-specific bounds, and Direct HTTP redirects.
    pub request: Request,
    /// Immutable document parser limits.
    pub documents: Documents,
    /// Locator plan and evaluation limits.
    pub locators: Locators,
    /// Requested execution tuning; default retains the package's current choices.
    pub tuning: Tuning,
    /// Map discovery and inventory policy.
    pub map: Map,
    /// Ordered provider choices and hard Search resource bounds.
    pub search: Search,
}

impl Policy {
    /// Validates nested page choices and all typed policy bounds.
    pub fn validate(&self) -> Result<(), PolicyError> {
        self.page.validate()?;
        self.request.validate()?;
        self.map.validate()?;
        self.search.validate()
    }

    /// Encodes the validated policy values as compact JSON.
    pub fn to_canonical_json(&self) -> Result<String, PolicyError> {
        serde_json::to_string(self).map_err(|error| PolicyError::Serialization(error.to_string()))
    }

    /// Resolves Current document selections into a stable effective snapshot.
    pub fn effective_policy(&self) -> Result<EffectivePolicy, PolicyError> {
        self.validate()?;
        Ok(EffectivePolicy {
            page: self.page.effective(),
            request: self.request,
            documents: self.documents,
            locators: self.locators,
            tuning: self.tuning,
            map: self.map.clone(),
            search: self.search.effective(),
        })
    }

    /// Computes the versioned identity of the effective behavior.
    pub fn effective_identity(&self) -> Result<EffectivePolicyIdentity, PolicyError> {
        self.effective_policy()?.identity()
    }

    /// Verifies that an archived effective snapshot retains this Policy's authored choices.
    ///
    /// Current routes are checked against their recorded status and profile
    /// shape, without resolving them against today's defaults registry.
    #[doc(hidden)]
    pub fn validate_effective_snapshot(
        &self,
        effective: &EffectivePolicy,
    ) -> Result<(), PolicyError> {
        self.validate()?;
        effective.search.validate()?;
        if effective.request != self.request
            || effective.documents != self.documents
            || effective.locators != self.locators
            || effective.tuning != self.tuning
            || effective.map != self.map
        {
            return Err(PolicyError::ArchivedSnapshotMismatch);
        }

        if self.page.acquisitions.len() != effective.page.acquisitions.len() {
            return Err(PolicyError::ArchivedSnapshotMismatch);
        }
        let mut structurally_valid_page = Vec::with_capacity(effective.page.acquisitions.len());
        for (authored, resolved) in self
            .page
            .acquisitions
            .iter()
            .zip(&effective.page.acquisitions)
        {
            if authored.kind() != resolved.acquisition
                || authored.selection_kind() != resolved.authored_selection
            {
                return Err(PolicyError::ArchivedSnapshotMismatch);
            }
            if let Some(exact_documents) = authored.exact_documents()
                && exact_documents != resolved.documents
            {
                return Err(PolicyError::ArchivedSnapshotMismatch);
            }
            structurally_valid_page.push(Acquisition::Exact {
                acquisition: resolved.acquisition,
                documents: resolved.documents.clone(),
            });
        }
        Page::new(structurally_valid_page).map_err(|_| PolicyError::ArchivedSnapshotMismatch)?;

        let authored_search = &self.search;
        let effective_search = &effective.search;
        if authored_search.max_in_flight != effective_search.max_in_flight
            || authored_search.max_browser_in_flight != effective_search.max_browser_in_flight
            || authored_search.max_results_per_provider != effective_search.max_results_per_provider
            || authored_search.max_total_results != effective_search.max_total_results
            || authored_search.max_retained_content_bytes
                != effective_search.max_retained_content_bytes
            || authored_search.maximum_elapsed != effective_search.maximum_elapsed
            || authored_search.providers.len() != effective_search.providers.len()
        {
            return Err(PolicyError::ArchivedSnapshotMismatch);
        }

        for (authored, resolved) in authored_search
            .providers
            .iter()
            .zip(&effective_search.providers)
        {
            if authored.provider != resolved.provider
                || authored.profile.kind() != resolved.profile_selection_kind
            {
                return Err(PolicyError::ArchivedSnapshotMismatch);
            }
            match (
                &authored.profile,
                resolved.defaults_status,
                &resolved.profile,
            ) {
                (
                    ProfileSelection::Current,
                    ProviderDefaultsStatus::Unavailable { .. }
                    | ProviderDefaultsStatus::Preview { .. }
                    | ProviderDefaultsStatus::Certified { .. },
                    _,
                ) => {}
                (
                    ProfileSelection::Exact(authored_profile),
                    ProviderDefaultsStatus::Exact,
                    Some(resolved_profile),
                ) if authored_profile == resolved_profile => {}
                _ => return Err(PolicyError::ArchivedSnapshotMismatch),
            }
        }
        Ok(())
    }

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

    pub(crate) fn identity(&self) -> Result<EffectivePolicyIdentity, PolicyError> {
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

impl Serialize for Policy {
    fn serialize<S>(&self, serializer: S) -> Result<S::Ok, S::Error>
    where
        S: Serializer,
    {
        self.validate().map_err(SerError::custom)?;
        PolicyRef {
            page: &self.page,
            request: &self.request,
            documents: &self.documents,
            locators: &self.locators,
            tuning: self.tuning,
            map: &self.map,
            search: &self.search,
        }
        .serialize(serializer)
    }
}

impl<'de> Deserialize<'de> for Policy {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        let values = PolicyValues::deserialize(deserializer)?;
        let policy = Self {
            page: values.page,
            request: values.request,
            documents: values.documents,
            locators: values.locators,
            tuning: values.tuning,
            map: values.map,
            search: values.search,
        };
        policy.validate().map_err(D::Error::custom)?;
        Ok(policy)
    }
}

#[derive(Serialize)]
struct PolicyRef<'a> {
    page: &'a Page,
    request: &'a Request,
    documents: &'a Documents,
    locators: &'a Locators,
    #[serde(skip_serializing_if = "Tuning::is_default")]
    tuning: Tuning,
    map: &'a Map,
    search: &'a Search,
}

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PolicyValues {
    page: Page,
    request: Request,
    documents: Documents,
    locators: Locators,
    #[serde(default)]
    tuning: Tuning,
    #[serde(default)]
    map: Map,
    #[serde(default = "Search::disabled")]
    search: Search,
}
