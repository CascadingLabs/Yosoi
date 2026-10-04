//! Provider-backed Search through Yosoi's public Search facade.

use std::{
    io::{self, Write},
    num::{NonZeroU16, NonZeroU32, NonZeroUsize},
    process::ExitCode,
};

use anyhow::{Context as _, Result};
use clap::{ArgAction, Args, ValueEnum};
use serde::Serialize;
use thiserror::Error;
use tokio::signal;
use yosoi::{
    CancellationToken, EffectivePolicyIdentity, Policy,
    policy::{
        AcquisitionKind, BrowserMode,
        search::{Provider, ProviderDefaultsStatus, ProviderDefaultsVersion, Search},
    },
    prelude as ys,
    search::{
        FeatureCoverage, ProviderCharge, ProviderOutcome, ProviderResult, RequestAttemptTerminal,
        SearchAttemptDiagnostic, SearchFailure, SearchFeature, SearchHit, SearchIssue,
        SearchIssueKind, SearchResponse, SearchResultUrl, SearchTermination,
        SearchUnavailableReason, WebCoverage,
    },
};

use crate::{policy_store::PolicyStore, stats::RunTimer};

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum ProviderChoice {
    Brave,
    Bing,
    #[value(name = "duckduckgo")]
    DuckDuckGo,
}

impl ProviderChoice {
    const fn into_provider(self) -> Provider {
        match self {
            Self::Brave => Provider::Brave,
            Self::Bing => Provider::Bing,
            Self::DuckDuckGo => Provider::DuckDuckGo,
        }
    }
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, ValueEnum)]
pub enum OutputFormat {
    Human,
    Json,
}

#[derive(Debug, Args)]
pub struct SearchArgs {
    /// Text to search for.
    pub query: String,
    /// Ordered providers, as a comma-separated enum list.
    #[arg(short = 'p', long = "providers", value_enum, value_delimiter = ',', action = ArgAction::Append)]
    pub providers: Vec<ProviderChoice>,
    /// Report wall time and Search totals on stderr.
    #[arg(short = 's', long = "stats")]
    pub stats: bool,
    /// Override the Search Policy's maximum retained results from each provider.
    #[arg(long)]
    pub per_provider_limit: Option<NonZeroU16>,
    /// Override the Search Policy's provider concurrency bound.
    #[arg(long)]
    pub max_in_flight: Option<NonZeroUsize>,
    /// Output format.
    #[arg(long, value_enum, default_value_t = OutputFormat::Human)]
    pub output: OutputFormat,
}

