use std::num::{NonZeroU16, NonZeroU32, NonZeroUsize};

use serde::{Deserialize, Serialize};

use crate::{
    PolicyError,
    policy::{AddressableByteLimit, MaximumElapsed},
};

use super::provider::{ProfileSelection, Provider, ProviderDefaultsStatus, ProviderSelection};
use super::{EffectiveProviderRoute, EffectiveSearch};

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

pub(super) fn required_total_results(
    provider_count: usize,
    results_per_provider: NonZeroU16,
) -> Result<u32, PolicyError> {
    let required = provider_count
        .checked_mul(usize::from(results_per_provider.get()))
        .ok_or(PolicyError::SearchPlanArithmeticOverflow)?;
    u32::try_from(required).map_err(|_| PolicyError::SearchPlanArithmeticOverflow)
}
