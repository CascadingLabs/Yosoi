//! A curl-inspired terminal entry point over the public Requests facade.

use std::{
    io::{self, Write},
    process::ExitCode,
};

use anyhow::{Context as _, Result, bail};
use clap::{Args, ValueEnum};
use tokio::signal;
use yosoi::{
    CancellationToken, Policy, ResponseTermination,
    policy::{
        Acquisition, AddressableByteLimit, BrowserMode, DocumentRequest, MaximumElapsed, Page,
    },
    request,
};

use crate::{
    document_pipe,
    policy_store::PolicyStore,
    stats::RunTimer,
    stream_output::{Destination, cli_target, destination},
};

mod render;

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum AcquisitionChoice {
    Http,
    Headless,
    Headful,
}

impl AcquisitionChoice {
    const fn into_policy(self) -> Acquisition {
        match self {
            Self::Http => Acquisition::DirectHttp,
            Self::Headless => Acquisition::Browser(BrowserMode::Headless),
            Self::Headful => Acquisition::Browser(BrowserMode::Headful),
        }
    }
}

#[derive(Clone, Copy, Debug, ValueEnum)]
pub enum DocumentChoice {
    Response,
    Dom,
    Ax,
    Network,
}

impl DocumentChoice {
    const fn into_policy(self) -> DocumentRequest {
        match self {
            Self::Response => DocumentRequest::ResponseDocument,
            Self::Dom => DocumentRequest::RenderedDom,
            Self::Ax => DocumentRequest::AccessibilityTree,
            Self::Network => DocumentRequest::NetworkTree,
        }
    }
}

#[derive(Debug, Args)]
#[allow(clippy::struct_excessive_bools)] // Clap output modes are mutually exclusive flags.
pub struct RequestArgs {
    /// HTTP or HTTPS URL to request.
    pub url: String,
    /// Replace the Policy's ordered acquisitions. Repeat to run several.
    #[arg(short = 'a', long, value_enum)]
    pub acquisition: Vec<AcquisitionChoice>,
    /// Maximum elapsed time per attempt in milliseconds.
    #[arg(long)]
    pub timeout_ms: Option<u64>,
    /// Maximum admitted content-coded response bytes.
    #[arg(long)]
    pub content_coded_bytes: Option<u64>,
    /// Maximum retained decoded representation bytes.
    #[arg(long)]
    pub representation_bytes: Option<u64>,
    /// Maximum derived Unicode UTF-8 bytes.
    #[arg(long)]
    pub unicode_bytes: Option<u64>,
    /// Explain the validated Policy and exit before network I/O.
    #[arg(long, conflicts_with_all = ["json", "raw", "pipe_document"])]
    pub explain: bool,
    /// Emit a bounded machine-readable outcome summary without document bytes.
    #[arg(long, conflicts_with_all = ["raw", "pipe_document"])]
    pub json: bool,
    /// Emit one complete selected Document as raw bytes on stdout.
    #[arg(long, conflicts_with = "pipe_document")]
    pub raw: bool,
    /// Emit one selected typed Document for `yosoi locate --pipe-document`.
    #[arg(long)]
    pub pipe_document: bool,
    /// Show wall time and request outcome metadata on stderr.
    #[arg(short = 's', long = "stats", visible_alias = "stat")]
    pub stat: bool,
    /// One-based acquisition index for raw or typed Document output.
    #[arg(long)]
    pub attempt: Option<usize>,
    /// Document view for raw or typed Document output.
    #[arg(long, value_enum)]
    pub document: Option<DocumentChoice>,
}

#[derive(Clone, Copy, Debug, Eq, PartialEq)]
enum OutputMode {
    Explain,
    Json,
    Raw,
    Typed,
    Human,
}

