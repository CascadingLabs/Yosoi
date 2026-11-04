#![expect(
    clippy::panic_in_result_fn,
    reason = "Assertions describe public Auto behavior."
)]
use std::error::Error;
use yosoi::{
    Policy,
    policy::{
        PolicyError,
        respectfulness::{Group, Respectfulness},
        search::{Provider, Routing, Search},
    },
    registry::Registry,
    search::{self, ProviderOutcome, SearchUnavailableReason},
};

type TestResult = Result<(), Box<dyn Error>>;

#[test]
fn defaults_are_auto_and_historical_explicit_plans_keep_their_identity() -> TestResult {
    let current = Policy::default();
    assert_eq!(current.search.routing, Routing::Auto);
    assert_eq!(
        current
            .search
            .providers
            .iter()
            .map(|selection| selection.provider)
            .collect::<Vec<_>>(),
        vec![
            Provider::Google,
            Provider::DuckDuckGo,
            Provider::Bing,
            Provider::Brave
        ]
    );
    assert_eq!(current.effective_identity()?.version(), 10);
    assert!(
        current
            .to_canonical_json()?
            .contains("\"routing\":\"auto\"")
    );
    let historical: Policy = serde_json::from_str(include_str!(
        "../src/internal/policy/integration_tests/fixtures/policy-v7-explicit-search.json"
    ))?;
    assert_eq!(historical.search.routing, Routing::All);
    assert_eq!(historical.effective_identity()?.version(), 7);
    assert_eq!(
        historical.effective_identity()?.digest().to_string(),
        "65f808531d392ce5ea96509219dfd62a3e0440c0c2c0a8e657bc420a89a6d7d2"
    );
    Ok(())
}

#[test]
fn candidate_lists_are_nonempty_ordered_and_explicit_all_remains_available() -> TestResult {
    assert!(matches!(
        Search::auto([]),
        Err(PolicyError::EmptyAutoSearch)
    ));
    assert!(matches!(
        Search::auto([Provider::Bing, Provider::Bing]),
        Err(PolicyError::DuplicateSearchProvider(Provider::Bing))
    ));
    let one = Search::auto([Provider::Bing])?;
    assert_eq!(one.providers.len(), 1);
    assert_eq!(one.routing, Routing::Auto);
    assert_eq!(
        Search::new([Provider::Bing, Provider::Brave])?.routing,
        Routing::All
    );
    Ok(())
}

#[tokio::test(flavor = "current_thread")]
async fn default_auto_reports_unsupported_and_blocked_candidates_without_dispatch_or_cursor_charge()
-> TestResult {
    let directory = tempfile::tempdir()?;
    let registry = Registry::jsonl(directory.path().join("search.jsonl"))?;
    let policy = Policy {
        respectfulness: Some(Respectfulness::new(vec![Group {
            blocked: true,
            ..Group::new("all", ["^https://"])
        }])?),
        ..Policy::default()
    };
    let response = search::new("no outbound work")?
        .bind(&policy)
        .with_registry(&registry)
        .send()
        .await?;
    assert_eq!(response.routing(), Routing::Auto);
    assert!(response.selected_provider().is_none());
    assert_eq!(response.providers().len(), 4);
    for provider in response.providers() {
        assert!(provider.request_id().is_none());
        assert_eq!(provider.attempts(), []);
        let expected = if provider.provider() == Provider::Bing {
            SearchUnavailableReason::Respectfulness
        } else {
            SearchUnavailableReason::UnsupportedCapability
        };
        assert!(
            matches!(provider.outcome(), ProviderOutcome::NotStarted(reason) if *reason == expected)
        );
    }
    assert!(registry.snapshot()?.entries.is_empty());
    Ok(())
}
