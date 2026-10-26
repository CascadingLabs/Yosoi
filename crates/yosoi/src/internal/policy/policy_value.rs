use super::policy::Network;
use std::time::{Duration, Instant};

use crate::internal::policy::{
    EffectivePolicy, EffectivePolicyIdentity, PolicyError,
    policy::{
        Acquisition, Documents, FlowPolicy, Locators, Map, Page, ProfileSelection,
        ProviderDefaultsStatus, Request, Search, Tuning,
    },
};

/// Complete page, request, document, and locator policy values.
///
/// The fields remain public so applications can author ordinary struct values.
/// Validation runs before serialization and identity calculation.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Policy {
    /// Opt-in outbound routing bound to requests and owned browser lifetimes.
    pub network: Network,
    /// Fallback execution budget for an action without a nearer Flow or action
    /// timeout, measured in milliseconds.
    pub default_action_timeout_ms: u64,
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
    /// Default continuation behavior for Flow failures and local cancellations.
    pub flow: FlowPolicy,
}

impl Default for Policy {
    fn default() -> Self {
        Self {
            network: Network::default(),
            default_action_timeout_ms: 10_000,
            page: Page::default(),
            request: Request::default(),
            documents: Documents::default(),
            locators: Locators::default(),
            tuning: Tuning::default(),
            map: Map::default(),
            search: Search::default(),
            flow: FlowPolicy::default(),
        }
    }
}

impl Policy {
    /// Validates nested page choices and all typed policy bounds.
    pub fn validate(&self) -> Result<(), PolicyError> {
        self.network.validate()?;
        self.page.validate()?;
        self.request.validate()?;
        if self.default_action_timeout_ms == 0
            || Instant::now()
                .checked_add(Duration::from_millis(self.default_action_timeout_ms))
                .is_none()
        {
            return Err(PolicyError::InvalidDefaultActionTimeout);
        }
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
            network: self.network.clone(),
            page: self.page.effective(),
            request: self.request,
            default_action_timeout_ms: self.default_action_timeout_ms,
            documents: self.documents,
            locators: self.locators,
            tuning: self.tuning,
            map: self.map.clone(),
            search: self.search.effective(),
            flow: self.flow,
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
        if effective.network != self.network
            || effective.request != self.request
            || effective.default_action_timeout_ms != self.default_action_timeout_ms
            || effective.documents != self.documents
            || effective.locators != self.locators
            || effective.tuning != self.tuning
            || effective.map != self.map
            || effective.flow != self.flow
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
}
