//! Bounded presentation of public Requests outcomes.

use std::{
    io::{self, Write},
    process::ExitCode,
};

use anyhow::{Context as _, Result, bail};
use serde_json::json;
use yosoi::{
    AttemptOutcome, Document, DocumentOutcome, EffectivePolicyIdentity, Response,
    ResponseTermination,
    policy::{AcquisitionKind, BrowserMode, DocumentRequest},
};

use crate::stats::RunTimer;

const MAX_RAW_BYTES: usize = 16 * 1024 * 1024;

pub(super) fn stats(response: &Response, timer: &RunTimer) -> Result<()> {
    let mut stderr = io::stderr().lock();
    writeln!(stderr, "Request stats:")?;
    timer.write_wall_time(&mut stderr)?;
    writeln!(
        stderr,
        "Termination: {}",
        termination_label(response.termination())
    )?;
    writeln!(stderr, "Attempts: {}", response.attempts().len())?;
    for (index, attempt) in response.attempts().iter().enumerate() {
        let number = index.saturating_add(1);
        let status = attempt
            .status()
            .map_or_else(|| "unobserved".to_owned(), |value| value.to_string());
        let bytes: u64 = attempt
            .result()
            .map(|result| {
                result
                    .documents()
                    .iter()
                    .filter_map(|document| document.outcome().document())
                    .map(Document::byte_len)
                    .fold(0_u64, u64::saturating_add)
            })
            .unwrap_or_default();
        writeln!(
            stderr,
            "Attempt {number}: {}, HTTP {status}, {bytes} document bytes",
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
        termination_label(response.termination())
    )?;
    for (index, attempt) in response.attempts().iter().enumerate() {
        let number = index.saturating_add(1);
        let status = attempt
            .status()
            .map_or_else(|| "unobserved".to_owned(), |value| value.to_string());
        match attempt {
            AttemptOutcome::Completed(result) => {
                writeln!(
                    stdout,
                    "Attempt {number}: {} completed, HTTP {status}",
                    acquisition_label(attempt.acquisition())
                )?;
                for document in result.documents() {
                    let outcome = document.outcome();
                    match document_detail(outcome) {
                        Some(detail) => writeln!(
                            stdout,
                            "  {}: {} ({detail})",
                            document_label(document.requested()),
                            document_state(outcome)
                        )?,
                        None => writeln!(
                            stdout,
                            "  {}: {}",
                            document_label(document.requested()),
                            document_state(outcome)
                        )?,
                    }
                }
            }
            AttemptOutcome::Failed(failure) => {
                writeln!(
                    stdout,
                    "Attempt {number}: {} failed, HTTP {status}, {:?}",
                    acquisition_label(attempt.acquisition()),
                    failure.diagnostic()
                )?;
            }
            AttemptOutcome::NotStarted(not_started) => {
                writeln!(
                    stdout,
                    "Attempt {number}: {} not started, {:?}",
                    acquisition_label(attempt.acquisition()),
                    not_started.reason()
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
        .iter()
        .enumerate()
        .map(|(index, attempt)| {
            let documents: Vec<_> = attempt
                .result()
                .map(|result| {
                    result
                        .documents()
                        .iter()
                        .map(|document| {
                            json!({
                                "requested": document_label(document.requested()),
                                "state": document_state(document.outcome()),
                                "byte_len": document.outcome().document().map(yosoi::Document::byte_len),
                                "detail": document_detail(document.outcome()),
                            })
                        })
                        .collect()
                })
                .unwrap_or_default();
            let (state, diagnostic) = match attempt {
                AttemptOutcome::Completed(_) => ("completed", None),
                AttemptOutcome::Failed(failure) => ("failed", Some(format!("{:?}", failure.diagnostic()))),
                AttemptOutcome::NotStarted(not_started) => ("not_started", Some(format!("{:?}", not_started.reason()))),
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
) -> Result<&Document> {
    let attempts = response.attempts();
    let number = match attempt_number {
        Some(number) => number,
        None if attempts.len() == 1 => 1,
        None => bail!("raw output needs --attempt when the request has multiple acquisitions"),
    };
    let index = number
        .checked_sub(1)
        .ok_or_else(|| anyhow::anyhow!("--attempt is one-based"))?;
    let attempt = attempts
        .get(index)
        .ok_or_else(|| anyhow::anyhow!("--attempt {number} is out of range"))?;
    let result = attempt
        .result()
        .ok_or_else(|| anyhow::anyhow!("attempt {number} did not complete"))?;
    let documents = result.documents();
    let outcome = match requested_document {
        Some(requested) => documents
            .iter()
            .find(|item| item.requested() == requested)
            .ok_or_else(|| {
                anyhow::anyhow!(
                    "attempt {number} did not request {}",
                    document_label(requested)
                )
            })?,
        None if documents.len() == 1 => documents
            .first()
            .ok_or_else(|| anyhow::anyhow!("attempt {number} has no documents"))?,
        None => bail!("raw output needs --document when the attempt has multiple documents"),
    };
    let DocumentOutcome::Produced { document, .. } = outcome.outcome() else {
        bail!(
            "selected {} is not a complete produced Document: {}",
            document_label(outcome.requested()),
            document_state(outcome.outcome())
        );
    };
    Ok(document)
}

pub(super) fn raw(document: &Document) -> Result<()> {
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
    for attempt in response.attempts() {
        let Some(result) = attempt.result() else {
            return true;
        };
        if result
            .documents()
            .iter()
            .any(|document| !matches!(document.outcome(), DocumentOutcome::Produced { .. }))
        {
            return true;
        }
    }
    false
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
        DocumentOutcome::Produced { .. } => "produced",
        DocumentOutcome::Partial { .. } => "partial",
        DocumentOutcome::Unavailable { .. } => "unavailable",
        DocumentOutcome::Unprojectable { .. } => "unprojectable",
    }
}

fn document_detail(outcome: &DocumentOutcome) -> Option<String> {
    match outcome {
        DocumentOutcome::Produced { .. } => None,
        DocumentOutcome::Partial { reasons, .. } => Some(format!("{reasons:?}")),
        DocumentOutcome::Unavailable { reason } => Some(format!("{reason:?}")),
        DocumentOutcome::Unprojectable { reason } => Some(format!("{reason:?}")),
    }
}

const fn termination_label(termination: ResponseTermination) -> &'static str {
    match termination {
        ResponseTermination::Completed => "completed",
        ResponseTermination::Cancelled => "cancelled",
    }
}
