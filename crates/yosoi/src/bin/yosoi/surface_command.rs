//! JSON-lines terminal transport over the Surface executor.
use clap::{Args, Subcommand};
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
    io::{AsyncWriteExt, Stdout, stdout},
    signal,
    sync::mpsc::{Receiver, channel},
};
use yosoi::surface::{
    ArchivePolicy, SurfaceConnection, SurfacePolicy, archive as surface_archive,
    browser::{BrowserSurface, archive as browser_archive},
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
        /// Archive captures and receipts after each command using an explicit recording policy.
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
            &json!({"id":value.get("id"),"ok":false,"error":"response exceeds budget; use a continuation, smaller items, or a larger budget; effects are preserved in trace.json"}),
        )?
    } else {
        bytes
    };
    output.write_all(&bytes).await?;
    output.write_all(b"\n").await?;
    output.flush().await?;
    Ok(())
}
async fn control_loop(driver: &mut impl SurfaceConnection) -> Result<()> {
    let mut output = stdout();
    reply(
        &mut output,
        Value::Null,
        driver.ready().map_err(Into::into),
        4096,
    )
    .await?;
    let mut input = command_input()?;
    let interrupted = interruption();
    tokio::pin!(interrupted);
    loop {
        let bytes = tokio::select! {
            line = input.recv() => match line {Some(line)=>line?,None=>break},
            _ = &mut interrupted => break,
        };
        if bytes.is_empty() {
            break;
        }
        if bytes.len() > 65536 {
            reply(
                &mut output,
                Value::Null,
                Err(io::Error::other("command exceeds 64 KiB; closing input").into()),
                4096,
            )
            .await?;
            break;
        }
        let raw = serde_json::from_slice::<Value>(&bytes);
        let raw = match raw {
            Ok(value) => value,
            Err(error) => {
                reply(&mut output, Value::Null, Err(error.into()), 4096).await?;
                continue;
            }
        };
        let id = raw
            .get("id")
            .filter(|id| serde_json::to_vec(id).is_ok_and(|bytes| bytes.len() <= 64))
            .cloned()
            .unwrap_or(Value::Null);
        let budget = raw
            .get("budget")
            .and_then(Value::as_u64)
            .and_then(|n| usize::try_from(n).ok())
            .filter(|n| (1024..=16384).contains(n))
            .unwrap_or(4096);
        let close = raw.get("op").and_then(Value::as_str) == Some("close");
        let result = driver.execute(raw).await.map_err(Into::into);
        reply(&mut output, id, result, budget).await?;
        if close {
            break;
        }
    }
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
    let result = control_loop(&mut surface).await;
    let closed = surface.close().await;
    result?;
    closed?;
    Ok(())
}
const fn policy(output: PathBuf, archive: Option<PathBuf>) -> SurfacePolicy {
    SurfacePolicy {
        archive: if archive.is_some() {
            ArchivePolicy::Enabled
        } else {
            ArchivePolicy::Off
        },
        archive_root: archive,
        output: Some(output),
    }
}
pub async fn run(args: SurfaceArgs) -> anyhow::Result<ExitCode> {
    let result = match args.command {
        SurfaceCommand::Web {
            url,
            headless,
            output,
            archive,
        } => drive(BrowserSurface::open(&url, policy(output, archive), headless).await?).await,
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
        } => match surface_archive::replay(&record, repeat, query.as_deref(), output.as_deref())
            .await
        {
            Ok(value) => {
                println!("{}", serde_json::to_string(&value)?);
                Ok(())
            }
            Err(error) => Err(error.into()),
        },
        SurfaceCommand::Repeat {
            record,
            count,
            headless,
            output,
        } => {
            browser_archive::repeat(&record, count, headless, &output, |result| {
                println!("{result}");
            })
            .await?;
            Ok(())
        }
    };
    result.map_err(|error| anyhow::anyhow!("{error}"))?;
    Ok(ExitCode::SUCCESS)
}
