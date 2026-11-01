//! JSON-lines transport over the public Surface runtime.
use clap::{Args, Subcommand, ValueEnum};
use serde_json::{Value, json};
use std::{
    error::Error,
    io::{self, BufRead, Read},
    path::PathBuf,
    process::ExitCode,
    result::Result as StdResult,
    thread,
};
#[cfg(unix)]
use tokio::signal::unix::{SignalKind, signal as unix_signal};
use tokio::{
    fs::File as AsyncFile,
    io::{AsyncReadExt, AsyncWriteExt, Stdout, stdout},
    signal,
    sync::mpsc::{Receiver, channel},
};
use yosoi::documents::{Document, DocumentEpoch};
use yosoi::surface::{
    ArchivePolicy, DocumentPolicies, DocumentPolicy, Surface, SurfaceConnection, SurfacePolicy,
    archive as surface_archive,
    browser::{BrowserSurface, WebSurface, archive as browser_archive},
    model::{ReadRequest, SourceId, SurfaceRead},
    video::VideoSession,
};
type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;
#[derive(Debug, Args)]
pub struct SurfaceArgs {
    #[command(subcommand)]
    command: SurfaceCommand,
}
#[derive(Debug, Subcommand)]
enum SurfaceCommand {
    /// Read one immutable local Document through the shared SurfaceRead protocol.
    Document {
        /// Document profile used to interpret the file bytes.
        #[arg(long, value_enum)]
        format: DocumentFormat,
        /// Local file containing the exact retained document bytes.
        #[arg(long)]
        file: PathBuf,
        /// Immutable SDK Document identity.
        #[arg(long, default_value = "document")]
        id: String,
        /// Continuing source identity for the shared observation.
        #[arg(long, default_value = "local:document")]
        source: String,
        /// Positive document epoch required for rendered DOM and accessibility tree.
        #[arg(long)]
        epoch: Option<u64>,
        /// Maximum retained source bytes before preparation.
        #[arg(long, default_value_t = 8 * 1024 * 1024)]
        max_bytes: usize,
        /// Maximum prepared tree depth, counting root as zero.
        #[arg(long, default_value_t = 96)]
        max_depth: usize,
        /// Maximum indexed nodes.
        #[arg(long, default_value_t = 100_000)]
        max_nodes: usize,
        /// Maximum depth opened automatically in an overview.
        #[arg(long, default_value_t = 6)]
        overview_depth: usize,
        /// Maximum complete serialized shared-read result bytes.
        #[arg(long, default_value_t = 65_536)]
        response_bytes: usize,
    },
    /// Keep a browser alive; read JSON commands on stdin and emit JSON replies.
    #[command(alias = "drive")]
    Web {
        /// Initial HTTP(S) document to open in an isolated browser profile.
        #[arg(long)]
        url: String,
        /// Use regular Chromium headless mode instead of a visible browser.
        #[arg(long)]
        headless: bool,
        /// Local evidence directory; stores trace.json and rejected captures.
        #[arg(long, default_value = ".local/surface-session")]
        output: PathBuf,
        /// Enable archive policy, checkpoint each command, and export output/surface.yosoi on close.
        #[arg(long)]
        archive: Option<PathBuf>,
    },
    /// Explore an immutable local video through the shared bounded read protocol.
    Video {
        #[arg(long)]
        file: PathBuf,
        #[arg(long, default_value = ".local/surface-video")]
        output: PathBuf,
        #[arg(long)]
        archive: Option<PathBuf>,
        #[arg(long, default_value_t = 1920)]
        max_side: u32,
    },
    /// Rebuild and verify captured surfaces offline; never opens a browser.
    Replay {
        #[arg(long)]
        record: PathBuf,
        #[arg(long, default_value_t = 1)]
        repeat: usize,
        #[arg(long)]
        query: Option<String>,
        /// Optional output directory for archived video PNG evidence.
        #[arg(long)]
        output: Option<PathBuf>,
    },
    /// Repeat recorded click intentions with fresh references and a fresh session per iteration.
    Repeat {
        #[arg(long)]
        record: PathBuf,
        #[arg(long, default_value_t = 3)]
        count: usize,
        #[arg(long)]
        headless: bool,
        #[arg(long, default_value = ".local/surface-repeat")]
        output: PathBuf,
    },
    /// Export an existing handle or portable file as one immutable portable file.
    Export {
        #[arg(long)]
        record: PathBuf,
        #[arg(long)]
        file: PathBuf,
    },
}
#[derive(Clone, Copy, Debug, ValueEnum)]
#[value(rename_all = "kebab-case")]
enum DocumentFormat {
    Html,
    Xml,
    Json,
    Text,
    RenderedDom,
    AccessibilityTree,
}
async fn reply(output: &mut Stdout, id: Value, result: Result<Value>, budget: usize) -> Result<()> {
    let value = match result {
        Ok(result) => json!({"id":id,"ok":true,"result":result}),
        Err(error) => {
            json!({"id":id,"ok":false,"error":error.to_string().chars().take(512).collect::<String>()})
        }
    };
    let bytes = serde_json::to_vec(&value)?;
    let bytes = if bytes.len() > budget {
        serde_json::to_vec(
            &json!({"id":value.get("id"),"ok":false,"error":"response exceeds budget; use a continuation, smaller items, or a larger budget"}),
        )?
    } else {
        bytes
    };
    output.write_all(&bytes).await?;
    output.write_all(b"\n").await?;
    output.flush().await?;
    Ok(())
}
// Tokio stdin uses an uncancellable blocking pool read, which can hold its
// runtime open after SIGTERM. A single process-scoped reader thread owns no
// browser state; dropping its handle permits process exit even while stdin is open.
fn command_input() -> io::Result<Receiver<io::Result<Vec<u8>>>> {
    let (sender, receiver) = channel(1);
    thread::Builder::new()
        .name("surface-stdin".into())
        .spawn(move || {
            let input = io::stdin();
            let mut input = input.lock();
            loop {
                let mut bytes = Vec::new();
                let result = (&mut input).take(65537).read_until(b'\n', &mut bytes);
                let terminal = result.is_err() || bytes.is_empty() || bytes.len() > 65536;
                if sender.blocking_send(result.map(|_| bytes)).is_err() || terminal {
                    break;
                }
            }
        })?;
    Ok(receiver)
}
async fn interruption() -> io::Result<()> {
    #[cfg(unix)]
    {
        let mut terminated = unix_signal(SignalKind::terminate())?;
        tokio::select! {result = signal::ctrl_c()=>result, _ = terminated.recv()=>Ok(())}
    }
    #[cfg(not(unix))]
    signal::ctrl_c().await
}

