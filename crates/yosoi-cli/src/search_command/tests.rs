use std::{error::Error, slice};

use super::report::{exit_code, render_human, render_json, render_stats};
use super::search_for_cli;
use super::view::names::failure_name;
use super::view::{
    ChargeView, CoverageView, FeatureView, HitView, IssueView, PolicyIdentityView,
    ProviderIdentityView, ProviderProfileView, ProviderStatus, ProviderView, RequestAttemptView,
    SearchEnvelope,
};
use super::{OutputFormat, ProviderChoice, SearchArgs};
use crate::{
    presentation::Theme,
    stats::{RunTimer, StatsArgs},
};
use std::{
    num::{NonZeroU16, NonZeroU32, NonZeroUsize},
    process::ExitCode,
};
use yosoi_engine::{
    policy::{
        self, AcquisitionKind,
        search::{Provider, Search},
    },
    search::SearchFailure,
};

fn fixture() -> SearchEnvelope<'static> {
    SearchEnvelope {
        schema_version: 2,
        cli_version: env!("CARGO_PKG_VERSION"),
        policy_profile: Some("daily"),
        policy_identity: PolicyIdentityView {
            version: 2,
            digest: "abc123".to_owned(),
        },
        termination: "completed",
        providers: vec![
            ProviderView {
                provider: "brave",
                identity: ProviderIdentityView {
                    endpoint: Some("https://search.brave.com/search"),
                    adapter_version: Some("1"),
                    parser_version: Some("1"),
                },
                status: ProviderStatus::Results,
                coverage: Some(CoverageView {
                    web: "complete",
                    rich_features: "collected",
                }),
                detail: None,
                profile: ProviderProfileView {
                    acquisition: Some(AcquisitionKind::DirectHttp),
                    defaults_status: "preview",
                    defaults_version: Some(1),
                    effective_request_policy: None,
                },
                request_id: Some("123e4567-e89b-42d3-a456-426614174100".to_owned()),
                recovery_query: None,
                attempts: vec![RequestAttemptView {
                    request_id: "123e4567-e89b-42d3-a456-426614174100".to_owned(),
                    capture_id: "123e4567-e89b-42d3-a456-426614174101".to_owned(),
                    acquisition: AcquisitionKind::DirectHttp,
                    http_status: Some(200),
                    source_bytes: Some(302_543),
                    diagnostic: None,
                    terminal: "completed",
                }],
                hits: vec![HitView {
                    organic_rank: 4,
                    placement_index: 5,
                    url: "https://example.test/result",
                    title: Some("Example"),
                    snippet: Some("A result"),
                    display_url: Some("example.test"),
                    publisher: Some("Example Press"),
                    published_at: None,
                    thumbnail_url: None,
                }],
                features: vec![FeatureView::Sponsored {
                    placement_index: 3,
                    destination: "https://example.test/sponsor",
                    label: Some("Ad"),
                }],
                applied_filters: Vec::new(),
                issues: vec![IssueView {
                    placement_index: Some(6),
                    kind: "unrecognized_result_row",
                }],
                cost: ChargeView {
                    status: "unknown",
                    currency: None,
                    amount: None,
                },
            },
            ProviderView {
                provider: "bing",
                identity: ProviderIdentityView {
                    endpoint: None,
                    adapter_version: None,
                    parser_version: None,
                },
                status: ProviderStatus::NotStarted,
                coverage: None,
                detail: Some("default_uncertified"),
                profile: ProviderProfileView {
                    acquisition: None,
                    defaults_status: "unavailable",
                    defaults_version: None,
                    effective_request_policy: None,
                },
                request_id: None,
                recovery_query: None,
                attempts: Vec::new(),
                hits: Vec::new(),
                features: Vec::new(),
                applied_filters: Vec::new(),
                issues: Vec::new(),
                cost: ChargeView {
                    status: "unknown",
                    currency: None,
                    amount: None,
                },
            },
        ],
    }
}

