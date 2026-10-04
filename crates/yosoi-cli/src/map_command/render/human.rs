use std::{
    collections::BTreeMap,
    io::{self, Write},
    process::ExitCode,
};

use anyhow::Result;
use yosoi::{
    map,
    policy::{PageDiscovery, Subdomains},
};

use crate::{
    map_command::render::wire::{
        discovery_source_label, host_verification_label, skip_reason_label, source_failure_label,
        termination_label,
    },
    stats::RunTimer,
};

pub(super) fn human(outcome: &map::MapOutcome, profile: Option<&str>) -> Result<()> {
    let identity = outcome.policy_snapshot().identity();
    let mut stdout = io::stdout().lock();
    writeln!(
        stdout,
        "Policy profile: {}",
        profile.unwrap_or("<defaults>")
    )?;
    writeln!(
        stdout,
        "Policy identity: v{} {}",
        identity.version(),
        identity.digest()
    )?;
    writeln!(
        stdout,
        "Termination: {}",
        termination_label(outcome.termination())
    )?;
    writeln!(
        stdout,
        "Summary: {} hosts, {} pages, {} relationships, {} wildcard patterns, {} requests, {} response bytes, {} omitted",
        outcome.hosts().len(),
        outcome.pages().len(),
        outcome.relationships().len(),
        outcome.wildcard_names().len(),
        outcome.summary().requests,
        outcome.summary().response_bytes,
        outcome.summary().omitted,
    )?;

    writeln!(stdout, "Hosts:")?;
    if outcome.hosts().is_empty() {
        writeln!(stdout, "  (none)")?;
    }
    for host in outcome.hosts() {
        writeln!(
            stdout,
            "  {} ({})",
            host.host,
            host_verification_label(host.verification)
        )?;
    }

    writeln!(stdout, "Tree:")?;
    if outcome.tree().is_empty() {
        writeln!(stdout, "  (none)")?;
    }
    let exploration_by_url: BTreeMap<_, _> = outcome
        .pages()
        .iter()
        .map(|page| (&page.url, &page.exploration))
        .collect();
    for entry in outcome.tree() {
        let indent = entry.depth.map_or(0, |depth| usize::from(depth.min(6)));
        for _ in 0..indent {
            write!(stdout, "  ")?;
        }
        match entry.depth {
            Some(depth) => write!(stdout, "[{depth}] ")?,
            None => write!(stdout, "[?] ")?,
        }
        write!(stdout, "{}", entry.page)?;
        if let Some(parent) = &entry.parent {
            write!(stdout, " <- {parent}")?;
        }
        if let Some(exploration) = exploration_by_url.get(&entry.page) {
            write!(stdout, " ({})", exploration_human(exploration))?;
        }
        writeln!(stdout)?;
    }

    let mut has_issues = false;
    for source in outcome.sources() {
        if source_has_issue(source) {
            if !has_issues {
                writeln!(stdout, "Source issues:")?;
                has_issues = true;
            }
            write!(stdout, "  {}", discovery_source_label(source.source))?;
            if let Some(url) = &source.source_url {
                write!(stdout, " at {url}")?;
            }
            write!(stdout, ": ")?;
            write_source_status(&mut stdout, &source.status)?;
            writeln!(stdout)?;
        }
    }
    if !has_issues {
        writeln!(stdout, "Source issues: none")?;
    }
    Ok(())
}

pub(super) fn stats(outcome: &map::MapOutcome, timer: &RunTimer) -> Result<()> {
    let mut stderr = io::stderr().lock();
    writeln!(stderr, "Map stats:")?;
    timer.write_wall_time(&mut stderr)?;
    writeln!(
        stderr,
        "Termination: {}",
        termination_label(outcome.termination())
    )?;
    writeln!(stderr, "Requests: {}", outcome.summary().requests)?;
    writeln!(
        stderr,
        "Provider concurrency peak: {}",
        outcome.summary().provider_concurrency_peak
    )?;
    writeln!(
        stderr,
        "Page concurrency peak: {}",
        outcome.summary().page_concurrency_peak
    )?;
    writeln!(
        stderr,
        "Unused page prefetches: {}",
        outcome.summary().unused_page_prefetches
    )?;
    writeln!(
        stderr,
        "Response bytes: {}",
        outcome.summary().response_bytes
    )?;
    writeln!(
        stderr,
        "Inventory bytes: {}",
        outcome.summary().inventory_bytes
    )?;
    writeln!(
        stderr,
        "Retained document bytes: {}",
        outcome.summary().retained_document_bytes
    )?;
    Ok(())
}

