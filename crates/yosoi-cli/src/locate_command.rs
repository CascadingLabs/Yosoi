//! Locate over explicitly typed source input or a piped Yosoi Document.

use std::{
    fs::File,
    io::{self, IsTerminal as _, Read, Write},
    path::PathBuf,
    process::ExitCode,
};

use anyhow::{Context as _, Result, bail};
use clap::{Args, ValueEnum};
use serde::Serialize;
use yosoi::{Document, LocateOutcome, prelude as ys};

use crate::{document_pipe, policy_store::PolicyStore};

const MAX_RAW_INPUT_BYTES: usize = 67_108_864;
const MAX_OUTPUT_BYTES: usize = 16_777_216;

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum SourceChoice {
    Html,
    Xml,
    Json,
    Text,
}

#[derive(Debug, Args)]
pub struct LocateArgs {
    /// Read raw source bytes from a file.
    #[arg(long)]
    pub file: Option<PathBuf>,
    /// Read raw source bytes from stdin.
    #[arg(long)]
    pub stdin: bool,
    /// Read exactly one typed Yosoi Document frame from stdin.
    #[arg(long)]
    pub pipe_document: bool,
    /// Explicit format for raw file or stdin bytes.
    #[arg(long, value_enum)]
    pub format: Option<SourceChoice>,
    /// CSS selector projected as text.
    #[arg(long)]
    pub css: Option<String>,
    /// Literal text query projected as matched text.
    #[arg(long)]
    pub text: Option<String>,
    /// JSONPath query projected as values.
    #[arg(long)]
    pub json_path: Option<String>,
    /// JSON Pointer query projected as values.
    #[arg(long)]
    pub json_pointer: Option<String>,
    /// Emit a bounded machine-readable outcome envelope.
    #[arg(long)]
    pub json: bool,
}

pub fn run(args: &LocateArgs, profile: Option<&str>) -> Result<ExitCode> {
    let plan = plan(args)?;
    let store = PolicyStore::load()?;
    let selected = profile.or_else(|| store.active_profile());
    let policy = match selected {
        Some(name) => store.resolve_profile(name)?,
        None => store.current()?,
    };
    let document = read_document(args)?;
    let outcome = document.bind(&policy).locate(&plan);
    render(&document, &outcome, selected, args.json)?;
    Ok(exit_code(&outcome))
}

fn plan(args: &LocateArgs) -> Result<ys::Plan> {
    let query_count = [
        args.css.is_some(),
        args.text.is_some(),
        args.json_path.is_some(),
        args.json_pointer.is_some(),
    ]
    .into_iter()
    .filter(|specified| *specified)
    .count();
    if query_count != 1 {
        bail!("choose exactly one of --css, --text, --json-path, or --json-pointer");
    }
    let output_plan = if let Some(value) = &args.css {
        ys::css(value)?.text()
    } else if let Some(value) = &args.text {
        ys::text_literal(value)?.text()
    } else if let Some(value) = &args.json_path {
        ys::json_path(value)?.value()
    } else if let Some(value) = &args.json_pointer {
        ys::json_pointer(value)?.value()
    } else {
        bail!("a locator query is required");
    };
    ys::Plan::new([ys::output("match", output_plan)?]).context("invalid locator Plan")
}

fn read_document(args: &LocateArgs) -> Result<Document> {
    let input_count = usize::from(args.file.is_some())
        .saturating_add(usize::from(args.stdin))
        .saturating_add(usize::from(args.pipe_document));
    if input_count > 1 {
        bail!("choose exactly one of --file, --stdin, or --pipe-document");
    }
    if input_count == 0 && args.format.is_none() {
        if io::stdin().is_terminal() {
            bail!("provide --file, raw --format on stdin, or a typed Yosoi Document pipe");
        }
        return document_pipe::read_from(&mut io::stdin().lock())
            .context("stdin is not a typed Yosoi Document; raw bytes require --format");
    }
    if args.pipe_document {
        if args.format.is_some() {
            bail!("--format applies only to raw file or stdin input");
        }
        return document_pipe::read_from(&mut io::stdin().lock());
    }
    let format = args
        .format
        .ok_or_else(|| anyhow::anyhow!("raw input requires --format"))?;
    let (id, bytes) = if let Some(path) = &args.file {
        let file =
            File::open(path).with_context(|| format!("could not open {}", path.display()))?;
        (path.to_string_lossy().into_owned(), read_bounded(file)?)
    } else {
        ("stdin".to_owned(), read_bounded(io::stdin().lock())?)
    };
    match format {
        SourceChoice::Html => Document::html(id, bytes),
        SourceChoice::Xml => Document::xml(id, bytes),
        SourceChoice::Json => Document::json(id, bytes),
        SourceChoice::Text => Document::text(id, bytes),
    }
    .context("invalid source Document")
}

