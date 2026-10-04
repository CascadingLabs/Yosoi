use std::num::{NonZeroU16, NonZeroU32, NonZeroUsize};

use serde::{Deserialize, Serialize};

use crate::PolicyError;

use super::{
    Acquisition, AddressableByteLimit, BrowserMode, DocumentRequest, Documents, MaximumElapsed,
    Page, Request,
};

/// Version of the provider-default registry used by effective Search snapshots.
pub const PROVIDER_DEFAULTS_REGISTRY_VERSION: u16 = 4;

/// A supported Search provider.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum Provider {
    Brave,
    Bing,
    DuckDuckGo,
}

impl Provider {
    /// Returns the versioned local profile's current certification state.
    pub fn defaults_status(self) -> ProviderDefaultsStatus {
        let version = match self {
            Self::Brave | Self::Bing => NonZeroU16::new(2).unwrap_or(NonZeroU16::MIN),
            Self::DuckDuckGo => NonZeroU16::MIN,
        };
        ProviderDefaultsStatus::Preview {
            version: ProviderDefaultsVersion(version),
        }
    }

    fn current_profile(self) -> ProviderRequestProfile {
        let mut request = Request::default();
        let page = match self {
            Self::Bing => Page::default(),
            Self::Brave | Self::DuckDuckGo => {
                request.maximum_elapsed = MaximumElapsed::default_search_browser_request();
                Page {
                    acquisitions: vec![Acquisition::Browser(BrowserMode::Headless).documents([
                        DocumentRequest::ResponseDocument,
                        DocumentRequest::RenderedDom,
                    ])],
                }
            }
        };
        ProviderRequestProfile {
            page,
            request,
            documents: Documents::default(),
        }
    }
}

/// A version identifier for one certified provider Requests profile.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct ProviderDefaultsVersion(NonZeroU16);

impl ProviderDefaultsVersion {
    /// Creates a positive provider-default version.
    pub fn try_new(version: u16) -> Result<Self, PolicyError> {
        NonZeroU16::new(version)
            .map(Self)
            .ok_or(PolicyError::ZeroProviderDefaultsVersion)
    }

    /// Returns the positive version number.
    pub const fn get(self) -> u16 {
        self.0.get()
    }
}

/// Whether the provider registry can supply a certified Current profile.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ProviderDefaultsStatus {
    /// No certified Current profile is available in this registry revision.
    Unavailable { registry_version: u16 },
    /// A versioned local profile is available while certification remains open.
    Preview { version: ProviderDefaultsVersion },
    /// A certified Current profile is available at this provider version.
    Certified { version: ProviderDefaultsVersion },
    /// The route was pinned explicitly and does not use provider defaults.
    Exact,
}

/// Whether a provider selection was authored as Current or Exact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ProfileSelectionKind {
    Current,
    Exact,
}

/// A complete existing Requests policy profile for one provider.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderRequestProfile {
    /// Acquisition and requested-document choices.
    pub page: Page,
    /// Request deadline, transport limits, and redirect behavior.
    pub request: Request,
    /// Document parsing limits.
    pub documents: Documents,
}

impl ProviderRequestProfile {
    /// Creates a complete Requests profile and validates its nested policy.
    pub fn new(page: Page, request: Request, documents: Documents) -> Result<Self, PolicyError> {
        page.validate()?;
        request.validate()?;
        Ok(Self {
            page,
            request,
            documents,
        })
    }

    /// Returns the acquisition and requested-document choices.
    pub const fn page(&self) -> &Page {
        &self.page
    }

    /// Returns request deadlines, transport limits, and redirect behavior.
    pub const fn request(&self) -> &Request {
        &self.request
    }

    /// Returns document parsing limits.
    pub const fn documents(&self) -> &Documents {
        &self.documents
    }

    fn validate(&self) -> Result<(), PolicyError> {
        self.page.validate()?;
        self.request.validate()
    }
}