fn cli_args(
    providers: Vec<ProviderChoice>,
    per_provider_limit: Option<NonZeroU16>,
    max_in_flight: Option<NonZeroUsize>,
) -> SearchArgs {
    SearchArgs {
        query: "unused fixture query".to_owned(),
        providers,
        reporting: StatsArgs { enabled: false },
        per_provider_limit,
        max_in_flight,
        output: OutputFormat::Human,
    }
}

#[test]
fn default_search_runs_three_preview_routes_at_five_each() -> Result<(), Box<dyn Error>> {
    let args = cli_args(Vec::new(), None, None);
    let resolved = search_for_cli(&Search::default(), &args)?;
    assert_eq!(resolved.providers().len(), 3);
    assert_eq!(resolved.max_results_per_provider().get(), 5);
    assert_eq!(resolved.max_total_results().get(), 15);
    Ok(())
}

#[test]
fn query_mismatch_is_a_distinct_provider_failure() {
    assert_eq!(failure_name(SearchFailure::QueryMismatch), "query_mismatch");
}

#[test]
fn stats_formatter_reports_wall_time_and_bounded_totals() -> Result<(), Box<dyn Error>> {
    let mut output = Vec::new();
    render_stats(&mut output, &fixture(), &RunTimer::start(), Theme::plain())?;
    let text = String::from_utf8(output)?;
    assert!(text.contains("Search stats:\nWall time: "));
    assert!(text.contains("Termination: completed"));
    assert!(text.contains("Providers: 2"));
    assert!(text.contains("Hits: 1"));
    assert!(text.contains("Request attempts: 1"));
    assert!(text.contains("Known retained source bytes: 302543"));
    Ok(())
}

#[test]
fn omitted_search_flags_preserve_profile_providers_and_limits() -> Result<(), Box<dyn Error>> {
    let base = Search::new([Provider::Brave, Provider::Bing])?
        .with_result_limits(
            NonZeroU16::new(4).ok_or("invalid test provider limit")?,
            NonZeroU32::new(16).ok_or("invalid test total limit")?,
        )?
        .with_max_in_flight(NonZeroUsize::new(3).ok_or("invalid test concurrency")?)?
        .with_max_browser_in_flight(
            NonZeroUsize::new(2).ok_or("invalid test browser concurrency")?,
        )?;
    let args = cli_args(Vec::new(), None, None);
    let resolved = search_for_cli(&base, &args)?;
    assert_eq!(resolved.providers(), base.providers());
    assert_eq!(resolved.max_results_per_provider().get(), 4);
    assert_eq!(resolved.max_total_results().get(), 16);
    assert_eq!(resolved.max_in_flight().get(), 3);
    assert_eq!(resolved.max_browser_in_flight().get(), 2);
    Ok(())
}

#[test]
fn explicit_flags_replace_providers_and_override_profile_limits() -> Result<(), Box<dyn Error>> {
    let base = Search::new([Provider::Brave, Provider::Bing])?
        .with_result_limits(
            NonZeroU16::new(4).ok_or("invalid test provider limit")?,
            NonZeroU32::new(8).ok_or("invalid test total limit")?,
        )?
        .with_max_in_flight(NonZeroUsize::new(3).ok_or("invalid test concurrency")?)?;
    let args = cli_args(
        vec![ProviderChoice::DuckDuckGo],
        Some(NonZeroU16::new(7).ok_or("invalid override provider limit")?),
        Some(NonZeroUsize::new(1).ok_or("invalid override concurrency")?),
    );
    let resolved = search_for_cli(&base, &args)?;
    let provider = resolved.providers().first().ok_or("provider missing")?;
    assert_eq!(provider.provider, Provider::DuckDuckGo);
    assert_eq!(resolved.max_results_per_provider().get(), 7);
    assert_eq!(resolved.max_total_results().get(), 8);
    assert_eq!(resolved.max_in_flight().get(), 1);
    Ok(())
}

