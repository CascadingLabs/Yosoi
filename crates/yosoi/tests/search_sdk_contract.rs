#![allow(clippy::panic_in_result_fn)]

use std::{error::Error, ptr};

use yosoi::prelude as ys;

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn search_query_is_bounded_and_redacted() -> TestResult {
    assert!(matches!(
        ys::search::new(" \t "),
        Err(ys::search::SearchQueryError::Empty)
    ));
    assert!(ys::search::new("x".repeat(512)).is_ok());
    assert!(matches!(
        ys::search::new("x".repeat(513)),
        Err(ys::search::SearchQueryError::TooLong {
            maximum: 512,
            observed: 513
        })
    ));

    let query = ys::search::new("private query phrase")?;
    let debug = format!("{query:?}");
    assert!(!debug.contains("private query phrase"));
    let id = query.id();
    let policy = ys::Policy::default();
    let bound = query.bind(&policy);
    assert_eq!(bound.request().id(), id);
    assert!(ptr::eq(bound.policy(), ptr::from_ref(&policy)));
    assert!(!format!("{bound:?}").contains("private query phrase"));
    Ok(())
}

#[test]
fn search_result_url_requires_safe_web_destination() -> TestResult {
    for invalid in [
        "/relative",
        "javascript:alert(1)",
        "data:text/plain,hello",
        "https://user:password@example.org/private",
    ] {
        assert!(ys::search::SearchResultUrl::parse(invalid).is_err());
    }
    let url = ys::search::SearchResultUrl::parse("https://example.org/path?q=1")?;
    assert_eq!(url.as_str(), "https://example.org/path?q=1");
    assert!(!format!("{url:?}").contains("example.org"));
    Ok(())
}

#[test]
fn default_binding_selects_three_versioned_preview_routes_at_five_each() -> TestResult {
    let policy = ys::Policy::default();
    let prepared = ys::search::new("rust ownership")?.bind(&policy).prepare()?;
    let search = &prepared.policy_snapshot().effective_policy().search;
    assert_eq!(search.providers().len(), 3);
    assert_eq!(search.max_results_per_provider().get(), 5);
    assert_eq!(search.max_total_results().get(), 15);
    assert!(
        search
            .providers()
            .iter()
            .all(|route| route.profile().is_some())
    );
    Ok(())
}

#[test]
fn binding_snapshots_ordered_provider_policy_without_a_certified_default() -> TestResult {
    let request = ys::search::new("rust ownership")?;
    let empty_policy = ys::Policy {
        search: ys::policy::search::Search::disabled(),
        ..ys::Policy::default()
    };
    assert!(matches!(
        request.clone().bind(&empty_policy).prepare(),
        Err(ys::search::SearchSendError::NoProviderConfigured)
    ));

    let policy = ys::Policy {
        search: ys::policy::search::Search::new([
            ys::policy::search::Provider::Brave,
            ys::policy::search::Provider::Bing,
        ])?,
        ..ys::Policy::default()
    };
    let prepared = request.bind(&policy).prepare()?;
    assert_eq!(prepared.providers().len(), 2);
    assert_eq!(
        prepared
            .providers()
            .first()
            .map(ys::policy::EffectiveProviderRoute::provider),
        Some(ys::policy::search::Provider::Brave)
    );
    assert_eq!(
        prepared
            .providers()
            .get(1)
            .map(ys::policy::EffectiveProviderRoute::provider),
        Some(ys::policy::search::Provider::Bing)
    );
    assert!(
        prepared
            .providers()
            .iter()
            .all(|route| route.profile().is_some())
    );
    assert!(!format!("{prepared:?}").contains("rust ownership"));
    Ok(())
}