#[derive(Debug, Error)]
pub enum SearchCommandError {
    #[error("{0:#}")]
    Setup(#[source] anyhow::Error),
    #[error("{0:#}")]
    Output(#[source] anyhow::Error),
}

pub async fn run(args: SearchArgs, profile: Option<&str>) -> Result<ExitCode, SearchCommandError> {
    let timer = RunTimer::start();
    let (policy, profile_name) =
        policy_for_search(&args, profile).map_err(SearchCommandError::Setup)?;
    let request = ys::search::new(args.query)
        .context("invalid Search query")
        .map_err(SearchCommandError::Setup)?
        .bind(&policy);

    let cancellation = CancellationToken::new();
    let send = request.send_cancellable(&cancellation);
    tokio::pin!(send);
    let (response, interrupted) = tokio::select! {
        result = &mut send => (result, false),
        signal_result = signal::ctrl_c() => {
            signal_result.context("could not listen for Ctrl-C").map_err(SearchCommandError::Setup)?;
            cancellation.cancel();
            (send.await, true)
        }
    };
    let response = response
        .context("Search setup failed")
        .map_err(SearchCommandError::Setup)?;
    let envelope = SearchEnvelope::from_response(&response, profile_name.as_deref());

    let rendered: anyhow::Result<()> = match args.output {
        OutputFormat::Human => {
            render_human(&mut io::stdout().lock(), &envelope).map_err(Into::into)
        }
        OutputFormat::Json => render_json(&mut io::stdout().lock(), &envelope),
    };
    rendered.map_err(SearchCommandError::Output)?;
    report_diagnostics(&response, interrupted).map_err(|error| {
        SearchCommandError::Output(
            anyhow::Error::new(error).context("could not write Search diagnostics"),
        )
    })?;
    if args.stats {
        report_stats(&envelope, &timer)
            .context("could not write Search stats")
            .map_err(SearchCommandError::Output)?;
    }

    Ok(exit_code(
        &envelope.providers,
        envelope.termination,
        interrupted,
    ))
}

pub fn report_error(error: &SearchCommandError) -> ExitCode {
    let code = match error {
        SearchCommandError::Setup(_) => 2,
        SearchCommandError::Output(_) => 1,
    };
    let _ = writeln!(io::stderr().lock(), "yosoi search: {error}");
    ExitCode::from(code)
}

fn policy_for_search(args: &SearchArgs, profile: Option<&str>) -> Result<(Policy, Option<String>)> {
    let store = PolicyStore::load().context("could not load the Policy profile store")?;
    let selected = profile.or_else(|| store.active_profile());
    let mut policy = match selected {
        Some(name) => store.resolve_profile(name)?,
        None => store.current()?,
    };
    policy.search = search_for_cli(&policy.search, args)?;
    policy.validate().context("Search Policy is invalid")?;
    Ok((policy, selected.map(str::to_owned)))
}

fn search_for_cli(base: &Search, args: &SearchArgs) -> Result<Search> {
    let mut search = base.clone();
    if !args.providers.is_empty() {
        let providers = args
            .providers
            .iter()
            .copied()
            .map(ProviderChoice::into_provider)
            .collect::<Vec<_>>();
        let selected = Search::new(providers).context("invalid CLI Search provider selection")?;
        search.providers = selected
            .providers()
            .iter()
            .map(|requested| {
                base.providers()
                    .iter()
                    .find(|existing| existing.provider == requested.provider)
                    .cloned()
                    .unwrap_or_else(|| requested.clone())
            })
            .collect();
    }
    if search.providers().is_empty() {
        anyhow::bail!("select Search providers with --providers or in the selected Policy profile");
    }

    let per_provider_limit = args
        .per_provider_limit
        .unwrap_or_else(|| search.max_results_per_provider());
    let provider_count =
        u32::try_from(search.providers().len()).context("too many Search providers")?;
    let required_total = u32::from(per_provider_limit.get())
        .checked_mul(provider_count)
        .ok_or_else(|| anyhow::anyhow!("Search result limits exceed the supported range"))?;
    let total_result_limit = NonZeroU32::new(search.max_total_results().get().max(required_total))
        .ok_or_else(|| anyhow::anyhow!("Search total result limit must be positive"))?;
    search = search
        .with_result_limits(per_provider_limit, total_result_limit)
        .context("invalid Search result limits")?;
    if let Some(max_in_flight) = args.max_in_flight {
        search = search
            .with_max_in_flight(max_in_flight)
            .context("invalid Search concurrency limit")?;
    }
    Ok(search)
}

#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
enum ProviderStatus {
    Results,
    Empty,
    Failed,
    Cancelled,
    NotStarted,
}

impl ProviderStatus {
    const fn is_valid(self) -> bool {
        matches!(self, Self::Results | Self::Empty)
    }

    const fn label(self) -> &'static str {
        match self {
            Self::Results => "results",
            Self::Empty => "empty",
            Self::Failed => "failed",
            Self::Cancelled => "cancelled",
            Self::NotStarted => "not_started",
        }
    }
}

#[derive(Debug, Serialize)]
struct PolicyIdentityView {
    version: u16,
    digest: String,
}

impl From<EffectivePolicyIdentity> for PolicyIdentityView {
    fn from(identity: EffectivePolicyIdentity) -> Self {
        Self {
            version: identity.version(),
            digest: identity.digest().to_string(),
        }
    }
}

#[derive(Debug, Serialize)]
struct SearchEnvelope<'a> {
    schema_version: u16,
    cli_version: &'static str,
    policy_profile: Option<&'a str>,
    policy_identity: PolicyIdentityView,
    termination: &'static str,
    providers: Vec<ProviderView<'a>>,
}