pub(super) fn exit_code(outcome: &map::MapOutcome) -> ExitCode {
    if outcome.termination() == map::MapTermination::Cancelled {
        return ExitCode::from(130);
    }

    let policy = &outcome.policy_snapshot().effective_policy().map;
    let work_selected =
        policy.pages == PageDiscovery::Explore || policy.subdomains == Subdomains::Passive;
    if !work_selected {
        return ExitCode::SUCCESS;
    }

    if matches!(
        outcome.termination(),
        map::MapTermination::Limit(_) | map::MapTermination::Deadline
    ) {
        return ExitCode::from(3);
    }

    if !has_useful_discovery(outcome) {
        return ExitCode::from(1);
    }

    if outcome.termination() == map::MapTermination::Exhausted && !has_material_failure(outcome) {
        ExitCode::SUCCESS
    } else {
        ExitCode::from(3)
    }
}

const fn source_has_issue(source: &map::SourceOutcome) -> bool {
    if matches!(
        source.source,
        map::DiscoverySource::Robots | map::DiscoverySource::Sitemap
    ) && matches!(
        source.status,
        map::SourceStatus::Failed(map::SourceFailure::HttpStatus(404 | 410))
    ) {
        return false;
    }
    matches!(
        source.status,
        map::SourceStatus::Failed(_)
            | map::SourceStatus::Truncated
            | map::SourceStatus::Sampled
            | map::SourceStatus::NotStarted
    )
}

fn write_source_status(output: &mut impl Write, status: &map::SourceStatus) -> io::Result<()> {
    match status {
        map::SourceStatus::Completed => write!(output, "completed"),
        map::SourceStatus::Sampled => {
            write!(output, "public index sample (completeness not guaranteed)")
        }
        map::SourceStatus::Skipped(map::SourceSkipReason::NotSitemap) => {
            write!(output, "not a sitemap (HTML response)")
        }
        map::SourceStatus::Disabled => write!(output, "disabled"),
        map::SourceStatus::NotStarted => write!(output, "not started"),
        map::SourceStatus::Truncated => write!(output, "truncated"),
        map::SourceStatus::Failed(failure) => {
            write!(output, "failed ({})", source_failure_label(failure))
        }
    }
}

fn has_useful_discovery(outcome: &map::MapOutcome) -> bool {
    outcome
        .pages()
        .iter()
        .any(|page| page.exploration == map::Exploration::Inspected)
        || outcome.sources().iter().any(|source| {
            source.source.is_passive()
                && matches!(
                    source.status,
                    map::SourceStatus::Completed | map::SourceStatus::Sampled
                )
        })
        || outcome.hosts().iter().any(|host| {
            host.observations
                .iter()
                .any(|observation| observation.source.is_passive())
        })
        || outcome.pages().iter().any(|page| {
            page.observations
                .iter()
                .any(|observation| observation.source.is_passive())
        })
        || !outcome.wildcard_names().is_empty()
        || outcome
            .support_documents()
            .iter()
            .any(|document| match &document.status {
                map::SourceStatus::Completed
                    if document.kind == map::SupportDocumentKind::Sitemap
                        || document.kind == map::SupportDocumentKind::SitemapIndex =>
                {
                    true
                }
                map::SourceStatus::Completed
                    if document.kind == map::SupportDocumentKind::Robots =>
                {
                    outcome.request_trace().iter().any(|trace| {
                        trace.target == document.url && matches!(trace.status, Some(200..=299))
                    })
                }
                _ => false,
            })
}

fn has_material_failure(outcome: &map::MapOutcome) -> bool {
    outcome
        .pages()
        .iter()
        .any(|page| matches!(&page.exploration, map::Exploration::Failed(_)))
        || outcome.sources().iter().any(source_has_material_failure)
        || outcome
            .support_documents()
            .iter()
            .any(|document| match &document.status {
                map::SourceStatus::Failed(map::SourceFailure::HttpStatus(404 | 410)) => false,
                map::SourceStatus::Failed(_)
                | map::SourceStatus::Truncated
                | map::SourceStatus::Sampled => true,
                _ => false,
            })
}

const fn source_has_material_failure(source: &map::SourceOutcome) -> bool {
    match &source.status {
        map::SourceStatus::Failed(map::SourceFailure::HttpStatus(404 | 410))
            if matches!(
                source.source,
                map::DiscoverySource::Robots | map::DiscoverySource::Sitemap
            ) =>
        {
            false
        }
        map::SourceStatus::Failed(_)
        | map::SourceStatus::Truncated
        | map::SourceStatus::Sampled => true,
        _ => false,
    }
}

fn exploration_human(exploration: &map::Exploration) -> String {
    match exploration {
        map::Exploration::Inventoried => "inventoried".to_owned(),
        map::Exploration::Pending => "pending".to_owned(),
        map::Exploration::Inspected => "inspected".to_owned(),
        map::Exploration::Skipped(reason) => format!("skipped ({})", skip_reason_label(*reason)),
        map::Exploration::Failed(failure) => format!("failed ({})", source_failure_label(failure)),
    }
}