pub async fn run(args: RequestArgs, profile: Option<&str>) -> Result<ExitCode> {
    let timer = RunTimer::start();
    let output_mode = output_mode(&args)?;
    let store = PolicyStore::load()?;
    let selected = profile.or_else(|| store.active_profile());
    let mut policy = match selected {
        Some(name) => store.resolve_profile(name)?,
        None => store.current()?,
    };
    apply_overrides(&args, &mut policy)?;
    policy
        .validate()
        .context("one-run Policy overrides are invalid")?;
    preflight_document_selection(&args, &policy, output_mode)?;
    let identity = policy
        .effective_identity()
        .context("could not compute effective Policy identity")?;
    let target = cli_target(&args.url);
    let request = request::new(target).bind(&policy);
    request.prepare().context("invalid request URL or Policy")?;

    if output_mode == OutputMode::Explain {
        let mut stdout = io::stdout().lock();
        writeln!(stdout, "CLI version: {}", env!("CARGO_PKG_VERSION"))?;
        writeln!(
            stdout,
            "Policy profile: {}",
            selected.unwrap_or("<defaults>")
        )?;
        writeln!(
            stdout,
            "Policy identity: v{} {}",
            identity.version(),
            identity.digest()
        )?;
        serde_json::to_writer_pretty(&mut stdout, &policy)
            .context("could not render effective Policy")?;
        writeln!(stdout)?;
        if args.stat {
            let mut stderr = io::stderr().lock();
            writeln!(stderr, "Request stats:")?;
            timer.write_wall_time(&mut stderr)?;
            writeln!(stderr, "Request: not sent (--explain)")?;
        }
        return Ok(ExitCode::SUCCESS);
    }

    let cancellation = CancellationToken::new();
    let send = request.send_cancellable(&cancellation);
    tokio::pin!(send);
    let response = tokio::select! {
        result = &mut send => result,
        signal = signal::ctrl_c() => {
            signal.context("could not listen for Ctrl-C")?;
            cancellation.cancel();
            send.await
        }
    }
    .context("request setup failed")?;
    if matches!(output_mode, OutputMode::Raw | OutputMode::Typed)
        && response.termination() == ResponseTermination::Cancelled
    {
        if args.stat {
            render::stats(&response, &timer)?;
        }
        writeln!(
            io::stderr().lock(),
            "yosoi: request cancelled; no Document emitted"
        )?;
        return Ok(ExitCode::from(130));
    }
    let output_result = (|| -> Result<()> {
        if matches!(output_mode, OutputMode::Raw | OutputMode::Typed) {
            let document = render::selected_document(
                &response,
                args.attempt,
                args.document.map(DocumentChoice::into_policy),
            )?;
            if output_mode == OutputMode::Raw {
                render::raw(document)?;
            } else {
                document_pipe::write_to(&mut io::stdout().lock(), document)?;
            }
            if render::has_incomplete(&response) {
                writeln!(
                    io::stderr().lock(),
                    "yosoi: selected Document emitted, but another requested outcome was incomplete or failed"
                )?;
            }
        } else if output_mode == OutputMode::Json {
            render::json(&response, selected, &identity)?;
        } else {
            render::human(&response, selected, &identity)?;
        }
        Ok(())
    })();
    if args.stat {
        render::stats(&response, &timer)?;
    }
    output_result?;
    Ok(render::exit_code(&response))
}

fn apply_overrides(args: &RequestArgs, policy: &mut Policy) -> Result<()> {
    if !args.acquisition.is_empty() {
        let acquisitions = args
            .acquisition
            .iter()
            .map(|item| item.into_policy())
            .collect();
        policy.page = Page::new(acquisitions).context("invalid acquisition override")?;
    }
    if let Some(milliseconds) = args.timeout_ms {
        let microseconds = milliseconds
            .checked_mul(1_000)
            .ok_or_else(|| anyhow::anyhow!("--timeout-ms is too large"))?;
        policy.request.maximum_elapsed =
            MaximumElapsed::try_from(microseconds).context("--timeout-ms must be positive")?;
    }
    if let Some(value) = args.content_coded_bytes {
        policy.request.source.content_coded_bytes = AddressableByteLimit::try_from(value)
            .context("--content-coded-bytes must be positive and addressable")?;
    }
    if let Some(value) = args.representation_bytes {
        policy.request.source.representation_bytes = AddressableByteLimit::try_from(value)
            .context("--representation-bytes must be positive and addressable")?;
    }
    if let Some(value) = args.unicode_bytes {
        policy.request.source.unicode_utf8_bytes = AddressableByteLimit::try_from(value)
            .context("--unicode-bytes must be positive and addressable")?;
    }
    Ok(())
}

fn preflight_document_selection(
    args: &RequestArgs,
    policy: &Policy,
    mode: OutputMode,
) -> Result<()> {
    if !matches!(mode, OutputMode::Raw | OutputMode::Typed) {
        if args.attempt.is_some() || args.document.is_some() {
            bail!("--attempt and --document require --raw or --pipe-document");
        }
        return Ok(());
    }
    let acquisitions = &policy.page.acquisitions;
    let number = match args.attempt {
        Some(number) => number,
        None if acquisitions.len() == 1 => 1,
        None if acquisitions.is_empty() => bail!("raw output needs a Policy acquisition"),
        None => bail!("raw output needs --attempt when the Policy has multiple acquisitions"),
    };
    let index = number
        .checked_sub(1)
        .ok_or_else(|| anyhow::anyhow!("--attempt is one-based and must be positive"))?;
    let acquisition = acquisitions
        .get(index)
        .ok_or_else(|| anyhow::anyhow!("--attempt {number} is out of range"))?;
    let default_document = [DocumentRequest::ResponseDocument];
    let documents = acquisition.exact_documents().unwrap_or(&default_document);
    match args.document {
        Some(requested) if documents.contains(&requested.into_policy()) => {}
        Some(_) => bail!("the selected acquisition does not request that Document view"),
        None if documents.len() == 1 => {}
        None => {
            bail!("raw output needs --document when the acquisition requests multiple Documents")
        }
    }
    Ok(())
}

fn output_mode(args: &RequestArgs) -> Result<OutputMode> {
    if args.explain {
        return Ok(OutputMode::Explain);
    }
    if args.json {
        return Ok(OutputMode::Json);
    }
    if args.raw {
        return Ok(OutputMode::Raw);
    }
    if args.pipe_document {
        return Ok(OutputMode::Typed);
    }
    match destination()? {
        Destination::Terminal => Ok(OutputMode::Human),
        Destination::Bytes => Ok(OutputMode::Raw),
        Destination::Document => Ok(OutputMode::Typed),
    }
}