impl<'a> SearchEnvelope<'a> {
    fn from_response(response: &'a SearchResponse, policy_profile: Option<&'a str>) -> Self {
        Self {
            schema_version: 2,
            cli_version: env!("CARGO_PKG_VERSION"),
            policy_profile,
            policy_identity: response.policy_identity().into(),
            termination: termination_name(response.termination()),
            providers: response
                .providers()
                .iter()
                .map(ProviderView::from_result)
                .collect(),
        }
    }
}

#[derive(Debug, Serialize)]
struct ProviderIdentityView<'a> {
    endpoint: Option<&'a str>,
    adapter_version: Option<&'a str>,
    parser_version: Option<&'a str>,
}

#[derive(Debug, Serialize)]
struct ProviderProfileView {
    acquisition: Option<AcquisitionKind>,
    defaults_status: &'static str,
    defaults_version: Option<u16>,
    effective_request_policy: Option<PolicyIdentityView>,
}

#[derive(Debug, Serialize)]
struct HitView<'a> {
    organic_rank: u16,
    placement_index: u16,
    url: &'a str,
    title: Option<&'a str>,
    snippet: Option<&'a str>,
    display_url: Option<&'a str>,
    publisher: Option<&'a str>,
    published_at: Option<&'a str>,
    thumbnail_url: Option<&'a str>,
}

#[derive(Debug, Serialize)]
struct IssueView {
    placement_index: Option<u16>,
    kind: &'static str,
}

#[derive(Debug, Serialize)]
struct ChargeView<'a> {
    status: &'static str,
    currency: Option<&'a str>,
    amount: Option<&'a str>,
}

#[derive(Debug, Serialize)]
struct CoverageView {
    web: &'static str,
    rich_features: &'static str,
}

#[derive(Debug, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
enum FeatureView<'a> {
    Sponsored {
        placement_index: u16,
        destination: &'a str,
        label: Option<&'a str>,
    },
    Answer {
        placement_index: u16,
        text: &'a str,
        citations: Vec<&'a str>,
    },
    ImageGallery {
        placement_index: u16,
        images: Vec<ImageView<'a>>,
    },
    LocalPack {
        placement_index: u16,
        places: Vec<LocalPlaceView<'a>>,
        map_url: Option<&'a str>,
    },
}

#[derive(Debug, Serialize)]
struct ImageView<'a> {
    image_url: &'a str,
    source_page_url: &'a str,
}

#[derive(Debug, Serialize)]
struct LocalPlaceView<'a> {
    name: &'a str,
    place_url: &'a str,
}

impl<'a> FeatureView<'a> {
    fn from_feature(feature: &'a SearchFeature) -> Self {
        match feature {
            SearchFeature::Sponsored {
                placement_index,
                destination,
                label,
            } => Self::Sponsored {
                placement_index: placement_index.get(),
                destination: destination.as_str(),
                label: label.as_deref(),
            },
            SearchFeature::Answer {
                placement_index,
                text,
                citations,
            } => Self::Answer {
                placement_index: placement_index.get(),
                text,
                citations: citations.iter().map(SearchResultUrl::as_str).collect(),
            },
            SearchFeature::ImageGallery {
                placement_index,
                images,
            } => Self::ImageGallery {
                placement_index: placement_index.get(),
                images: images
                    .iter()
                    .map(|image| ImageView {
                        image_url: image.image_url.as_str(),
                        source_page_url: image.source_page_url.as_str(),
                    })
                    .collect(),
            },
            SearchFeature::LocalPack {
                placement_index,
                places,
                map_url,
            } => Self::LocalPack {
                placement_index: placement_index.get(),
                places: places
                    .iter()
                    .map(|place| LocalPlaceView {
                        name: &place.name,
                        place_url: place.place_url.as_str(),
                    })
                    .collect(),
                map_url: map_url.as_ref().map(SearchResultUrl::as_str),
            },
        }
    }

    const fn label(&self) -> &'static str {
        match self {
            Self::Sponsored { .. } => "sponsored",
            Self::Answer { .. } => "answer",
            Self::ImageGallery { .. } => "image gallery",
            Self::LocalPack { .. } => "local pack",
        }
    }
}

#[derive(Debug, Serialize)]
struct RequestAttemptView {
    request_id: String,
    capture_id: String,
    acquisition: AcquisitionKind,
    http_status: Option<u16>,
    source_bytes: Option<u64>,
    diagnostic: Option<&'static str>,
    terminal: &'static str,
}

