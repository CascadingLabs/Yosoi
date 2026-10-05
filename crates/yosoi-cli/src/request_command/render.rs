//! Bounded presentation of public Requests outcomes.

use std::{
    io::{self, Write},
    process::ExitCode,
};

use anyhow::{Context as _, Result, bail};
use serde_json::json;
use yosoi::{
    EffectivePolicyIdentity, ResponseTermination,
    documents::DocumentRef,
    policy::{AcquisitionKind, BrowserMode, DocumentRequest},
    request::{AttemptDiagnostic, AttemptState, DocumentOutcome, Response},
};

use crate::{browser_diagnostics, presentation::Theme, stats::RunTimer};

const MAX_RAW_BYTES: usize = 16 * 1024 * 1024;

pub(super) fn stats(response: &Response, timer: &RunTimer) -> Result<()> {
    let theme = Theme::stderr();
    let label = theme.label;
    let value = theme.value;
    let mut stderr = io::stderr().lock();
    timer.write_header(&mut stderr, "Request", theme)?;
    writeln!(
        stderr,
        "{label}Termination:{label:#} {value}{}{value:#}",
        termination_label(response.termination())
    )?;
    writeln!(
        stderr,
        "{label}Attempts:{label:#} {value}{}{value:#}",
        response.attempts().len()
    )?;
    for (index, attempt) in response.attempts().enumerate() {
        let number = index.saturating_add(1);
        let status = attempt
            .status()
            .map_or_else(|| "unobserved".to_owned(), |value| value.to_string());
        let bytes = attempt
            .documents()
            .filter_map(|item| item.outcome().document())
            .map(DocumentRef::byte_len)
            .fold(0_u64, u64::saturating_add);
        writeln!(
            stderr,
            "{label}Attempt {number}:{label:#} {value}{}{value:#}, HTTP {status}, {bytes} document bytes",
            acquisition_label(attempt.acquisition())
        )?;
    }
    Ok(())
}

pub(super) fn human(
    response: &Response,
    profile: Option<&str>,
    identity: &EffectivePolicyIdentity,
) -> Result<()> {
    let theme = Theme::stdout();
    let label = theme.label;
    let value = theme.value;
    let muted = theme.muted;
    let success = theme.success;
    let error = theme.error;
    let warning = theme.warning;
    let mut stdout = io::stdout().lock();
    writeln!(
        stdout,
        "{label}Policy profile:{label:#} {value}{}{value:#}",
        profile.unwrap_or("<defaults>")
    )?;
    writeln!(
        stdout,
        "{muted}Policy identity: v{} {}{muted:#}",
        identity.version(),
        identity.digest()
    )?;
    writeln!(
        stdout,
        "{label}Termination:{label:#} {value}{}{value:#}",
        termination_label(response.termination())
    )?;
    for (index, attempt) in response.attempts().enumerate() {
        let number = index.saturating_add(1);
        let status = attempt
            .status()
            .map_or_else(|| "unobserved".to_owned(), |value| value.to_string());
        match attempt.state() {
            AttemptState::Completed => {
                writeln!(
                    stdout,
                    "{label}Attempt {number}:{label:#} {value}{}{value:#} {success}completed{success:#}, HTTP {status}",
                    acquisition_label(attempt.acquisition())
                )?;
                for document in attempt.documents() {
                    let outcome = document.outcome();
                    match document_detail(&outcome) {
                        Some(detail) => writeln!(
                            stdout,
                            "  {label}{}:{label:#} {value}{}{value:#} ({detail})",
                            document_label(document.requested()),
                            document_state(&outcome)
                        )?,
                        None => writeln!(
                            stdout,
                            "  {label}{}:{label:#} {value}{}{value:#}",
                            document_label(document.requested()),
                            document_state(&outcome)
                        )?,
                    }
                }
            }
            AttemptState::Failed(_) => {
                writeln!(
                    stdout,
                    "{label}Attempt {number}:{label:#} {value}{}{value:#} {error}failed{error:#}, HTTP {status}, {}",
                    acquisition_label(attempt.acquisition()),
                    attempt
                        .diagnostic()
                        .map_or_else(|| "unavailable".to_owned(), diagnostic_label)
                )?;
                if let Some(AttemptDiagnostic::BrowserFailure(reason)) = attempt.diagnostic()
                    && let Some(advice) =
                        browser_diagnostics::advice(browser_diagnostics::name(reason))
                {
                    writeln!(stdout, "  {error}{advice}{error:#}")?;
                    writeln!(
                        stdout,
                        "  {muted}Capture: {}{muted:#}",
                        attempt.capture_id()
                    )?;
                }
            }
            AttemptState::NotStarted(reason) => {
                writeln!(
                    stdout,
                    "{label}Attempt {number}:{label:#} {value}{}{value:#} {warning}not started{warning:#}, {:?}",
                    acquisition_label(attempt.acquisition()),
                    reason
                )?;
            }
        }
    }
    Ok(())
}