async fn drive(mut surface: impl SurfaceConnection) -> Result<()> {
    let control = async {
        let mut output = stdout();
        reply(&mut output, Value::Null, surface.ready().map_err(Into::into), 4096).await?;
        let mut input = command_input()?;
        let interrupted = interruption();
        tokio::pin!(interrupted);
        loop {
            let bytes = tokio::select! { value = input.recv() => value.transpose()?, value = &mut interrupted => { value?; None } };
            let Some(bytes) = bytes else { break };
            if bytes.is_empty() { break; }
            if bytes.len() > 65536 { reply(&mut output, Value::Null, Err(io::Error::other("command exceeds 64 KiB; closing input").into()), 4096).await?; break; }
            let raw: Value = match serde_json::from_slice(&bytes) { Ok(value) => value, Err(error) => { reply(&mut output, Value::Null, Err(error.into()),4096).await?; continue; } };
            let id = raw.get("id").filter(|id| serde_json::to_vec(id).is_ok_and(|value|value.len()<=64)).cloned().unwrap_or(Value::Null);
            let budget = raw.get("budget").and_then(Value::as_u64).and_then(|value| usize::try_from(value).ok()).filter(|value| (1024..=16384).contains(value)).unwrap_or(4096);
            let close = raw.get("op").and_then(Value::as_str)==Some("close");
            let result = surface.execute(raw).await.map_err(Into::into);
            let accepted = result.is_ok();
            reply(&mut output,id,result,budget).await?;
            if close && accepted { break; }
        }
        Ok::<_, Box<dyn Error + Send + Sync>>(())
    }.await;
    let closed = surface.close().await;
    control?;
    closed?;
    Ok(())
}