#[derive(Debug, Serialize)]
struct ProviderView<'a> {
    provider: &'static str,
    identity: ProviderIdentityView<'a>,
    status: ProviderStatus,
    coverage: Option<CoverageView>,
    detail: Option<&'static str>,
    profile: ProviderProfileView,
    request_id: Option<String>,
    recovery_query: Option<&'a str>,
    attempts: Vec<RequestAttemptView>,
    hits: Vec<HitView<'a>>,
    features: Vec<FeatureView<'a>>,
    applied_filters: Vec<&'static str>,
    issues: Vec<IssueView>,
    cost: ChargeView<'a>,
}

impl<'a> ProviderView<'a> {
    fn from_result(result: &'a ProviderResult) -> Self {
        let (status, coverage, detail, hits, features, issues) = match result.outcome() {
            ProviderOutcome::Results(page) => (
                ProviderStatus::Results,
                Some(CoverageView {
                    web: match page.coverage().web() {
                        WebCoverage::Complete => "complete",
                        WebCoverage::Partial => "partial",
                    },
                    rich_features: match page.coverage().rich_features() {
                        FeatureCoverage::NotCollected => "not_collected",
                        FeatureCoverage::Collected => "collected",
                        FeatureCoverage::Partial => "partial",
                    },
                }),
                None,
                page.hits().iter().map(HitView::from_hit).collect(),
                page.features()
                    .iter()
                    .map(FeatureView::from_feature)
                    .collect(),
                page.issues().iter().map(IssueView::from_issue).collect(),
            ),
            ProviderOutcome::Empty => (
                ProviderStatus::Empty,
                None,
                None,
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
            ProviderOutcome::Failed(failure) => (
                ProviderStatus::Failed,
                None,
                Some(failure_name(*failure)),
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
            ProviderOutcome::Cancelled => (
                ProviderStatus::Cancelled,
                None,
                None,
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
            ProviderOutcome::NotStarted(reason) => (
                ProviderStatus::NotStarted,
                None,
                Some(unavailable_name(*reason)),
                Vec::new(),
                Vec::new(),
                Vec::new(),
            ),
        };
        let identity = result.identity();
        let profile = result.profile();
        Self {
            provider: provider_name(result.provider()),
            identity: ProviderIdentityView {
                endpoint: identity.endpoint,
                adapter_version: identity.adapter_version,
                parser_version: identity.parser_version,
            },
            status,
            coverage,
            detail,
            profile: ProviderProfileView {
                acquisition: profile.acquisition,
                defaults_status: defaults_status_name(profile.defaults_status),
                defaults_version: profile.defaults_version.map(ProviderDefaultsVersion::get),
                effective_request_policy: profile.effective_request_policy.map(Into::into),
            },
            request_id: result.request_id().map(|id| id.to_string()),
            recovery_query: result.recovery_query(),
            attempts: result
                .attempts()
                .iter()
                .map(|attempt| RequestAttemptView {
                    request_id: attempt.request_id.to_string(),
                    capture_id: attempt.capture_id.to_string(),
                    acquisition: attempt.acquisition,
                    http_status: attempt.http_status,
                    source_bytes: attempt.source_bytes,
                    diagnostic: attempt.diagnostic.map(attempt_diagnostic_name),
                    terminal: match attempt.terminal {
                        RequestAttemptTerminal::Completed => "completed",
                        RequestAttemptTerminal::Failed => "failed",
                        RequestAttemptTerminal::NotStarted => "not_started",
                    },
                })
                .collect(),
            hits,
            features,
            applied_filters: Vec::new(),
            issues,
            cost: ChargeView::from_charge(result.charge()),
        }
    }
}

impl<'a> HitView<'a> {
    fn from_hit(hit: &'a SearchHit) -> Self {
        Self {
            organic_rank: hit.organic_rank().get(),
            placement_index: hit.placement_index().get(),
            url: hit.url().as_str(),
            title: hit.title(),
            snippet: hit.snippet(),
            display_url: hit.display_url(),
            publisher: hit.publisher(),
            published_at: hit.published_at(),
            thumbnail_url: hit.thumbnail_url().map(SearchResultUrl::as_str),
        }
    }
}

impl IssueView {
    fn from_issue(issue: &SearchIssue) -> Self {
        Self {
            placement_index: issue.placement_index.map(NonZeroU16::get),
            kind: issue_name(issue.kind),
        }
    }
}

impl<'a> ChargeView<'a> {
    fn from_charge(charge: &'a ProviderCharge) -> Self {
        match charge {
            ProviderCharge::Unknown => Self {
                status: "unknown",
                currency: None,
                amount: None,
            },
            ProviderCharge::Known { currency, amount } => Self {
                status: "known",
                currency: Some(currency),
                amount: Some(amount),
            },
        }
    }
}

const fn provider_name(provider: Provider) -> &'static str {
    match provider {
        Provider::Brave => "brave",
        Provider::Bing => "bing",
        Provider::DuckDuckGo => "duckduckgo",
    }
}

const fn defaults_status_name(status: ProviderDefaultsStatus) -> &'static str {
    match status {
        ProviderDefaultsStatus::Unavailable { .. } => "unavailable",
        ProviderDefaultsStatus::Preview { .. } => "preview",
        ProviderDefaultsStatus::Certified { .. } => "certified",
        ProviderDefaultsStatus::Exact => "exact",
    }
}

const fn attempt_diagnostic_name(diagnostic: SearchAttemptDiagnostic) -> &'static str {
    match diagnostic {
        SearchAttemptDiagnostic::MissingExecutionContext => "missing_execution_context",
        SearchAttemptDiagnostic::PolicyResolutionFailed => "policy_resolution_failed",
        SearchAttemptDiagnostic::DirectHttpTransport => "direct_http_transport",
        SearchAttemptDiagnostic::DirectHttpBodyFailed => "direct_http_body_failed",
        SearchAttemptDiagnostic::DirectHttpFinalizationFailed => "direct_http_finalization_failed",
        SearchAttemptDiagnostic::BrowserCancelled => "browser_cancelled",
        SearchAttemptDiagnostic::BrowserCancelledCleanupFailed => {
            "browser_cancelled_cleanup_failed"
        }
        SearchAttemptDiagnostic::BrowserCleanupFailed => "browser_cleanup_failed",
        SearchAttemptDiagnostic::BrowserCaptureFailed => "browser_capture_failed",
        SearchAttemptDiagnostic::BrowserFinalizationFailed => "browser_finalization_failed",
        SearchAttemptDiagnostic::BrowserFeatureDisabled => "browser_feature_disabled",
        SearchAttemptDiagnostic::ProjectionFailed => "projection_failed",
    }
}