pub(super) fn json(
    response: &Response,
    profile: Option<&str>,
    identity: &EffectivePolicyIdentity,
) -> Result<()> {
    let attempts: Vec<_> = response
        .attempts()
        .enumerate()
        .map(|(index, attempt)| {
            let documents: Vec<_> = attempt
                .documents()
                .map(|item| {
                    let outcome = item.outcome();
                    json!({
                        "requested": document_label(item.requested()),
                        "state": document_state(&outcome),
                        "byte_len": outcome.document().map(DocumentRef::byte_len),
                        "detail": document_detail(&outcome),
                    })
                })
                .collect();
            let (state, diagnostic) = match attempt.state() {
                AttemptState::Completed => ("completed", None),
                AttemptState::Failed(_) => ("failed", attempt.diagnostic().map(diagnostic_label)),
                AttemptState::NotStarted(reason) => ("not_started", Some(format!("{reason:?}"))),
            };
            json!({
                "index": index.saturating_add(1),
                "acquisition": acquisition_label(attempt.acquisition()),
                "state": state,
                "http_status": attempt.status(),
                "diagnostic": diagnostic,
                "documents": documents,
            })
        })
        .collect();
    let envelope = json!({
        "schema_version": 1,
        "cli_version": env!("CARGO_PKG_VERSION"),
        "policy_profile": profile,
        "policy_identity": {
            "version": identity.version(),
            "sha256": identity.digest().to_string(),
        },
        "termination": termination_label(response.termination()),
        "attempts": attempts,
    });
    let mut stdout = io::stdout().lock();
    serde_json::to_writer(&mut stdout, &envelope).context("could not render request JSON")?;
    writeln!(stdout)?;
    Ok(())
}

pub(super) fn selected_document(
    response: &Response,
    attempt_number: Option<usize>,
    requested_document: Option<DocumentRequest>,
) -> Result<DocumentRef<'_>> {
    let mut attempts = response.attempts();
    let number = match attempt_number {
        Some(number) => number,
        None if attempts.len() == 1 => 1,
        None => bail!("raw output needs --attempt when the request has multiple acquisitions"),
    };
    let index = number
        .checked_sub(1)
        .ok_or_else(|| anyhow::anyhow!("--attempt is one-based"))?;
    let attempt = attempts
        .nth(index)
        .ok_or_else(|| anyhow::anyhow!("--attempt {number} is out of range"))?;
    if attempt.state() != AttemptState::Completed {
        bail!("attempt {number} did not complete");
    }
    let mut documents = attempt.documents();
    let outcome = match requested_document {
        Some(requested) => documents
            .find(|item| item.requested() == requested)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "attempt {number} did not request {}",
                    document_label(requested)
                )
            })?,
        None if documents.len() == 1 => documents
            .next()
            .ok_or_else(|| anyhow::anyhow!("attempt {number} has no documents"))?,
        None => bail!("raw output needs --document when the attempt has multiple documents"),
    };
    let DocumentOutcome::Produced(document) = outcome.outcome() else {
        bail!(
            "selected {} is not a complete produced Document: {}",
            document_label(outcome.requested()),
            document_state(&outcome.outcome())
        );
    };
    Ok(document)
}

pub(super) fn raw(document: DocumentRef<'_>) -> Result<()> {
    if document.bytes().len() > MAX_RAW_BYTES {
        bail!("selected Document exceeds the {MAX_RAW_BYTES} byte CLI raw-output limit");
    }
    io::stdout()
        .lock()
        .write_all(document.bytes())
        .context("could not write raw Document")?;
    Ok(())
}

pub(super) fn exit_code(response: &Response) -> ExitCode {
    if response.termination() == ResponseTermination::Cancelled {
        return ExitCode::from(130);
    }
    if has_incomplete(response) {
        return ExitCode::FAILURE;
    }
    ExitCode::SUCCESS
}

pub(super) fn has_incomplete(response: &Response) -> bool {
    response.attempts().any(|attempt| {
        attempt.state() != AttemptState::Completed
            || attempt
                .documents()
                .any(|item| !matches!(item.outcome(), DocumentOutcome::Produced(_)))
    })
}

const fn acquisition_label(kind: AcquisitionKind) -> &'static str {
    match kind {
        AcquisitionKind::DirectHttp => "direct_http",
        AcquisitionKind::Browser {
            mode: BrowserMode::Headless,
        } => "browser_headless",
        AcquisitionKind::Browser {
            mode: BrowserMode::Headful,
        } => "browser_headful",
    }
}

const fn document_label(requested: DocumentRequest) -> &'static str {
    match requested {
        DocumentRequest::ResponseDocument => "response",
        DocumentRequest::RenderedDom => "dom",
        DocumentRequest::AccessibilityTree => "ax",
        DocumentRequest::NetworkTree => "network",
    }
}

const fn document_state(outcome: &DocumentOutcome) -> &'static str {
    match outcome {
        DocumentOutcome::Produced(_) => "produced",
        DocumentOutcome::Partial { .. } => "partial",
        DocumentOutcome::Unavailable(_) => "unavailable",
        DocumentOutcome::Unprojectable(_) => "unprojectable",
    }
}

fn document_detail(outcome: &DocumentOutcome) -> Option<String> {
    match outcome {
        DocumentOutcome::Produced(_) => None,
        DocumentOutcome::Partial { reasons, .. } => Some(format!("{reasons:?}")),
        DocumentOutcome::Unavailable(reason) => Some(format!("{reason:?}")),
        DocumentOutcome::Unprojectable(reason) => Some(format!("{reason:?}")),
    }
}

const fn termination_label(termination: ResponseTermination) -> &'static str {
    match termination {
        ResponseTermination::Completed => "completed",
        ResponseTermination::Cancelled => "cancelled",
    }
}

fn diagnostic_label(diagnostic: AttemptDiagnostic) -> String {
    match diagnostic {
        AttemptDiagnostic::BrowserFailure(reason) => browser_diagnostics::name(reason).to_owned(),
        other => format!("{other:?}"),
    }
}