/// One provider in authored response order, with its Requests profile choice.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct ProviderSelection {
    /// Provider whose result slot occupies this position.
    pub provider: Provider,
    /// Current certified defaults or a complete explicit Requests profile.
    pub profile: ProfileSelection,
}

impl ProviderSelection {
    /// Selects the provider's current certified Requests profile.
    pub const fn current(provider: Provider) -> Self {
        Self {
            provider,
            profile: ProfileSelection::Current,
        }
    }

    /// Selects a complete explicit Requests profile for the provider.
    pub const fn exact(provider: Provider, profile: ProviderRequestProfile) -> Self {
        Self {
            provider,
            profile: ProfileSelection::Exact(profile),
        }
    }
}

/// How Search obtains one provider's Requests profile.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "kind",
    content = "profile",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum ProfileSelection {
    /// Resolve the provider's current certified Requests profile.
    Current,
    /// Pin one complete general Requests profile in the Search policy.
    Exact(ProviderRequestProfile),
}

impl ProfileSelection {
    /// Returns whether this is a Current or Exact profile declaration.
    pub const fn kind(&self) -> ProfileSelectionKind {
        match self {
            Self::Current => ProfileSelectionKind::Current,
            Self::Exact(_) => ProfileSelectionKind::Exact,
        }
    }
}

/// Search provider selection and resource bounds.
///
/// The default selects all three local-preview providers with five hits each.
/// Use `Search::disabled()` when a child Request or historical policy must not search.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct Search {
    /// Providers in authored and response-slot order.
    pub providers: Vec<ProviderSelection>,
    /// Maximum concurrently running provider Requests.
    pub max_in_flight: NonZeroUsize,
    /// Maximum concurrently running browser provider Requests.
    pub max_browser_in_flight: NonZeroUsize,
    /// Maximum retained hits from each provider.
    pub max_results_per_provider: NonZeroU16,
    /// Maximum retained hits across every provider.
    pub max_total_results: NonZeroU32,
    /// Maximum retained URL and provider text bytes across Search results.
    pub max_retained_content_bytes: AddressableByteLimit,
    /// Absolute elapsed-time bound shared by the Search operation.
    pub maximum_elapsed: MaximumElapsed,
}

impl Search {
    /// A bounded Search policy with no provider Requests.
    pub fn disabled() -> Self {
        Self {
            providers: Vec::new(),
            max_in_flight: NonZeroUsize::new(2).unwrap_or(NonZeroUsize::MIN),
            max_browser_in_flight: NonZeroUsize::MIN,
            max_results_per_provider: NonZeroU16::new(10).unwrap_or(NonZeroU16::MIN),
            max_total_results: NonZeroU32::new(30).unwrap_or(NonZeroU32::MIN),
            max_retained_content_bytes: AddressableByteLimit::default_locator_output(),
            maximum_elapsed: MaximumElapsed::default_search(),
        }
    }

    /// Creates an ordered Search policy from distinct providers using Current.
    pub fn new(providers: impl IntoIterator<Item = Provider>) -> Result<Self, PolicyError> {
        let mut search = Self {
            providers: providers
                .into_iter()
                .map(ProviderSelection::current)
                .collect(),
            ..Self::default()
        };
        let planned_results =
            required_total_results(search.providers.len(), search.max_results_per_provider)?;
        if planned_results > search.max_total_results.get() {
            search.max_total_results = NonZeroU32::new(planned_results).unwrap_or(NonZeroU32::MIN);
        }
        search.validate()?;
        Ok(search)
    }

    /// Returns the ordered provider selections.
    pub fn providers(&self) -> &[ProviderSelection] {
        &self.providers
    }

    /// Returns the provider concurrency limit.
    pub const fn max_in_flight(&self) -> NonZeroUsize {
        self.max_in_flight
    }

    /// Returns the browser provider concurrency limit.
    pub const fn max_browser_in_flight(&self) -> NonZeroUsize {
        self.max_browser_in_flight
    }

