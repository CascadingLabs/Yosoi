//! Persistent, line-delimited JSON control for web and video surfaces.
mod adapter;
mod recording;
mod repeating;
mod video_cli;
use adapter::{Browser, ELEMENT, Result, Trace};
use clap::{Args, Subcommand};
use recording::Recording;
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    error::Error,
    fs,
    io::{self, BufRead, Read},
    path::{Path, PathBuf},
    process::ExitCode,
    thread,
};
use tokio::io::AsyncWriteExt;
use tokio::io::{Stdout, stdout};
use tokio::signal;
#[cfg(unix)]
use tokio::signal::unix::{SignalKind, signal as unix_signal};
use tokio::sync::mpsc::{Receiver, channel};
use yosoi::surface::{
    ActionStatus, Budget, Continuation, Cursor, PixelRect, Reference, Session, SessionPolicy,
    model::{self, SurfaceRead},
    web::WebSurface,
};

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
#[derive(Debug, Deserialize)]
struct Request {
    #[serde(default)]
    id: Value,
    #[serde(default = "default_budget")]
    budget: usize,
    #[serde(default = "default_items")]
    items: usize,
    #[serde(default)]
    continuation: Option<Continuation>,
    #[serde(flatten)]
    operation: Operation,
}
const fn default_budget() -> usize {
    4096
}
const fn default_items() -> usize {
    20
}
#[derive(Debug, Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
enum Operation {
    Describe,
    Read {
        request: model::ReadRequest,
    },
    FocusEvidence {
        reference: model::Reference,
    },
    Seek {
        position_us: u64,
    },
    Frame {
        reference: model::Reference,
    },
    Crop {
        reference: model::Reference,
        rect: PixelRect,
    },
    Status,
    Attach,
    Detach,
    Overview,
    Find {
        query: String,
    },
    Expand {
        reference: Reference,
    },
    Inspect {
        reference: Reference,
    },
    Parent {
        reference: Reference,
    },
    Focus {
        reference: Reference,
    },
    Hot,
    Cool,
    Refresh,
    Eligibility {
        reference: Reference,
    },
    Article,
    Screenshot,
    Wait {
        text: String,
        present: bool,
    },
    Click {
        reference: Reference,
        #[serde(default)]
        expect: Option<Expectation>,
        #[serde(default)]
        target: Option<Target>,
    },
    Fill {
        reference: Reference,
        text: String,
    },
    Key {
        reference: Reference,
        key: String,
    },
    Scroll {
        reference: Reference,
        delta_y: i32,
        #[serde(default)]
        delta_x: i32,
    },
    Navigate {
        reference: Reference,
        url: String,
    },
    Close,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
struct Target {
    query: String,
    tag: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
enum Expectation {
    Navigation,
    Article,
    Text { text: String, present: bool },
}
struct Driver {
    browser: Browser,
    session: Session,
    cursor: Cursor,
    epoch: u64,
    trace: Trace,
    recording_fault: bool,
    recording: Option<Recording>,
}
impl Driver {
    fn web_view(&self) -> Result<WebSurface> {
        Ok(WebSurface::new(
            self.session.current()?,
            model::SourceId::new(format!("browser:{}", self.browser.session_key()))?,
        )?)
    }
    fn describe(&self) -> Result<Value> {
        let view = self.web_view()?;
        let mut descriptor = view.descriptor().clone();
        descriptor.controllable = true;
        for name in ["click", "fill", "key", "scroll", "navigate"] {
            descriptor.capabilities.push(model::Capability {
                id: format!("web.{name}@1"),
                access: model::Access::Control,
                control_domain: Some(descriptor.source.as_str().into()),
                input_schema: format!("yosoi.web.{name}.v1"),
            });
        }
        Ok(
            json!({"descriptor":descriptor,"observation":view.observation(),"root":view.root_reference()}),
        )
    }
    fn status(&self) -> Result<Value> {
        let current = self.session.current()?;
        Ok(
            json!({"capture":current.identity(),"root":current.root(),"nodes":current.node_count(),
            "cursor":self.cursor.status()?,"surface_read_bytes":self.trace.read_bytes,"recording":self.recording.as_ref().map_or_else(||json!({"mode":"off"}),Recording::status),"recording_fault":self.recording_fault,"controllable":true,"observation":"explicit captures; refresh to publish new evidence"}),
        )
    }
    async fn refresh(&mut self) -> Result<Value> {
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(|| io::Error::other("capture epoch exhausted"))?;
        self.session
            .invalidate("explicit browser capture requested")?;
        let (surface, document, snapshot) =
            self.browser.capture(self.epoch, &mut self.trace).await?;
        if let Some(recording) = self.recording.as_mut()
            && let Err(error) = recording
                .capture(&document, &surface, &snapshot, self.epoch)
                .await
        {
            self.recording_fault = true;
            self.session.detach()?;
            return Err(error);
        }
        self.session.publish(surface)?;
        self.status()
    }
    fn native_id(&self, reference: &Reference) -> Result<u64> {
        let surface = self.session.current()?;
        surface.validate(reference)?;
        let coordinate = surface.coordinate(reference)?;
        if coordinate.kind != "dom_node" {
            return Err(io::Error::other("reference is not a live DOM node").into());
        }
        Ok(coordinate.value.parse()?)
    }
    async fn command(&mut self, request: &Request) -> Result<Value> {
        let budget = Budget {
            bytes: request.budget.saturating_sub(256),
            items: request.items.min(100),
        };
        let token = request.continuation.as_ref();
        match &request.operation {
            Operation::Describe => self.describe(),
            Operation::Read { request: read } => {
                let mut read = read.clone();
                read.budget.bytes = read.budget.bytes.min(request.budget.saturating_sub(256));
                Ok(serde_json::to_value(self.web_view()?.read(&read)?)?)
            }
            Operation::FocusEvidence { reference } => {
                let native = self.web_view()?.native_reference(reference)?;
                self.cursor.focus(&native)?;
                self.status()
            }
            Operation::Seek { .. } | Operation::Frame { .. } | Operation::Crop { .. } => Err(
                io::Error::other("web surface does not advertise video read capabilities").into(),
            ),
            Operation::Status => self.status(),
            Operation::Attach => {
                self.session.attach()?;
                self.status()
            }
            Operation::Detach => {
                self.session.detach()?;
                self.status()
            }
            Operation::Overview => Ok(serde_json::to_value(self.cursor.overview(token, budget)?)?),
            Operation::Find { query } => Ok(serde_json::to_value(
                self.cursor.find(query, token, budget)?,
            )?),
            Operation::Expand { reference } => Ok(serde_json::to_value(
                self.cursor.expand(reference, token, budget)?,
            )?),
            Operation::Inspect { reference } => Ok(serde_json::to_value(
                self.cursor.inspect(reference, token, budget)?,
            )?),
            Operation::Parent { reference } => Ok(serde_json::to_value(
                self.session.current()?.parent(reference)?,
            )?),
            Operation::Focus { reference } => {
                self.cursor.focus(reference)?;
                self.status()
            }
            Operation::Hot => {
                self.cursor.promote()?;
                self.status()
            }
            Operation::Cool => {
                self.cursor.cool()?;
                self.status()
            }
            Operation::Refresh => self.refresh().await,
            Operation::Wait { text, present } => {
                if text.is_empty() || text.len() > 512 {
                    return Err(io::Error::other("wait text must be 1..512 bytes").into());
                }
                if !self.cursor.status()?.live {
                    return Err(io::Error::other("attach before waiting on the live page").into());
                }
                let condition = self
                    .browser
                    .script(
                        "watch",
                        json!({"kind":"text","text":text,"present":present,"timeout_ms":15000}),
                    )
                    .await?;
                Ok(json!({"condition":condition,"observation":self.refresh().await?}))
            }
            Operation::Eligibility { reference } => {
                let id = self.native_id(reference)?;
                self.browser.script("eligibility", json!({"id":id})).await
            }
            Operation::Article => self.browser.script("article", json!({})).await,
            Operation::Screenshot => {
                self.browser
                    .screenshot(&self.trace.output, "surface")
                    .await?;
                Ok(json!({"path":self.trace.output.join("surface.png")}))
            }
            Operation::Click { reference, .. }
            | Operation::Fill { reference, .. }
            | Operation::Key { reference, .. }
            | Operation::Scroll { reference, .. }
            | Operation::Navigate { reference, .. } => {
                self.effect(reference, &request.operation).await
            }
            Operation::Close => Ok(json!({"closing":true})),
        }
    }
    fn record_reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()> {
        if matches!(
            operation,
            Operation::Read { .. }
                | Operation::Overview
                | Operation::Find { .. }
                | Operation::Expand { .. }
                | Operation::Inspect { .. }
        ) && let Ok(value) = result
        {
            self.trace.read_bytes = self
                .trace
                .read_bytes
                .saturating_add(serde_json::to_vec(value)?.len());
        }
        match result {
            Ok(value) => self.trace.event("cli.reply", value.clone()),
            Err(error) => self.trace.event(
                "cli.error",
                json!({"error":error.to_string().chars().take(512).collect::<String>()}),
            ),
        }
        Ok(())
    }
    async fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> Result<Value> {
        let persisted = if let Some(recording) = self.recording.as_mut() {
            recording
                .command(serde_json::to_value(operation)?, &result)
                .await
        } else {
            Ok(())
        };
        match persisted {
            Ok(()) => result,
            Err(error) => {
                self.recording_fault = true;
                self.session.detach()?;
                self.trace
                    .event("recording.failed", json!({"error":error.to_string()}));
                Err(error)
            }
        }
    }
    async fn effect(&mut self, reference: &Reference, operation: &Operation) -> Result<Value> {
        if self.recording_fault {
            return Err(io::Error::other(
                "recording failed; further effects are blocked in this session",
            )
            .into());
        }
        validate_effect(operation)?;
        if let Operation::Click {
            target: Some(target),
            ..
        } = operation
            && repeating::resolve(self, target).await? != *reference
        {
            return Err(io::Error::other(
                "recorded intention does not identify the selected reference",
            )
            .into());
        }
        let surface = self.session.current()?;
        surface.validate(reference)?;
        let page_action = matches!(
            operation,
            Operation::Scroll { .. } | Operation::Navigate { .. }
        );
        let id = if page_action {
            None
        } else {
            Some(self.native_id(reference)?)
        };
        let before = if let Some(id) = id {
            self.browser.script("eligibility", json!({"id":id})).await?
        } else {
            self.browser.script("binding", json!({})).await?
        };
        let fillable = !matches!(operation, Operation::Fill { .. })
            || (matches!(
                before.get("tag").and_then(Value::as_str),
                Some("input" | "textarea")
            ) && before.get("readonly") != Some(&Value::Bool(true)));
        let eligible = fillable
            && if page_action {
                before.get("current") == Some(&Value::Bool(true)) && *reference == surface.root()
            } else {
                before.get("eligible") == Some(&Value::Bool(true))
                    && before.get("unchanged") == Some(&Value::Bool(true))
            };
        self.cursor.focus(reference)?;
        // begin_action enforces attach + hot ownership; this never promotes implicitly.
        let mut lease = self.cursor.begin_action()?;
        if !eligible {
            let receipt=lease.finish(ActionStatus::Rejected,"live node, URL, captured target, or click point is no longer eligible; refresh and locate again")?;
            return Ok(json!({"receipt":receipt,"eligibility":before}));
        }
        let element = if let Some(id) = id {
            let element = self.browser.script("element", json!({"id":id})).await?;
            Some(
                element
                    .get(ELEMENT)
                    .and_then(Value::as_str)
                    .ok_or_else(|| io::Error::other("missing native element"))?
                    .to_owned(),
            )
        } else {
            None
        };
        let guard = if let Some(id) = id {
            self.browser.script("eligibility", json!({"id":id})).await?
        } else {
            self.browser.script("binding", json!({})).await?
        };
        let current = if page_action {
            guard.get("current") == Some(&Value::Bool(true))
        } else {
            guard.get("eligible") == Some(&Value::Bool(true))
                && guard.get("unchanged") == Some(&Value::Bool(true))
        };
        if !current {
            let receipt = lease.finish(
                ActionStatus::Rejected,
                "target changed during final live validation",
            )?;
            return Ok(json!({"receipt":receipt,"eligibility":guard}));
        }
        self.trace.event("action.revalidated", guard);
        lease.revalidate()?;
        lease.mark_dispatched()?;
        self.session
            .invalidate("native effect dispatched; outcome pending")?;
        let execution = self.execute(operation, element.as_deref(), &before).await;
        // Always attempt fresh evidence, including when native dispatch returned an error.
        let published = self.refresh().await;
        let confirmed = execution
            .as_ref()
            .is_ok_and(|outcome| outcome.get("confirmed") == Some(&Value::Bool(true)))
            && published.is_ok();
        let receipt = lease.finish(
            if confirmed {
                ActionStatus::Confirmed
            } else {
                ActionStatus::Unconfirmed
            },
            if confirmed {
                "explicit browser postcondition observed"
            } else {
                "effect dispatched; postcondition or fresh capture remains unconfirmed"
            },
        )?;
        let outcome = match execution {
            Ok(value) => value,
            Err(error) => json!({"error":error.to_string().chars().take(512).collect::<String>()}),
        };
        let observation = match published {
            Ok(_) => self.status()?,
            Err(error) => json!({"error":error.to_string().chars().take(512).collect::<String>()}),
        };
        let result = json!({"receipt":receipt,"outcome":outcome,"observation":observation});
        self.trace.event("action.receipt", result.clone());
        Ok(result)
    }
    async fn execute(
        &self,
        operation: &Operation,
        element: Option<&str>,
        before: &Value,
    ) -> Result<Value> {
        match operation {
            Operation::Click { expect, .. } => {
                let element =
                    element.ok_or_else(|| io::Error::other("click requires an element"))?;
                self.browser
                    .post(&format!("/element/{element}/click"), json!({}))
                    .await?;
                let expectation = match expect {
                    Some(Expectation::Text { text, present }) => {
                        json!({"kind":"text","text":text,"present":present})
                    }
                    Some(Expectation::Article) => json!({"kind":"article"}),
                    Some(Expectation::Navigation) => json!({"kind":"navigation"}),
                    None => {
                        return Ok(
                            json!({"confirmed":false,"note":"native click dispatched without an explicit postcondition"}),
                        );
                    }
                };
                let mut input = expectation;
                if let Some(fields) = input.as_object_mut() {
                    fields.insert(
                        "before_url".into(),
                        before.get("url").cloned().unwrap_or(Value::Null),
                    );
                    fields.insert(
                        "expected_url".into(),
                        before.get("href").cloned().unwrap_or(Value::Null),
                    );
                    fields.insert("timeout_ms".into(), json!(15000));
                }
                let observed = self.browser.script("watch", input).await?;
                Ok(
                    json!({"confirmed":observed.get("state").and_then(Value::as_str).is_some_and(|s|s!="timeout"),"postcondition":observed}),
                )
            }
            Operation::Fill { text, .. } => {
                let element =
                    element.ok_or_else(|| io::Error::other("fill requires an element"))?;
                self.browser
                    .post(&format!("/element/{element}/clear"), json!({}))
                    .await?;
                self.browser
                    .post(&format!("/element/{element}/value"), json!({"text":text}))
                    .await?;
                let observed = self
                    .browser
                    .script(
                        "value",
                        json!({"element":{(ELEMENT):element},"expected":text}),
                    )
                    .await?;
                Ok(
                    json!({"confirmed":observed.get("matches")==Some(&Value::Bool(true)),"value":observed}),
                )
            }
            Operation::Key { key, .. } => {
                let element = element.ok_or_else(|| io::Error::other("key requires an element"))?;
                self.browser
                    .post(
                        &format!("/element/{element}/value"),
                        json!({"text":key_code(key)?}),
                    )
                    .await?;
                Ok(
                    json!({"confirmed":false,"note":"key dispatched; inspect the resulting capture"}),
                )
            }
            Operation::Scroll {
                delta_x, delta_y, ..
            } => {
                self.browser.post("/actions",json!({"actions":[{"type":"wheel","id":"surface-wheel","actions":[{"type":"scroll","x":300,"y":300,"deltaX":delta_x,"deltaY":delta_y,"duration":0,"origin":"viewport"}]}]})).await?;
                Ok(
                    json!({"confirmed":false,"note":"wheel dispatched; inspect the resulting viewport"}),
                )
            }
            Operation::Navigate { url, .. } => {
                self.browser.post("/url", json!({"url":url})).await?;
                let observed = self.browser.script("location", json!({})).await?;
                Ok(
                    json!({"confirmed":observed.get("url").and_then(Value::as_str)==Some(url.as_str()),"location":observed}),
                )
            }
            _ => Err(io::Error::other("operation is not an effect").into()),
        }
    }
}
fn key_code(key: &str) -> Result<&'static str> {
    match key {
        "Enter" => Ok("\u{e007}"),
        "Tab" => Ok("\u{e004}"),
        "Escape" => Ok("\u{e00c}"),
        "Backspace" => Ok("\u{e003}"),
        _ => Err(io::Error::other("key must be Enter, Tab, Escape, or Backspace").into()),
    }
}
fn validate_url(value: &str) -> Result<()> {
    let url = url::Url::parse(value)?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(io::Error::other("URL must use HTTP(S)").into());
    }
    Ok(())
}
fn validate_effect(operation: &Operation) -> Result<()> {
    match operation {
        Operation::Navigate { url, .. } => validate_url(url),
        Operation::Key { key, .. } => {
            key_code(key)?;
            Ok(())
        }
        Operation::Scroll {
            delta_x, delta_y, ..
        } if delta_x.unsigned_abs() > 10000 || delta_y.unsigned_abs() > 10000 => {
            Err(io::Error::other("scroll deltas must be within 10000 pixels").into())
        }
        Operation::Click {
            expect: Some(Expectation::Text { text, .. }),
            ..
        } if text.is_empty() || text.len() > 512 => {
            Err(io::Error::other("expected text must be 1..512 bytes").into())
        }
        _ => Ok(()),
    }
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
async fn drive(
    url: &str,
    headless: bool,
    output_dir: PathBuf,
    archive: Option<PathBuf>,
) -> Result<()> {
    validate_url(url)?;
    fs::create_dir_all(&output_dir)?;
    let mut trace = Trace::new(&output_dir);
    let mut recording = match archive {
        Some(root) => Some(Recording::open(&root, &output_dir, url).await?),
        None => None,
    };
    let mut browser = Browser::open(headless).await?;
    let initialized = async {
        browser.post("/url", json!({"url":url})).await?;
        let (surface, document, snapshot) = browser.capture(1, &mut trace).await?;
        if let Some(recording) = recording.as_mut() {
            recording.capture(&document, &surface, &snapshot, 1).await?;
        }
        let session = Session::new(surface, SessionPolicy::default())?;
        let cursor = session.cursor()?;
        Ok::<_, Box<dyn Error + Send + Sync>>((session, cursor))
    }
    .await;
    let (session, cursor) = match initialized {
        Ok(value) => value,
        Err(error) => {
            let _ = browser.close().await;
            return Err(error);
        }
    };
    let mut driver = Driver {
        browser,
        session,
        cursor,
        epoch: 1,
        trace,
        recording_fault: false,
        recording,
    };
    let control = control_loop(&mut driver, &output_dir).await;
    let detached = driver.session.detach();
    let closed = driver.browser.close().await;
    let archived = if let Some(recording) = driver.recording.as_mut() {
        recording.close(&closed).await
    } else {
        Ok(())
    };
    control?;
    archived?;
    detached?;
    closed?;
    Ok(())
}
trait AgentSurface {
    fn ready(&mut self) -> Result<Value>;
    async fn command(&mut self, request: &Request) -> Result<Value>;
    fn record_reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()>;
    async fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> Result<Value>;
    fn trace(&mut self) -> &mut Trace;
}
impl AgentSurface for Driver {
    fn ready(&mut self) -> Result<Value> {
        self.trace.read(
            "surface.open",
            &self.cursor.overview(None, Budget::default())?,
        )?;
        Ok(
            json!({"event":"ready","sdk":"ys::surface","state":self.status()?,"browser":self.browser.capabilities.get("browserVersion"),"representation":"yosoi.web.document.v1","controllable":true,"protocol":"JSON lines; describe and read share the video protocol; close or EOF releases resources"}),
        )
    }
    async fn command(&mut self, request: &Request) -> Result<Value> {
        Self::command(self, request).await
    }
    fn record_reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()> {
        Self::record_reply(self, operation, result)
    }
    async fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> Result<Value> {
        Self::persist_command(self, operation, result).await
    }
    fn trace(&mut self) -> &mut Trace {
        &mut self.trace
    }
}
async fn control_loop<D: AgentSurface>(driver: &mut D, output_dir: &Path) -> Result<()> {
    let mut output = stdout();
    reply(&mut output, Value::Null, driver.ready(), 4096).await?;
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
        let request = match serde_json::from_value::<Request>(raw) {
            Ok(value) => value,
            Err(error) => {
                reply(&mut output, id, Err(error.into()), 4096).await?;
                continue;
            }
        };
        if !(1024..=16384).contains(&request.budget) || serde_json::to_vec(&request.id)?.len() > 64
        {
            reply(
                &mut output,
                Value::Null,
                Err(io::Error::other("budget must be 1024..16384; id must fit 64 bytes").into()),
                4096,
            )
            .await?;
            continue;
        }
        if request.budget < 4096
            && matches!(
                request.operation,
                Operation::Click { .. }
                    | Operation::Fill { .. }
                    | Operation::Key { .. }
                    | Operation::Scroll { .. }
                    | Operation::Navigate { .. }
            )
        {
            reply(
                &mut output,
                request.id,
                Err(
                    io::Error::other("effects require a reply budget of at least 4096 bytes")
                        .into(),
                ),
                request.budget,
            )
            .await?;
            continue;
        }
        let result = driver.command(&request).await;
        driver.record_reply(&request.operation, &result)?;
        let result = driver.persist_command(&request.operation, result).await;
        let trace = driver.trace();
        fs::write(
            output_dir.join("trace.json"),
            serde_json::to_vec_pretty(
                &json!({"sdk":"ys::surface","events":trace.events,"dropped_events":trace.dropped_events}),
            )?,
        )?;
        let close = matches!(request.operation, Operation::Close);
        reply(&mut output, request.id, result, request.budget).await?;
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
pub async fn run(args: SurfaceArgs) -> anyhow::Result<ExitCode> {
    let result = match args.command {
        SurfaceCommand::Web {
            url,
            headless,
            output,
            archive,
        } => drive(&url, headless, output, archive).await,
        SurfaceCommand::Video {
            file,
            output,
            archive,
            max_side,
        } => video_cli::drive(&file, output, archive, max_side).await,
        SurfaceCommand::Replay {
            record,
            repeat,
            query,
            output,
        } => match recording::replay(&record, repeat, query.as_deref(), output.as_deref()).await {
            Ok(value) => {
                println!("{}", serde_json::to_string(&value)?);
                Ok(())
            }
            Err(error) => Err(error),
        },
        SurfaceCommand::Repeat {
            record,
            count,
            headless,
            output,
        } => repeating::run(&record, count, headless, &output).await,
    };
    result.map_err(|error| anyhow::anyhow!("{error}"))?;
    Ok(ExitCode::SUCCESS)
}