fn read_bounded(mut reader: impl Read) -> Result<Vec<u8>> {
    let mut bytes = Vec::new();
    reader
        .by_ref()
        .take(67_108_865)
        .read_to_end(&mut bytes)
        .context("could not read source input")?;
    if bytes.len() > MAX_RAW_INPUT_BYTES {
        bail!("raw input exceeds the {MAX_RAW_INPUT_BYTES} byte CLI limit");
    }
    Ok(bytes)
}

#[derive(Serialize)]
struct LocateEnvelope<'a> {
    schema_version: u32,
    cli_version: &'static str,
    policy_profile: Option<&'a str>,
    document_id: &'a ys::DocumentId,
    document_profile: ys::DocumentProfile,
    outcome: &'a LocateOutcome,
}

fn render(
    document: &Document,
    outcome: &LocateOutcome,
    profile: Option<&str>,
    machine: bool,
) -> Result<()> {
    let mut output = BoundedOutput::new();
    if machine {
        let envelope = LocateEnvelope {
            schema_version: 1,
            cli_version: env!("CARGO_PKG_VERSION"),
            policy_profile: profile,
            document_id: document.id(),
            document_profile: document.profile(),
            outcome,
        };
        let serialized = serde_json::to_writer(&mut output, &envelope);
        if output.exceeded {
            bail!("Locate output exceeds the {MAX_OUTPUT_BYTES} byte CLI limit");
        }
        serialized.context("could not render Locate outcome")?;
    } else {
        render_human(&mut output, document, outcome, profile)?;
    }
    if output.exceeded {
        bail!("Locate output exceeds the {MAX_OUTPUT_BYTES} byte CLI limit");
    }
    let mut stdout = io::stdout().lock();
    stdout.write_all(&output.bytes)?;
    writeln!(stdout)?;
    Ok(())
}

fn render_human(
    output: &mut impl Write,
    document: &Document,
    outcome: &LocateOutcome,
    profile: Option<&str>,
) -> Result<()> {
    writeln!(
        output,
        "Document: {} ({:?})",
        document.id(),
        document.class()
    )?;
    writeln!(
        output,
        "Policy profile: {}",
        profile.unwrap_or("<defaults>")
    )?;
    match outcome {
        LocateOutcome::Matched { result } => {
            writeln!(
                output,
                "Matched: {} finding(s), {} region(s)",
                result.findings().len(),
                result.regions().len()
            )?;
            for finding in result.findings() {
                writeln!(output, "  {}: {:?}", finding.output_id(), finding.value())?;
            }
        }
        LocateOutcome::NoMatch { .. } => writeln!(output, "No match")?,
        LocateOutcome::Indeterminate { reason_code, .. } => {
            writeln!(output, "Indeterminate: {reason_code}")?;
        }
        LocateOutcome::Failed { failure } => writeln!(output, "Locate failed: {failure:?}")?,
    }
    Ok(())
}

fn exit_code(outcome: &LocateOutcome) -> ExitCode {
    match outcome {
        LocateOutcome::Matched { .. } => ExitCode::SUCCESS,
        LocateOutcome::NoMatch { .. } => ExitCode::from(1),
        LocateOutcome::Indeterminate { .. } => ExitCode::from(2),
        LocateOutcome::Failed { .. } => ExitCode::from(3),
    }
}

struct BoundedOutput {
    bytes: Vec<u8>,
    exceeded: bool,
}

impl BoundedOutput {
    const fn new() -> Self {
        Self {
            bytes: Vec::new(),
            exceeded: false,
        }
    }
}

impl Write for BoundedOutput {
    fn write(&mut self, buffer: &[u8]) -> io::Result<usize> {
        if self.bytes.len().saturating_add(buffer.len()) > MAX_OUTPUT_BYTES {
            self.exceeded = true;
            return Err(io::Error::new(
                io::ErrorKind::WriteZero,
                "Locate output limit exceeded",
            ));
        }
        self.bytes.extend_from_slice(buffer);
        Ok(buffer.len())
    }

    fn flush(&mut self) -> io::Result<()> {
        Ok(())
    }
}

#[cfg(test)]
mod tests {
    #![allow(clippy::panic_in_result_fn)] // Assertions intentionally fail outcome tests.

    use std::{error::Error, process::ExitCode};

    use yosoi::{
        LocateOutcome,
        prelude::{DocumentId, IncompleteEvidence, LocateFailure},
    };

    use super::exit_code;

    #[test]
    fn indeterminate_and_failed_have_distinct_exit_codes() -> Result<(), Box<dyn Error>> {
        let document_id = DocumentId::try_new("partial")?;
        let indeterminate = LocateOutcome::Indeterminate {
            document_id,
            completeness: IncompleteEvidence::Unknown {
                reason_code: "unknown_loss".to_owned(),
            },
            reason_code: "incomplete_evidence".to_owned(),
        };
        let failed = LocateOutcome::Failed {
            failure: LocateFailure::ParseFailed {
                code: "bad_document".to_owned(),
            },
        };
        assert_eq!(exit_code(&indeterminate), ExitCode::from(2));
        assert_eq!(exit_code(&failed), ExitCode::from(3));
        Ok(())
    }
}
