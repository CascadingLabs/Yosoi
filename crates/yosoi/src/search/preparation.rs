use std::{cmp::min, fmt};

use thiserror::Error;
use yosoi_policy::{
    Policy, PolicyError, PolicySnapshot,
    policy::{
        AddressableByteLimit,
        search::{EffectiveProviderRoute, Search},
    },
};

use super::{BoundSearchRequest, SearchExecutionSetupError, SearchRequestId};

/// A structural or setup failure before any provider Requests begin.
#[derive(Debug, Error)]
pub enum SearchSendError {
    #[error("Search policy has no selected providers")]
    NoProviderConfigured,
    #[error("Search policy is invalid")]
    Policy(#[source] PolicyError),
    #[error(transparent)]
    Execution(#[from] SearchExecutionSetupError),
}

/// Immutable query intent and one fully resolved Policy snapshot.
pub struct PreparedSearch {
    request_id: SearchRequestId,
    query: String,
    policy_snapshot: PolicySnapshot,
}

impl PreparedSearch {
    pub const fn request_id(&self) -> SearchRequestId {
        self.request_id
    }

    pub fn query(&self) -> &str {
        &self.query
    }

    pub const fn policy_snapshot(&self) -> &PolicySnapshot {
        &self.policy_snapshot
    }

    /// Resolved provider routes in the order authored by Search policy.
    pub fn providers(&self) -> &[EffectiveProviderRoute] {
        self.policy_snapshot.effective_policy().search.providers()
    }

    /// Derives the complete Policy for one child Request. The Search section
    /// is disabled in the child; the parent snapshot retains the overall plan.
    pub(crate) fn request_policy_for(
        &self,
        route: &EffectiveProviderRoute,
        output_limit: AddressableByteLimit,
    ) -> Option<Policy> {
        let profile = route.profile()?;
        let mut policy = self.policy_snapshot.policy().clone();
        policy.page = profile.page().clone();
        policy.request = *profile.request();
        policy.documents = *profile.documents();
        policy.locators.max_output_bytes = min(policy.locators.max_output_bytes, output_limit);
        policy.search = Search::disabled();
        Some(policy)
    }
}

impl fmt::Debug for PreparedSearch {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("PreparedSearch")
            .field("request_id", &self.request_id)
            .field("query", &"<redacted>")
            .field("policy_identity", &self.policy_snapshot.identity())
            .field("provider_count", &self.providers().len())
            .finish()
    }
}

impl BoundSearchRequest<'_> {
    /// Validates the complete Policy and resolves provider defaults once.
    /// Provider-specific unavailable capabilities remain visible routes;
    /// execution gives them a NotStarted outcome rather than erasing them.
    pub fn prepare(&self) -> Result<PreparedSearch, SearchSendError> {
        let policy_snapshot =
            PolicySnapshot::from_policy(self.policy()).map_err(SearchSendError::Policy)?;
        if policy_snapshot
            .effective_policy()
            .search
            .providers()
            .is_empty()
        {
            return Err(SearchSendError::NoProviderConfigured);
        }
        Ok(PreparedSearch {
            request_id: self.request().id(),
            query: self.request().query().to_owned(),
            policy_snapshot,
        })
    }
}

#[cfg(test)]
#[expect(
    clippy::panic_in_result_fn,
    reason = "assertions report child-policy preparation regressions after fallible setup"
)]
mod tests {
    use std::error::Error;

    use yosoi_policy::{
        Documents, Policy,
        policy::{
            AddressableByteLimit, Page, Request,
            search::{Provider, ProviderRequestProfile, ProviderSelection, Search},
        },
    };

    use super::super::new;

    #[test]
    fn child_request_uses_one_profile_and_capped_locator_output() -> Result<(), Box<dyn Error>> {
        let profile =
            ProviderRequestProfile::new(Page::default(), Request::default(), Documents::default())?;
        let search = Search {
            providers: vec![ProviderSelection::exact(Provider::Brave, profile)],
            max_retained_content_bytes: AddressableByteLimit::try_from(64_u64)?,
            ..Search::default()
        };
        let policy = Policy {
            search,
            ..Policy::default()
        };

        let query = new("rust")?;
        let prepared = query.bind(&policy).prepare()?;
        let route = prepared
            .providers()
            .first()
            .ok_or("missing prepared Brave route")?;
        let child = prepared
            .request_policy_for(route, AddressableByteLimit::try_from(64_u64)?)
            .ok_or("missing exact child Request policy")?;
        assert_eq!(child.locators.max_output_bytes.get(), 64);
        assert_eq!(child.search.providers().len(), 0);
        assert_eq!(child.page, Page::default());
        Ok(())
    }
}