    /// Returns the per-provider hit limit.
    pub const fn max_results_per_provider(&self) -> NonZeroU16 {
        self.max_results_per_provider
    }

    /// Returns the total hit limit.
    pub const fn max_total_results(&self) -> NonZeroU32 {
        self.max_total_results
    }

    /// Returns the retained-output byte limit.
    pub const fn max_retained_content_bytes(&self) -> AddressableByteLimit {
        self.max_retained_content_bytes
    }

    /// Returns the whole-Search elapsed-time limit.
    pub const fn maximum_elapsed(&self) -> MaximumElapsed {
        self.maximum_elapsed
    }

    /// Replaces the provider concurrency bound and validates the plan.
    pub fn with_max_in_flight(mut self, value: NonZeroUsize) -> Result<Self, PolicyError> {
        self.max_in_flight = value;
        self.validate()?;
        Ok(self)
    }

    /// Replaces the browser provider concurrency bound and validates the plan.
    pub fn with_max_browser_in_flight(mut self, value: NonZeroUsize) -> Result<Self, PolicyError> {
        self.max_browser_in_flight = value;
        self.validate()?;
        Ok(self)
    }

    /// Sets the per-provider hit bound and validates the total-hit plan.
    pub fn per_provider_limit(mut self, value: u16) -> Result<Self, PolicyError> {
        self.max_results_per_provider =
            NonZeroU16::new(value).ok_or(PolicyError::ZeroSearchPerProviderLimit)?;
        self.validate()?;
        Ok(self)
    }

    /// Replaces both hit bounds together and validates the complete plan.
    pub fn with_result_limits(
        mut self,
        per_provider: NonZeroU16,
        total: NonZeroU32,
    ) -> Result<Self, PolicyError> {
        self.max_results_per_provider = per_provider;
        self.max_total_results = total;
        self.validate()?;
        Ok(self)
    }

    /// Replaces the total-hit bound and validates the complete provider plan.
    pub fn with_max_total_results(mut self, value: NonZeroU32) -> Result<Self, PolicyError> {
        self.max_total_results = value;
        self.validate()?;
        Ok(self)
    }

    /// Replaces the retained-output bound and validates addressability.
    pub fn with_max_retained_content_bytes(
        mut self,
        value: AddressableByteLimit,
    ) -> Result<Self, PolicyError> {
        self.max_retained_content_bytes = value;
        self.validate()?;
        Ok(self)
    }

    /// Replaces the whole-Search deadline and validates it.
    pub fn with_maximum_elapsed(mut self, value: MaximumElapsed) -> Result<Self, PolicyError> {
        self.maximum_elapsed = value;
        self.validate()?;
        Ok(self)
    }

    /// Returns whether any provider is selected.
    pub const fn is_enabled(&self) -> bool {
        !self.providers.is_empty()
    }

    pub(crate) fn validate(&self) -> Result<(), PolicyError> {
        let mut seen = Vec::with_capacity(self.providers.len());
        for selection in &self.providers {
            if seen.contains(&selection.provider) {
                return Err(PolicyError::DuplicateSearchProvider(selection.provider));
            }
            seen.push(selection.provider);
            if let ProfileSelection::Exact(profile) = &selection.profile {
                profile.validate()?;
            }
        }

        self.max_retained_content_bytes.as_usize()?;
        self.maximum_elapsed
            .to_capture_deadline()
            .map_err(|_| PolicyError::ZeroMaximumElapsed)?;

        let required_results =
            required_total_results(self.providers.len(), self.max_results_per_provider)?;
        if required_results > self.max_total_results.get() {
            return Err(PolicyError::SearchPlanExceedsTotalResults {
                required: required_results,
                limit: self.max_total_results.get(),
            });
        }
        Ok(())
    }