fn document_value(
    reader: &impl SurfaceRead,
    operation: &str,
    raw: &Value,
    outer_budget: usize,
) -> Result<Value> {
    match operation {
        "describe" | "status" => Ok(serde_json::json!({
            "descriptor": reader.descriptor(),
            "observation": reader.observation(),
            "root": reader.root_reference(),
            "controllable": false,
        })),
        "read" => {
            let value = raw
                .get("request")
                .cloned()
                .ok_or_else(|| io::Error::other("read requires a shared SurfaceRead request"))?;
            let mut request: ReadRequest = serde_json::from_value(value)?;
            request.budget.bytes = request
                .budget
                .bytes
                .min(outer_budget.saturating_sub(256))
                .min(65_536);
            Ok(serde_json::to_value(reader.read(&request)?)?)
        }
        "close" => Ok(serde_json::json!({"closing": true})),
        _ => Err(io::Error::other(
            "immutable document reader supports describe and read only; use a live browser binding for actions",
        )
        .into()),
    }
}

async fn drive_document(reader: WebSurface) -> Result<()> {
    let ready = serde_json::json!({
        "event": "ready",
        "descriptor": reader.descriptor(),
        "observation": reader.observation(),
        "root": reader.root_reference(),
        "controllable": false,
        "protocol": "JSON lines; describe and read use the shared SurfaceRead contract",
    });
    let mut output = stdout();
    reply(&mut output, Value::Null, Ok(ready), 4096).await?;
    let mut input = command_input()?;
    let interrupted = interruption();
    tokio::pin!(interrupted);
    loop {
        let bytes = tokio::select! {
            value = input.recv() => value.transpose()?,
            value = &mut interrupted => { value?; None }
        };
        let Some(bytes) = bytes else { break };
        if bytes.is_empty() {
            break;
        }
        if bytes.len() > 65_536 {
            reply(
                &mut output,
                Value::Null,
                Err(io::Error::other("command exceeds 64 KiB; closing input").into()),
                4096,
            )
            .await?;
            break;
        }
        let raw: Value = match serde_json::from_slice(&bytes) {
            Ok(value) => value,
            Err(error) => {
                reply(&mut output, Value::Null, Err(error.into()), 4096).await?;
                continue;
            }
        };
        let id = raw
            .get("id")
            .filter(|id| serde_json::to_vec(id).is_ok_and(|value| value.len() <= 64))
            .cloned()
            .unwrap_or(Value::Null);
        let budget = raw
            .get("budget")
            .and_then(Value::as_u64)
            .and_then(|value| usize::try_from(value).ok())
            .filter(|value| (1024..=16_384).contains(value))
            .unwrap_or(4096);
        let operation = raw.get("op").and_then(Value::as_str).unwrap_or("");
        let close = operation == "close";
        let result = document_value(&reader, operation, &raw, budget);
        let accepted = result.is_ok();
        reply(&mut output, id, result, budget).await?;
        if close && accepted {
            break;
        }
    }
    Ok(())
}

async fn read_document(
    format: DocumentFormat,
    file: PathBuf,
    id: String,
    source: String,
    epoch: Option<u64>,
    policy: DocumentPolicy,
) -> Result<()> {
    const MAX_DOCUMENT_BYTES: usize = 128 * 1024 * 1024;
    let max_bytes = policy.max_bytes;
    if !(1..=MAX_DOCUMENT_BYTES).contains(&max_bytes) {
        return Err(io::Error::other("--max-bytes must be 1..134217728").into());
    }
    let input = AsyncFile::open(file).await?;
    let read_limit = max_bytes
        .checked_add(1)
        .ok_or_else(|| io::Error::other("--max-bytes overflowed"))?;
    let mut bytes = Vec::new();
    AsyncReadExt::take(input, u64::try_from(read_limit)?)
        .read_to_end(&mut bytes)
        .await?;
    if bytes.len() > max_bytes {
        return Err(io::Error::other("document exceeds --max-bytes").into());
    }
    let document = match format {
        DocumentFormat::Html => {
            reject_epoch(epoch)?;
            Document::html(id, bytes)?
        }
        DocumentFormat::Xml => {
            reject_epoch(epoch)?;
            Document::xml(id, bytes)?
        }
        DocumentFormat::Json => {
            reject_epoch(epoch)?;
            Document::json(id, bytes)?
        }
        DocumentFormat::Text => {
            reject_epoch(epoch)?;
            Document::text(id, bytes)?
        }
        DocumentFormat::RenderedDom => Document::rendered_dom(id, document_epoch(epoch)?, bytes)?,
        DocumentFormat::AccessibilityTree => {
            Document::accessibility_tree(id, document_epoch(epoch)?, bytes)?
        }
    };
    let policies = DocumentPolicies {
        dom: policy,
        ax: policy,
        html: policy,
        xml: policy,
        json: policy,
        text: policy,
        network: policy,
    };
    let index = Surface::with_policy(&document, &policies)?;
    let reader = WebSurface::with_policy(index, SourceId::new(source)?, policy)?;
    drive_document(reader).await
}

