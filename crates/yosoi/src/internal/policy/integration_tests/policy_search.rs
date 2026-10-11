#![allow(clippy::panic_in_result_fn)]

use std::error::Error;

use crate::internal::policy::policy::{
    AcquisitionKind, BrowserMode, DocumentRequest, Documents, Page, ProfileSelectionKind, Provider,
    ProviderDefaultsStatus, ProviderDefaultsVersion, ProviderRequestProfile, ProviderSelection,
    Request, Search,
};
use crate::internal::policy::{Policy, PolicyError, PolicySnapshot};
use std::num::{NonZeroU16, NonZeroU32};

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn current_routes_keep_order_and_expose_versioned_preview_profiles() -> TestResult {
    let search = Search::new([Provider::Brave, Provider::Bing, Provider::DuckDuckGo])?;
    let policy = Policy {
        search,
        ..Policy::default()
    };
    let snapshot = PolicySnapshot::from_policy(&policy)?;
    let routes = snapshot.effective_policy().search.providers();

    assert_eq!(routes.len(), 3);
    for (route, provider) in
        routes
            .iter()
            .zip([Provider::Brave, Provider::Bing, Provider::DuckDuckGo])
    {
        assert_eq!(route.provider(), provider);
        assert_eq!(
            route.profile_selection_kind(),
            ProfileSelectionKind::Current
        );
        let profile = route.profile().ok_or("Current route profile is missing")?;
        let expected_version = if provider == Provider::DuckDuckGo {
            1
        } else {
            2
        };
        assert_eq!(
            route.defaults_version(),
            Some(ProviderDefaultsVersion::try_new(expected_version)?)
        );
        assert_eq!(
            route.defaults_status(),
            ProviderDefaultsStatus::Preview {
                version: ProviderDefaultsVersion::try_new(expected_version)?
            }
        );
        match provider {
            Provider::Bing => {
                assert_eq!(profile.page, Page::default());
            }
            Provider::Brave | Provider::DuckDuckGo => {
                let acquisition = profile
                    .page
                    .acquisitions
                    .first()
                    .ok_or("DDG route missing")?;
                assert_eq!(
                    acquisition.kind(),
                    AcquisitionKind::Browser {
                        mode: BrowserMode::Headless
                    }
                );
                assert_eq!(
                    acquisition.exact_documents(),
                    Some(
                        &[
                            DocumentRequest::ResponseDocument,
                            DocumentRequest::RenderedDom
                        ][..]
                    )
                );
                assert_eq!(
                    profile.request.maximum_elapsed.as_microseconds(),
                    20_000_000
                );
            }
        }
    }

    let reversed = Policy {
        search: Search::new([Provider::DuckDuckGo, Provider::Bing, Provider::Brave])?,
        ..Policy::default()
    };
    assert_ne!(policy.effective_identity()?, reversed.effective_identity()?);
    Ok(())
}

#[test]
fn exact_general_requests_profile_resolves_in_the_effective_route() -> TestResult {
    let profile =
        ProviderRequestProfile::new(Page::default(), Request::default(), Documents::default())?;
    let search = Search {
        providers: vec![ProviderSelection::exact(Provider::Brave, profile.clone())],
        ..Search::default()
    };
    let policy = Policy {
        search,
        ..Policy::default()
    };
    let canonical = policy.to_canonical_json()?;
    let reopened: Policy = serde_json::from_str(&canonical)?;
    assert_eq!(reopened, policy);
    assert_eq!(reopened.effective_identity()?, policy.effective_identity()?);

    let snapshot = PolicySnapshot::from_policy(&policy)?;
    let route = snapshot
        .effective_policy()
        .search
        .providers()
        .first()
        .ok_or("exact route is missing")?;

    assert_eq!(route.profile_selection_kind(), ProfileSelectionKind::Exact);
    assert_eq!(route.defaults_status(), ProviderDefaultsStatus::Exact);
    assert_eq!(route.profile(), Some(&profile));
    assert_eq!(route.page(), Some(profile.page()));
    assert_eq!(route.request(), Some(profile.request()));
    assert_eq!(route.documents(), Some(profile.documents()));
    assert_eq!(route.defaults_version(), None);
    Ok(())
}

#[test]
fn provider_order_is_distinct_and_total_hit_bounds_cover_the_plan() -> TestResult {
    assert!(matches!(
        Search::new([Provider::Brave, Provider::Brave]),
        Err(PolicyError::DuplicateSearchProvider(Provider::Brave))
    ));

    let search = Search::new([Provider::Brave, Provider::Bing])?;
    assert!(matches!(
        search.clone().with_max_total_results(NonZeroU32::MIN),
        Err(PolicyError::SearchPlanExceedsTotalResults {
            required: 10,
            limit: 1
        })
    ));
    let larger_limits = search.with_result_limits(
        NonZeroU16::new(20).ok_or("positive test bound is missing")?,
        NonZeroU32::new(40).ok_or("positive test bound is missing")?,
    )?;
    assert_eq!(larger_limits.max_results_per_provider().get(), 20);
    assert_eq!(larger_limits.max_total_results().get(), 40);

    assert_eq!(
        Search::new([Provider::Brave])?.per_provider_limit(0),
        Err(PolicyError::ZeroSearchPerProviderLimit)
    );
    assert_eq!(
        Search::new([Provider::Brave])?
            .per_provider_limit(10)?
            .max_results_per_provider()
            .get(),
        10
    );

    let default = Search::default();
    assert!(default.is_enabled());
    assert_eq!(
        default
            .providers()
            .iter()
            .map(|route| route.provider)
            .collect::<Vec<_>>(),
        vec![Provider::Brave, Provider::Bing, Provider::DuckDuckGo]
    );
    assert_eq!(default.max_results_per_provider().get(), 5);
    assert_eq!(default.max_total_results().get(), 15);

    let disabled = Search::disabled();
    assert!(!disabled.is_enabled());
    assert_eq!(disabled.max_in_flight().get(), 2);
    assert!(disabled.max_browser_in_flight().get() > 0);
    assert!(disabled.max_results_per_provider().get() > 0);
    assert!(disabled.max_total_results().get() > 0);
    assert!(disabled.max_retained_content_bytes().get() > 0);
    assert_eq!(disabled.maximum_elapsed().as_microseconds(), 30_000_000);
    Ok(())
}