#[test]
fn provider_reorder_preserves_selected_exact_profile() -> Result<(), Box<dyn Error>> {
    let profile = policy::ProviderRequestProfile::new(
        policy::Page::default(),
        policy::Request::default(),
        policy::Documents::default(),
    )?;
    let mut base = Search::new([Provider::Brave, Provider::Bing])?;
    base.providers[0] = policy::ProviderSelection::exact(Provider::Brave, profile.clone());
    let args = cli_args(
        vec![ProviderChoice::Bing, ProviderChoice::Brave],
        None,
        None,
    );
    let resolved = search_for_cli(&base, &args)?;
    assert_eq!(resolved.providers()[0].provider, Provider::Bing);
    assert_eq!(resolved.providers()[1].provider, Provider::Brave);
    assert_eq!(
        resolved.providers()[1].profile,
        policy::ProfileSelection::Exact(profile)
    );
    Ok(())
}

#[test]
fn provider_override_expands_total_limit_without_changing_per_provider_limit()
-> Result<(), Box<dyn Error>> {
    let base = Search::new([Provider::Brave])?.with_result_limits(
        NonZeroU16::new(4).ok_or("invalid test provider limit")?,
        NonZeroU32::new(4).ok_or("invalid test total limit")?,
    )?;
    let args = cli_args(
        vec![
            ProviderChoice::Brave,
            ProviderChoice::Bing,
            ProviderChoice::DuckDuckGo,
        ],
        None,
        None,
    );
    let resolved = search_for_cli(&base, &args)?;
    assert_eq!(resolved.providers().len(), 3);
    assert_eq!(resolved.max_results_per_provider().get(), 4);
    assert_eq!(resolved.max_total_results().get(), 12);
    Ok(())
}

#[test]
fn empty_policy_search_requires_an_explicit_or_profile_provider() {
    let args = cli_args(Vec::new(), None, None);
    assert!(search_for_cli(&Search::disabled(), &args).is_err());
}

#[test]
fn json_formatter_keeps_provider_order_profile_facts_issues_and_unknown_cost()
-> Result<(), Box<dyn Error>> {
    let mut bytes = Vec::new();
    render_json(&mut bytes, &fixture())?;
    let value: serde_json::Value = serde_json::from_slice(&bytes)?;
    assert_eq!(
        value.get("cli_version").and_then(serde_json::Value::as_str),
        Some(env!("CARGO_PKG_VERSION"))
    );
    assert_eq!(
        value
            .get("schema_version")
            .and_then(serde_json::Value::as_u64),
        Some(2)
    );
    let providers = value
        .get("providers")
        .and_then(serde_json::Value::as_array)
        .ok_or("providers missing")?;
    let first = providers.first().ok_or("first provider missing")?;
    let second = providers.get(1).ok_or("second provider missing")?;
    assert_eq!(
        first.get("provider").and_then(serde_json::Value::as_str),
        Some("brave")
    );
    assert_eq!(
        second.get("provider").and_then(serde_json::Value::as_str),
        Some("bing")
    );
    assert_eq!(
        first.get("status").and_then(serde_json::Value::as_str),
        Some("results")
    );
    assert_eq!(
        first
            .get("coverage")
            .and_then(|coverage| coverage.get("web"))
            .and_then(serde_json::Value::as_str),
        Some("complete")
    );
    assert_eq!(
        first
            .get("profile")
            .and_then(|profile| profile.get("defaults_status"))
            .and_then(serde_json::Value::as_str),
        Some("preview")
    );
    assert_eq!(
        first
            .get("profile")
            .and_then(|profile| profile.get("defaults_version"))
            .and_then(serde_json::Value::as_u64),
        Some(1)
    );
    assert_eq!(
        first
            .get("issues")
            .and_then(serde_json::Value::as_array)
            .map(Vec::len),
        Some(1)
    );
    assert_eq!(
        first
            .get("features")
            .and_then(serde_json::Value::as_array)
            .and_then(|features| features.first())
            .and_then(|feature| feature.get("kind"))
            .and_then(serde_json::Value::as_str),
        Some("sponsored")
    );
    assert_eq!(
        first
            .get("attempts")
            .and_then(serde_json::Value::as_array)
            .and_then(|attempts| attempts.first())
            .and_then(|attempt| attempt.get("http_status"))
            .and_then(serde_json::Value::as_u64),
        Some(200)
    );
    assert_eq!(
        first
            .get("cost")
            .and_then(|cost| cost.get("status"))
            .and_then(serde_json::Value::as_str),
        Some("unknown")
    );
    let first_hit = first
        .get("hits")
        .and_then(serde_json::Value::as_array)
        .and_then(|hits| hits.first())
        .ok_or("first hit missing")?;
    assert_eq!(
        first_hit
            .get("organic_rank")
            .and_then(serde_json::Value::as_u64),
        Some(4)
    );
    Ok(())
}

