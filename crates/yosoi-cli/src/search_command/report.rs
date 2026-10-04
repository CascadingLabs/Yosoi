use std::{
    io::{self, Write},
    process::ExitCode,
};

use anyhow::{Context as _, Result};
use yosoi::{
    policy::{AcquisitionKind, BrowserMode},
    search::{ProviderOutcome, SearchResponse, SearchTermination},
};

use crate::stats::RunTimer;

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
) -> io::Result<()> {
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

pub(super) fn report_diagnostics(response: &SearchResponse, interrupted: bool) -> io::Result<()> {
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

pub(super) fn report_stats(envelope: &SearchEnvelope<'_>, timer: &RunTimer) -> Result<()> {
    render_stats(&mut io::stderr().lock(), envelope, timer)
}

pub(super) fn render_stats(
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
