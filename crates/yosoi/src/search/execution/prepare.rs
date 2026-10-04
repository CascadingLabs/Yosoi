use thiserror::Error;
use yosoi_policy::{
    Policy, PolicySnapshot,
    policy::{
        Acquisition, AcquisitionKind, AddressableByteLimit, BrowserMode, DocumentRequest,
        search::{EffectiveProviderRoute, ProfileSelectionKind, Provider},
    },
};
use yosoi_web_capture::RequestedWebTarget;

use crate::request::new as new_request;
use crate::{PageRequest, search::ProviderResult};

use super::super::target::{ProviderTargetError, provider_target};
use super::super::{PreparedSearch, SearchProfileFacts, SearchUnavailableReason};

/// A structural Search setup failure detected before provider Requests start.
#[derive(Clone, Copy, Debug, Error, Eq, PartialEq)]
pub enum SearchExecutionSetupError {
    #[error("Search output budget cannot provide a nonzero quota to every selected provider")]
    OutputBudgetTooSmall,
    #[error("Search deadline cannot be represented by the runtime clock")]
    DeadlineUnrepresentable,
    #[error("Search provider target could not be prepared")]
    ProviderTarget,
    #[error("Search child Request policy could not be prepared")]
    ChildRequestPolicy,
}

pub(super) struct ProviderJob {
    pub(super) route: EffectiveProviderRoute,
    pub(super) provider: Provider,
    pub(super) request: PageRequest,
    pub(super) policy: Policy,
    pub(super) provider_target: RequestedWebTarget,
    pub(super) query: String,
    pub(super) result_limit: usize,
    pub(super) output_limit: usize,
    pub(super) profile: SearchProfileFacts,
}

pub(super) fn per_provider_output_quota(
    total_limit: usize,
    provider_count: usize,
) -> Result<usize, SearchExecutionSetupError> {
    let quota = total_limit
        .checked_div(provider_count)
        .filter(|quota| *quota > 0)
        .ok_or(SearchExecutionSetupError::OutputBudgetTooSmall)?;
    Ok(quota)
}

pub(super) fn prepare_provider_job(
    prepared: &PreparedSearch,
    route: &EffectiveProviderRoute,
    output_limit: AddressableByteLimit,
    output_limit_usize: usize,
    result_limit: usize,
) -> Result<(Option<ProviderResult>, Option<ProviderJob>), SearchExecutionSetupError> {
    if route.profile_selection_kind() == ProfileSelectionKind::Current && route.profile().is_none()
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::DefaultUncertified,
            )),
            None,
        ));
    }

    let Some(page) = route.page() else {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::DefaultUncertified,
            )),
            None,
        ));
    };
    if page.acquisitions.is_empty() {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }
    #[cfg(not(feature = "browser"))]
    if page
        .acquisitions
        .iter()
        .any(|acquisition| matches!(acquisition.kind(), AcquisitionKind::Browser { .. }))
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }
    if page.acquisitions.len() != 1 {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }
    let Some(acquisition) = page.acquisitions.first() else {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    };
    if acquisition
        .exact_documents()
        .is_some_and(|documents| !documents.contains(&DocumentRequest::ResponseDocument))
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }

    if route.provider() == Provider::DuckDuckGo && !is_supported_duckduckgo_acquisition(acquisition)
    {
        return Ok((
            Some(ProviderResult::not_started(
                route,
                SearchUnavailableReason::UnsupportedCapability,
            )),
            None,
        ));
    }

    let policy = prepared
        .request_policy_for(route, output_limit)
        .ok_or(SearchExecutionSetupError::ChildRequestPolicy)?;
    let child_snapshot = PolicySnapshot::from_policy(&policy)
        .map_err(|_| SearchExecutionSetupError::ChildRequestPolicy)?;
    let target =
        provider_target(route.provider(), prepared.query()).map_err(map_provider_target_error)?;
    let request = new_request(target.as_str());
    request
        .clone()
        .bind(&policy)
        .prepare()
        .map_err(|_| SearchExecutionSetupError::ChildRequestPolicy)?;

    let acquisition = page.acquisitions.first().map(Acquisition::kind);
    let profile = SearchProfileFacts {
        acquisition,
        defaults_status: route.defaults_status(),
        defaults_version: route.defaults_version(),
        effective_request_policy: Some(child_snapshot.identity()),
    };
    Ok((
        None,
        Some(ProviderJob {
            route: route.clone(),
            provider: route.provider(),
            request,
            policy,
            provider_target: target,
            query: prepared.query().to_owned(),
            result_limit,
            output_limit: output_limit_usize,
            profile,
        }),
    ))
}

const fn map_provider_target_error(_: ProviderTargetError) -> SearchExecutionSetupError {
    SearchExecutionSetupError::ProviderTarget
}

pub(super) fn job_uses_browser(job: &ProviderJob) -> bool {
    job.policy
        .page
        .acquisitions
        .iter()
        .any(|acquisition| matches!(acquisition.kind(), AcquisitionKind::Browser { .. }))
}

pub(super) fn is_supported_duckduckgo_acquisition(acquisition: &Acquisition) -> bool {
    matches!(
        acquisition.kind(),
        AcquisitionKind::Browser {
            mode: BrowserMode::Headless
        }
    ) && acquisition.exact_documents().is_some_and(|documents| {
        documents
            == [
                DocumentRequest::ResponseDocument,
                DocumentRequest::RenderedDom,
            ]
    })
}
