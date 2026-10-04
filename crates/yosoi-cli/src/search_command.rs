//! Provider-backed Search command execution and output.

mod report;
#[cfg(test)]
#[expect(
    clippy::panic_in_result_fn,
    reason = "Assertions report Search CLI test failures."
)]
mod tests;
mod view;

use std::num::{NonZeroU16, NonZeroUsize};

use clap::{ArgAction, Args, ValueEnum};
use yosoi::policy::search::Provider;

use std::{
    io::{self, Write},
    num::NonZeroU32,
    process::ExitCode,
};

use anyhow::{Context as _, Result};
use thiserror::Error;
use tokio::signal;
use yosoi::{CancellationToken, Policy, policy::search::Search, prelude as ys};

use crate::{policy_store::PolicyStore, stats::RunTimer};

use view::SearchEnvelope;

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
            report::render_human(&mut io::stdout().lock(), &envelope).map_err(Into::into)
        }
        OutputFormat::Json => report::render_json(&mut io::stdout().lock(), &envelope),
    };
    rendered.map_err(SearchCommandError::Output)?;
    report::report_diagnostics(&response, interrupted).map_err(|error| {
        SearchCommandError::Output(
            anyhow::Error::new(error).context("could not write Search diagnostics"),
        )
    })?;
    if args.stats {
        report::report_stats(&envelope, &timer)
            .context("could not write Search stats")
            .map_err(SearchCommandError::Output)?;
    }

    Ok(report::exit_code(
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