const fn failure_name(failure: SearchFailure) -> &'static str {
    match failure {
        SearchFailure::RateLimited => "rate_limited",
        SearchFailure::Challenge => "challenge",
        SearchFailure::ProviderUnavailable => "provider_unavailable",
        SearchFailure::MalformedResponse => "malformed_response",
        SearchFailure::QueryMismatch => "query_mismatch",
        SearchFailure::TransportFailure => "transport_failure",
        SearchFailure::BudgetExhausted => "budget_exhausted",
    }
}

const fn unavailable_name(reason: SearchUnavailableReason) -> &'static str {
    match reason {
        SearchUnavailableReason::DefaultUncertified => "default_uncertified",
        SearchUnavailableReason::AdapterUnavailable => "adapter_unavailable",
        SearchUnavailableReason::UnsupportedCapability => "unsupported_capability",
        SearchUnavailableReason::Cancelled => "cancelled",
        SearchUnavailableReason::DeadlineReached => "deadline_reached",
        SearchUnavailableReason::RequestSetupFailed => "request_setup_failed",
    }
}

const fn termination_name(termination: SearchTermination) -> &'static str {
    match termination {
        SearchTermination::Completed => "completed",
        SearchTermination::Cancelled => "cancelled",
        SearchTermination::DeadlineReached => "deadline_reached",
    }
}

const fn issue_name(kind: SearchIssueKind) -> &'static str {
    match kind {
        SearchIssueKind::InvalidDestination => "invalid_destination",
        SearchIssueKind::DuplicateDestination => "duplicate_destination",
        SearchIssueKind::MissingRequiredField => "missing_required_field",
        SearchIssueKind::UnrecognizedResultRow => "unrecognized_result_row",
        SearchIssueKind::OutputLimit => "output_limit",
        SearchIssueKind::QueryRelaxed => "query_relaxed",
    }
}

