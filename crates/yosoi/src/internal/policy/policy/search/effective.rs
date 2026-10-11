use std::num::{NonZeroU16, NonZeroU32, NonZeroUsize};

use serde::{Deserialize, Serialize};

use crate::internal::policy::{
    PolicyError,
    policy::{AddressableByteLimit, Documents, MaximumElapsed, Page, Request},
};

use super::plan::required_total_results;
use super::provider::{
    ProfileSelectionKind, Provider, ProviderDefaultsStatus, ProviderDefaultsVersion,
    ProviderRequestProfile,
};

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

    pub(in crate::internal::policy) fn validate(&self) -> Result<(), PolicyError> {
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
