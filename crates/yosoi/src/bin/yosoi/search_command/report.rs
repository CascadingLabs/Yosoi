use std::{
    io::{self, Write},
    process::ExitCode,
};

use anyhow::{Context as _, Result};
use yosoi::{
    policy::{AcquisitionKind, BrowserMode},
    search::{ProviderOutcome, SearchResponse, SearchTermination},
};

use crate::{browser_diagnostics, presentation::Theme, stats::RunTimer};

use super::view::names::{failure_name, provider_name, unavailable_name};
use super::view::{ProviderView, SearchEnvelope};

pub(super) fn render_json(writer: &mut impl Write, envelope: &SearchEnvelope<'_>) -> Result<()> {
    serde_json::to_writer(&mut *writer, envelope).context("could not serialize Search output")?;
    writeln!(writer).context("could not finish Search JSON output")?;
    Ok(())
}

pub(super) fn render_human(
    writer: &mut impl Write,
    envelope: &SearchEnvelope<'_>,
    theme: Theme,
) -> io::Result<()> {
    let heading = theme.heading;
    let label = theme.label;
    let value = theme.value;
    let muted = theme.muted;
    for provider in &envelope.providers {
        writeln!(writer, "{heading}{}:{heading:#}", provider.provider)?;
        let status = theme.status(provider.status.label());
        writeln!(
            writer,
            "  {label}Status:{label:#} {status}{}{status:#}",
            provider.status.label()
        )?;
        if let Some(coverage) = &provider.coverage {
            writeln!(
                writer,
                "  {label}Web coverage:{label:#} {value}{}{value:#}",
                coverage.web
            )?;
            writeln!(
                writer,
                "  {label}Rich features:{label:#} {value}{}{value:#}",
                coverage.rich_features
            )?;
        }
        if let Some(detail) = provider.detail {
            writeln!(
                writer,
                "  {label}Detail:{label:#} {status}{detail}{status:#}"
            )?;
            let explanation = match detail {
                "unsupported_capability"
                    if !cfg!(feature = "browser")
                        && provider.profile.acquisition.is_some_and(|kind| {
                            matches!(kind, AcquisitionKind::Browser { .. })
                        }) =>
                {
                    Some(
                        "This provider needs browser support; rebuild yosoi-cli with its default features.",
                    )
                }
                "query_mismatch" => Some(
                    "The relevance check could not verify these results against your query; they were discarded.",
                ),
                _ => None,
            };
            if let Some(explanation) = explanation {
                writeln!(writer, "  {status}{explanation}{status:#}")?;
            }
        }
        for attempt in &provider.attempts {
            if let Some(diagnostic) = attempt.diagnostic {
                writeln!(
                    writer,
                    "  {label}Request attempt:{label:#} {status}{diagnostic}{status:#}"
                )?;
                if let Some(advice) = browser_diagnostics::advice(diagnostic) {
                    writeln!(writer, "  {status}{advice}{status:#}")?;
                    writeln!(
                        writer,
                        "  {muted}Request: {}; Capture: {}{muted:#}",
                        attempt.request_id, attempt.capture_id
                    )?;
                }
            }
        }
        if let Some(acquisition) = provider.profile.acquisition {
            writeln!(
                writer,
                "  {label}Acquisition:{label:#} {value}{}{value:#}",
                acquisition_name(acquisition)
            )?;
        }
        writeln!(
            writer,
            "  {label}Provider profile:{label:#} {value}{}{value:#}",
            provider.profile.defaults_status
        )?;
        if let Some(version) = provider.profile.defaults_version {
            writeln!(
                writer,
                "  {label}Defaults version:{label:#} {value}{version}{value:#}"
            )?;
        }
        if let Some(query) = provider.recovery_query {
            writeln!(
                writer,
                "  {label}Recovery query:{label:#} {value}{}{value:#}",
                safe_terminal_text(query)
            )?;
        }
        writeln!(
            writer,
            "  {label}Cost:{label:#} {value}{}{value:#}",
            provider.cost.status
        )?;

        for hit in &provider.hits {
            let title = hit.title.unwrap_or(hit.url);
            writeln!(
                writer,
                "  {muted}{}.{muted:#} {value}{}{value:#}",
                hit.organic_rank,
                safe_terminal_text(title)
            )?;
            if hit.title.is_some() {
                writeln!(
                    writer,
                    "     {label}URL:{label:#} {value}{}{value:#}",
                    safe_terminal_text(hit.url)
                )?;
            }
            if let Some(publisher) = hit.publisher {
                writeln!(
                    writer,
                    "     {label}Publisher:{label:#} {value}{}{value:#}",
                    safe_terminal_text(publisher)
                )?;
            }
            if let Some(published_at) = hit.published_at {
                writeln!(
                    writer,
                    "     {label}Published:{label:#} {value}{}{value:#}",
                    safe_terminal_text(published_at)
                )?;
            }
            if let Some(snippet) = hit.snippet {
                writeln!(writer, "     {}", safe_terminal_text(snippet))?;
            }
        }
        for feature in &provider.features {
            writeln!(
                writer,
                "  {label}Feature:{label:#} {value}{}{value:#}",
                feature.label()
            )?;
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
                "  {muted}Request Policy: v{} {}{muted:#}",
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

pub(super) fn report_diagnostics(response: &SearchResponse, interrupted: bool) -> io::Result<()> {
    let error = Theme::stderr().error;
    let mut stderr = io::stderr().lock();
    for provider in response.providers() {
        match provider.outcome() {
            ProviderOutcome::Results(_) | ProviderOutcome::Empty => {}
            ProviderOutcome::Failed(failure) => {
                writeln!(
                    stderr,
                    "{error}yosoi search: {} failed ({}){error:#}",
                    provider_name(provider.provider()),
                    failure_name(*failure)
                )?;
            }
            ProviderOutcome::Cancelled => {
                writeln!(
                    stderr,
                    "{error}yosoi search: {} was cancelled{error:#}",
                    provider_name(provider.provider())
                )?;
            }
            ProviderOutcome::NotStarted(reason) => {
                writeln!(
                    stderr,
                    "{error}yosoi search: {} did not start ({}){error:#}",
                    provider_name(provider.provider()),
                    unavailable_name(*reason)
                )?;
            }
        }
    }
    if response.termination() == SearchTermination::DeadlineReached {
        writeln!(
            stderr,
            "{error}yosoi search: the Search deadline was reached{error:#}"
        )?;
    }
    if interrupted {
        writeln!(
            stderr,
            "{error}yosoi search: interrupted; partial provider output was preserved{error:#}"
        )?;
    }
    Ok(())
}

pub(super) fn report_stats(envelope: &SearchEnvelope<'_>, timer: &RunTimer) -> Result<()> {
    render_stats(&mut io::stderr().lock(), envelope, timer, Theme::stderr())
}

pub(super) fn render_stats(
    writer: &mut impl Write,
    envelope: &SearchEnvelope<'_>,
    timer: &RunTimer,
    theme: Theme,
) -> Result<()> {
    let label = theme.label;
    let value = theme.value;
    timer.write_header(writer, "Search", theme)?;
    writeln!(
        writer,
        "{label}Termination:{label:#} {value}{}{value:#}",
        envelope.termination
    )?;
    writeln!(
        writer,
        "{label}Providers:{label:#} {value}{}{value:#}",
        envelope.providers.len()
    )?;
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
    writeln!(writer, "{label}Hits:{label:#} {value}{hits}{value:#}")?;
    writeln!(
        writer,
        "{label}Request attempts:{label:#} {value}{attempts}{value:#}"
    )?;
    writeln!(
        writer,
        "{label}Known retained source bytes:{label:#} {value}{retained_source_bytes}{value:#}"
    )?;
    Ok(())
}

pub(super) fn exit_code(
    providers: &[ProviderView<'_>],
    termination: &str,
    interrupted: bool,
) -> ExitCode {
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