#[test]
fn human_formatter_groups_by_provider_and_removes_terminal_controls() -> Result<(), Box<dyn Error>>
{
    let mut output = Vec::new();
    let mut envelope = fixture();
    if let Some(hit) = envelope
        .providers
        .first_mut()
        .and_then(|provider| provider.hits.first_mut())
    {
        hit.title = Some("Example\u{1b}[31m");
    }
    render_human(&mut output, &envelope, Theme::plain())?;
    let text = String::from_utf8(output)?;
    assert!(
        text.find("brave:").ok_or("Brave group missing")?
            < text.find("bing:").ok_or("Bing group missing")?
    );
    assert!(text.contains("  Provider profile: preview"));
    assert!(text.contains("  4. Example [31m"));
    assert!(!text.contains('\u{1b}'));
    Ok(())
}

#[test]
fn exit_code_reflects_valid_partial_failed_and_interrupted_results() -> Result<(), Box<dyn Error>> {
    let envelope = fixture();
    let first = envelope.providers.first().ok_or("first provider missing")?;
    let second = envelope.providers.get(1).ok_or("second provider missing")?;
    assert_eq!(
        exit_code(&envelope.providers, envelope.termination, false),
        ExitCode::from(3)
    );
    assert_eq!(
        exit_code(slice::from_ref(first), "completed", false),
        ExitCode::from(3)
    );
    assert_eq!(
        exit_code(slice::from_ref(second), "completed", false),
        ExitCode::from(1)
    );
    assert_eq!(
        exit_code(&envelope.providers, envelope.termination, true),
        ExitCode::from(130)
    );
    assert_eq!(exit_code(&[], "completed", false), ExitCode::from(1));
    let mut clean = fixture();
    let clean_provider = clean.providers.first_mut().ok_or("provider missing")?;
    clean_provider.issues.clear();
    assert_eq!(
        exit_code(slice::from_ref(clean_provider), "completed", false),
        ExitCode::SUCCESS
    );
    if let Some(coverage) = clean_provider.coverage.as_mut() {
        coverage.web = "partial";
    }
    assert_eq!(
        exit_code(slice::from_ref(clean_provider), "completed", false),
        ExitCode::from(3)
    );
    Ok(())
}

#[test]
fn browser_failure_advice_and_ids_are_human_only() -> Result<(), Box<dyn Error>> {
    let mut envelope = fixture();
    let provider = envelope
        .providers
        .first_mut()
        .ok_or("missing provider fixture")?;
    provider.status = ProviderStatus::Failed;
    provider.detail = Some("transport_failure");
    provider.coverage = None;
    provider.hits.clear();
    provider
        .attempts
        .first_mut()
        .ok_or("missing request attempt")?
        .diagnostic = Some("browser_launch_failed");
    let mut human = Vec::new();
    render_human(&mut human, &envelope, Theme::plain())?;
    let text = String::from_utf8(human)?;
    assert!(text.contains("Chrome/Chromium could not start"));
    assert!(text.contains("Request: 123e4567-e89b-42d3-a456-426614174100"));
    assert!(text.contains("Capture: 123e4567-e89b-42d3-a456-426614174101"));
    let mut machine = Vec::new();
    render_json(&mut machine, &envelope)?;
    let value: serde_json::Value = serde_json::from_slice(&machine)?;
    assert_eq!(
        value
            .pointer("/providers/0/attempts/0/diagnostic")
            .and_then(serde_json::Value::as_str),
        Some("browser_launch_failed")
    );
    assert!(!String::from_utf8(machine)?.contains("Chrome/Chromium could not start"));
    Ok(())
}