    pub(crate) fn effective(&self) -> EffectiveSearch {
        let providers = self
            .providers
            .iter()
            .map(|selection| {
                let (profile, defaults_status) = match &selection.profile {
                    ProfileSelection::Current => (
                        Some(selection.provider.current_profile()),
                        selection.provider.defaults_status(),
                    ),
                    ProfileSelection::Exact(profile) => {
                        (Some(profile.clone()), ProviderDefaultsStatus::Exact)
                    }
                };
                EffectiveProviderRoute {
                    provider: selection.provider,
                    profile,
                    profile_selection_kind: selection.profile.kind(),
                    defaults_status,
                }
            })
            .collect();
        EffectiveSearch {
            providers,
            max_in_flight: self.max_in_flight,
            max_browser_in_flight: self.max_browser_in_flight,
            max_results_per_provider: self.max_results_per_provider,
            max_total_results: self.max_total_results,
            max_retained_content_bytes: self.max_retained_content_bytes,
            maximum_elapsed: self.maximum_elapsed,
        }
    }
}

impl Default for Search {
    fn default() -> Self {
        let mut search = Self::disabled();
        search.providers = vec![
            ProviderSelection::current(Provider::Brave),
            ProviderSelection::current(Provider::Bing),
            ProviderSelection::current(Provider::DuckDuckGo),
        ];
        search.max_results_per_provider = NonZeroU16::new(5).unwrap_or(NonZeroU16::MIN);
        search.max_total_results = NonZeroU32::new(15).unwrap_or(NonZeroU32::MIN);
        search
    }
}

/// Resolved Search policy with stable ordered provider slots and hard bounds.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectiveSearch {
    /// Resolved routes in policy order; unavailable Current routes remain present.
    pub providers: Vec<EffectiveProviderRoute>,
    /// Maximum concurrently running provider Requests.
    pub max_in_flight: NonZeroUsize,
    /// Maximum concurrently running browser provider Requests.
    pub max_browser_in_flight: NonZeroUsize,
    /// Maximum retained hits from each provider.
    pub max_results_per_provider: NonZeroU16,
    /// Maximum retained hits across every provider.
    pub max_total_results: NonZeroU32,
    /// Maximum retained URL and provider text bytes across Search results.
    pub max_retained_content_bytes: AddressableByteLimit,
    /// Absolute elapsed-time bound shared by the Search operation.
    pub maximum_elapsed: MaximumElapsed,
}

impl EffectiveSearch {
    /// Returns effective routes in authored provider order.
    pub fn providers(&self) -> &[EffectiveProviderRoute] {
        &self.providers
    }

    /// Returns the provider concurrency limit.
    pub const fn max_in_flight(&self) -> NonZeroUsize {
        self.max_in_flight
    }

    /// Returns the browser provider concurrency limit.
    pub const fn max_browser_in_flight(&self) -> NonZeroUsize {
        self.max_browser_in_flight
    }

    /// Returns the per-provider hit limit.
    pub const fn max_results_per_provider(&self) -> NonZeroU16 {
        self.max_results_per_provider
    }

    /// Returns the total hit limit.
    pub const fn max_total_results(&self) -> NonZeroU32 {
        self.max_total_results
    }

    /// Returns the retained-output byte limit.
    pub const fn max_retained_content_bytes(&self) -> AddressableByteLimit {
        self.max_retained_content_bytes
    }

    /// Returns the whole-Search elapsed-time limit.
    pub const fn maximum_elapsed(&self) -> MaximumElapsed {
        self.maximum_elapsed
    }