fn document_epoch(epoch: Option<u64>) -> Result<DocumentEpoch> {
    let value = epoch.ok_or_else(|| {
        io::Error::other("--epoch is required for rendered-dom and accessibility-tree")
    })?;
    Ok(DocumentEpoch::try_from(value)?)
}

fn reject_epoch(epoch: Option<u64>) -> Result<()> {
    if epoch.is_some() {
        return Err(io::Error::other(
            "--epoch applies only to rendered-dom and accessibility-tree",
        )
        .into());
    }
    Ok(())
}
fn policy(output: PathBuf, archive: Option<PathBuf>) -> SurfacePolicy {
    SurfacePolicy {
        output: Some(output),
        archive: if archive.is_some() {
            ArchivePolicy::Enabled
        } else {
            ArchivePolicy::Off
        },
        archive_root: archive,
        ..SurfacePolicy::default()
    }
}
pub async fn run(args: SurfaceArgs) -> anyhow::Result<ExitCode> {
    let result: Result<()> = match args.command {
        SurfaceCommand::Document {
            format,
            file,
            id,
            source,
            epoch,
            max_bytes,
            max_depth,
            max_nodes,
            overview_depth,
            response_bytes,
        } => {
            read_document(
                format,
                file,
                id,
                source,
                epoch,
                DocumentPolicy {
                    max_bytes,
                    max_depth,
                    max_nodes,
                    overview_depth,
                    response_bytes,
                },
            )
            .await
        }
        SurfaceCommand::Web {
            url,
            headless,
            output,
            archive,
        } => {
            Box::pin(drive(
                BrowserSurface::open(&url, policy(output, archive), headless).await?,
            ))
            .await
        }
        SurfaceCommand::Video {
            file,
            output,
            archive,
            max_side,
        } => drive(VideoSession::open(&file, policy(output, archive), max_side).await?).await,
        SurfaceCommand::Replay {
            record,
            repeat,
            query,
            output,
        } => {
            let value =
                surface_archive::replay(&record, repeat, query.as_deref(), output.as_deref())
                    .await?;
            println!("{}", serde_json::to_string(&value)?);
            Ok(())
        }
        SurfaceCommand::Export { record, file } => surface_archive::export(&record, &file)
            .await
            .map_err(Into::into),
        SurfaceCommand::Repeat {
            record,
            count,
            headless,
            output,
        } => {
            let temporary = tempfile::tempdir()?;
            let archive = yosoi::Archive::open(temporary.path()).await?;
            let reference = if record.extension().and_then(|value| value.to_str()) == Some("yosoi")
            {
                archive.import_file(&record).await?
            } else {
                let portable = temporary.path().join("legacy.yosoi");
                surface_archive::export(&record, &portable).await?;
                archive.import_file(portable).await?
            };
            let saved = archive.read(&reference).await?;
            let outcomes = browser_archive::rerun(
                &saved,
                policy(output.clone(), Some(output.join("archive"))),
                count,
                headless,
            )
            .await?;
            for (index, outcome) in outcomes.iter().enumerate() {
                println!(
                    "{}",
                    json!({"iteration":index.saturating_add(1),"mode":"live","fresh_session":true,"record":output.join(format!("run-{}",index.saturating_add(1))).join("record.json"),"portable_file":output.join(format!("run-{}",index.saturating_add(1))).join("surface.yosoi"),"record_id":outcome.record.id(),"confirmed_clicks":outcome.record.operations().iter().filter(|receipt|receipt.kind=="surface.command" && receipt.result.as_ref().and_then(|value|value.pointer("/command/op")).and_then(Value::as_str)==Some("click") && receipt.result.as_ref().and_then(|value|value.pointer("/outcome/receipt/status")).and_then(Value::as_str)==Some("Confirmed")).count(),"final_url":outcome.record.observations().last().and_then(|value|value.url.as_ref())})
                );
            }
            Ok(())
        }
    };
    result.map_err(|error| anyhow::anyhow!("{error}"))?;
    Ok(ExitCode::SUCCESS)
}