fn render_json(writer: &mut impl Write, envelope: &SearchEnvelope<'_>) -> Result<()> {
    serde_json::to_writer(&mut *writer, envelope).context("could not serialize Search output")?;
    writeln!(writer).context("could not finish Search JSON output")?;
    Ok(())
}

fn render_human(writer: &mut impl Write, envelope: &SearchEnvelope<'_>) -> io::Result<()> {
    for provider in &envelope.providers {
        writeln!(writer, "{}:", provider.provider)?;
        writeln!(writer, "  Status: {}", provider.status.label())?;
        if let Some(coverage) = &provider.coverage {
            writeln!(writer, "  Web coverage: {}", coverage.web)?;
            writeln!(writer, "  Rich features: {}", coverage.rich_features)?;
        }
        if let Some(detail) = provider.detail {
            writeln!(writer, "  Detail: {detail}")?;
        }
        for attempt in &provider.attempts {
            if let Some(diagnostic) = attempt.diagnostic {
                writeln!(writer, "  Request attempt: {diagnostic}")?;
            }
        }
        if let Some(acquisition) = provider.profile.acquisition {
            writeln!(writer, "  Acquisition: {}", acquisition_name(acquisition))?;
        }
        writeln!(
            writer,
            "  Provider profile: {}",
            provider.profile.defaults_status
        )?;
        if let Some(version) = provider.profile.defaults_version {
            writeln!(writer, "  Defaults version: {version}")?;
        }
        if let Some(query) = provider.recovery_query {
            writeln!(writer, "  Recovery query: {}", safe_terminal_text(query))?;
        }
        writeln!(writer, "  Cost: {}", provider.cost.status)?;

        for hit in &provider.hits {
            let label = hit.title.unwrap_or(hit.url);
            writeln!(
                writer,
                "  {}. {}",
                hit.organic_rank,
                safe_terminal_text(label)
            )?;
            if hit.title.is_some() {
                writeln!(writer, "     URL: {}", safe_terminal_text(hit.url))?;
            }
            if let Some(publisher) = hit.publisher {
                writeln!(writer, "     Publisher: {}", safe_terminal_text(publisher))?;
            }
            if let Some(published_at) = hit.published_at {
                writeln!(
                    writer,
                    "     Published: {}",
                    safe_terminal_text(published_at)
                )?;
            }
            if let Some(snippet) = hit.snippet {
                writeln!(writer, "     {}", safe_terminal_text(snippet))?;
            }
        }
        for feature in &provider.features {
            writeln!(writer, "  Feature: {}", feature.label())?;
        }
        for issue in &provider.issues {
            match issue.placement_index {
                Some(index) => writeln!(writer, "  Issue at placement {index}: {}", issue.kind)?,
                None => writeln!(writer, "  Issue: {}", issue.kind)?,
            }
        }
        if let Some(identity) = &provider.profile.effective_request_policy {
            writeln!(
                writer,
                "  Request Policy: v{} {}",
                identity.version, identity.digest
            )?;
        }
        writeln!(writer)?;
    }
    Ok(())
}

const fn acquisition_name(acquisition: AcquisitionKind) -> &'static str {
    match acquisition {
        AcquisitionKind::DirectHttp => "direct_http",
        AcquisitionKind::Browser {
            mode: BrowserMode::Headless,
        } => "browser_headless",
        AcquisitionKind::Browser {
            mode: BrowserMode::Headful,
        } => "browser_headful",
    }
}

fn safe_terminal_text(value: &str) -> String {
    value
        .chars()
        .map(|character| {
            if character.is_control() {
                ' '
            } else {
                character
            }
        })
        .collect()
}