    pub(crate) fn validate(&self) -> Result<(), PolicyError> {
        let mut seen = Vec::with_capacity(self.providers.len());
        for route in &self.providers {
            if seen.contains(&route.provider) {
                return Err(PolicyError::DuplicateSearchProvider(route.provider));
            }
            seen.push(route.provider);
            match (
                route.profile_selection_kind,
                route.defaults_status,
                &route.profile,
            ) {
                (
                    ProfileSelectionKind::Current,
                    ProviderDefaultsStatus::Unavailable { registry_version },
                    None,
                ) if registry_version > 0 => {}
                (
                    ProfileSelectionKind::Current,
                    ProviderDefaultsStatus::Certified { version },
                    Some(profile),
                ) if version.get() > 0 => profile.validate()?,
                (
                    ProfileSelectionKind::Current,
                    ProviderDefaultsStatus::Preview { version },
                    Some(profile),
                ) if version.get() > 0 => profile.validate()?,
                (ProfileSelectionKind::Exact, ProviderDefaultsStatus::Exact, Some(profile)) => {
                    profile.validate()?;
                }
                _ => return Err(PolicyError::InvalidEffectiveSearchRoute),
            }
        }
        self.max_retained_content_bytes.as_usize()?;
        self.maximum_elapsed
            .to_capture_deadline()
            .map_err(|_| PolicyError::ZeroMaximumElapsed)?;
        let required_results =
            required_total_results(self.providers.len(), self.max_results_per_provider)?;
        if required_results > self.max_total_results.get() {
            return Err(PolicyError::SearchPlanExceedsTotalResults {
                required: required_results,
                limit: self.max_total_results.get(),
            });
        }
        Ok(())
    }
}

/// One provider route resolved from Current or an exact Requests profile.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct EffectiveProviderRoute {
    /// Selected provider.
    pub provider: Provider,
    /// Exact profile when available; unavailable Current routes retain `None`.
    pub profile: Option<ProviderRequestProfile>,
    /// Authored resolution mode.
    pub profile_selection_kind: ProfileSelectionKind,
    /// Registry state captured into effective identity.
    pub defaults_status: ProviderDefaultsStatus,
}

impl EffectiveProviderRoute {
    /// Returns the selected provider.
    pub const fn provider(&self) -> Provider {
        self.provider
    }

    /// Returns the resolved preview, certified, or explicitly authored profile.
    pub const fn profile(&self) -> Option<&ProviderRequestProfile> {
        self.profile.as_ref()
    }

    /// Returns the authored Current or Exact selection kind.
    pub const fn profile_selection_kind(&self) -> ProfileSelectionKind {
        self.profile_selection_kind
    }

    /// Returns the registry state captured for this route.
    pub const fn defaults_status(&self) -> ProviderDefaultsStatus {
        self.defaults_status
    }

    /// Returns the version of a resolved Current route.
    pub const fn defaults_version(&self) -> Option<ProviderDefaultsVersion> {
        match self.defaults_status {
            ProviderDefaultsStatus::Preview { version }
            | ProviderDefaultsStatus::Certified { version } => Some(version),
            ProviderDefaultsStatus::Unavailable { .. } | ProviderDefaultsStatus::Exact => None,
        }
    }

    /// Returns the resolved page policy when one is available.
    pub fn page(&self) -> Option<&Page> {
        self.profile.as_ref().map(ProviderRequestProfile::page)
    }

    /// Returns the resolved Requests policy when one is available.
    pub fn request(&self) -> Option<&Request> {
        self.profile.as_ref().map(ProviderRequestProfile::request)
    }

    /// Returns the resolved document policy when one is available.
    pub fn documents(&self) -> Option<&Documents> {
        self.profile.as_ref().map(ProviderRequestProfile::documents)
    }
}

fn required_total_results(
    provider_count: usize,
    results_per_provider: NonZeroU16,
) -> Result<u32, PolicyError> {
    let required = provider_count
        .checked_mul(usize::from(results_per_provider.get()))
        .ok_or(PolicyError::SearchPlanArithmeticOverflow)?;
    u32::try_from(required).map_err(|_| PolicyError::SearchPlanArithmeticOverflow)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn total_hit_budget_uses_checked_multiplication_and_conversion() {
        assert_eq!(
            required_total_results(usize::MAX, NonZeroU16::MAX),
            Err(PolicyError::SearchPlanArithmeticOverflow)
        );
        assert_eq!(
            required_total_results(4, NonZeroU16::new(10).unwrap_or(NonZeroU16::MIN)),
            Ok(40)
        );
    }
}