fn report_diagnostics(response: &SearchResponse, interrupted: bool) -> io::Result<()> {
    let mut stderr = io::stderr().lock();
    for provider in response.providers() {
        match provider.outcome() {
            ProviderOutcome::Results(_) | ProviderOutcome::Empty => {}
            ProviderOutcome::Failed(failure) => {
                writeln!(
                    stderr,
                    "yosoi search: {} failed ({})",
                    provider_name(provider.provider()),
                    failure_name(*failure)
                )?;
            }
            ProviderOutcome::Cancelled => {
                writeln!(
                    stderr,
                    "yosoi search: {} was cancelled",
                    provider_name(provider.provider())
                )?;
            }
            ProviderOutcome::NotStarted(reason) => {
                writeln!(
                    stderr,
                    "yosoi search: {} did not start ({})",
                    provider_name(provider.provider()),
                    unavailable_name(*reason)
                )?;
            }
        }
    }
    if response.termination() == SearchTermination::DeadlineReached {
        writeln!(stderr, "yosoi search: the Search deadline was reached")?;
    }
    if interrupted {
        writeln!(
            stderr,
            "yosoi search: interrupted; partial provider output was preserved"
        )?;
    }
    Ok(())
}

fn report_stats(envelope: &SearchEnvelope<'_>, timer: &RunTimer) -> Result<()> {
    render_stats(&mut io::stderr().lock(), envelope, timer)
}

fn render_stats(
    writer: &mut impl Write,
    envelope: &SearchEnvelope<'_>,
    timer: &RunTimer,
) -> Result<()> {
    writeln!(writer, "Search stats:")?;
    timer.write_wall_time(writer)?;
    writeln!(writer, "Termination: {}", envelope.termination)?;
    writeln!(writer, "Providers: {}", envelope.providers.len())?;
    let mut hits = 0_usize;
    let mut attempts = 0_usize;
    let mut retained_source_bytes = 0_u64;
    for provider in &envelope.providers {
        hits = hits.saturating_add(provider.hits.len());
        attempts = attempts.saturating_add(provider.attempts.len());
        for attempt in &provider.attempts {
            if let Some(bytes) = attempt.source_bytes {
                retained_source_bytes = retained_source_bytes.saturating_add(bytes);
            }
        }
    }
    writeln!(writer, "Hits: {hits}")?;
    writeln!(writer, "Request attempts: {attempts}")?;
    writeln!(
        writer,
        "Known retained source bytes: {retained_source_bytes}"
    )?;
    Ok(())
}

fn exit_code(providers: &[ProviderView<'_>], termination: &str, interrupted: bool) -> ExitCode {
    if interrupted {
        return ExitCode::from(130);
    }
    let mut valid_count = 0_usize;
    let mut invalid_count = 0_usize;
    let mut partial = termination != "completed";
    for provider in providers {
        if provider.status.is_valid() {
            valid_count = valid_count.saturating_add(1);
            partial |= !provider.issues.is_empty()
                || provider.coverage.as_ref().is_some_and(|coverage| {
                    coverage.web == "partial" || coverage.rich_features == "partial"
                });
        } else {
            invalid_count = invalid_count.saturating_add(1);
        }
    }
    if invalid_count == 0 && valid_count > 0 && !partial {
        ExitCode::SUCCESS
    } else if valid_count == 0 {
        ExitCode::from(1)
    } else {
        ExitCode::from(3)
    }
}

#[cfg(test)]
#[allow(clippy::panic, clippy::panic_in_result_fn)]
mod tests {
    use std::{error::Error, slice};

    use super::*;
    use yosoi::policy;

    fn fixture() -> SearchEnvelope<'static> {
        SearchEnvelope {
            schema_version: 2,
            cli_version: "0.1.0",
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
            stats: false,
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
        render_stats(&mut output, &fixture(), &RunTimer::start())?;
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
    fn explicit_flags_replace_providers_and_override_profile_limits() -> Result<(), Box<dyn Error>>
    {
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
    fn human_formatter_groups_by_provider_and_removes_terminal_controls()
    -> Result<(), Box<dyn Error>> {
        let mut output = Vec::new();
        let mut envelope = fixture();
        if let Some(hit) = envelope
            .providers
            .first_mut()
            .and_then(|provider| provider.hits.first_mut())
        {
            hit.title = Some("Example\u{1b}[31m");
        }
        render_human(&mut output, &envelope)?;
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
    fn exit_code_reflects_valid_partial_failed_and_interrupted_results()
    -> Result<(), Box<dyn Error>> {
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
}
