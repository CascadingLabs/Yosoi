//! Provider execution shared by SDK callers and the JSON-lines CLI.
mod adapter;
mod recording;
mod repeating;
mod video;
mod web;
use crate::surface::{Budget, Continuation, PixelRect, Reference, model};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::VecDeque,
    error::Error,
    fmt::{self, Debug, Formatter},
    fs, io,
    path::{Path, PathBuf},
    result::Result as StdResult,
    time::Instant,
};
use web::{Driver, open_web};
type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;
#[derive(Debug)]
struct Trace {
    start: Instant,
    events: VecDeque<Value>,
    read_bytes: usize,
    dropped_events: usize,
    output: PathBuf,
}
impl Trace {
    fn reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()> {
        if matches!(
            operation,
            Operation::Read { .. }
                | Operation::Overview
                | Operation::Find { .. }
                | Operation::Expand { .. }
                | Operation::Inspect { .. }
        ) && let Ok(value) = result
        {
            self.read_bytes = self
                .read_bytes
                .saturating_add(serde_json::to_vec(value)?.len());
        }
        match result {
            Ok(value) => self.event("cli.reply", value.clone()),
            Err(error) => self.event(
                "cli.error",
                json!({"error":error.to_string().chars().take(512).collect::<String>()}),
            ),
        }
        Ok(())
    }

    fn new(output: &Path) -> Self {
        Self {
            start: Instant::now(),
            events: VecDeque::new(),
            read_bytes: 0,
            dropped_events: 0,
            output: output.to_owned(),
        }
    }
    fn event(&mut self, operation: &str, evidence: Value) {
        let mut event = json!({"at_ms":self.start.elapsed().as_millis(),"operation":operation});
        if let Some(fields) = event.as_object_mut() {
            fields.insert("evidence".into(), evidence);
        }
        if self.events.len() >= 1024 {
            self.events.pop_front();
            self.dropped_events = self.dropped_events.saturating_add(1);
        }
        self.events.push_back(event);
    }
    fn read(&mut self, operation: &str, value: &impl serde::Serialize) -> Result<()> {
        let bytes = serde_json::to_vec(value)?.len();
        if bytes > Budget::default().bytes {
            return Err(io::Error::other("SDK read exceeded its byte budget").into());
        }
        self.read_bytes = self.read_bytes.saturating_add(bytes);
        self.event(operation, json!({"response_bytes":bytes,"response":value}));
        Ok(())
    }
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
trait AgentSurface {
    fn ready(&mut self) -> Result<Value>;
    async fn command(&mut self, request: &Request) -> Result<Value>;
    async fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> Result<Value>;
    fn trace(&mut self) -> &mut Trace;
}
/// Execution or provider failure; an effect may already have occurred.
#[derive(Debug, thiserror::Error)]
#[error("surface runtime: {0}")]
pub struct RuntimeError(#[source] Box<dyn Error + Send + Sync>);

// Concrete providers retain their own authority and lifecycle. Adding a modality
// does not extend the document index or make every source controllable.
enum Provider {
    Web(Box<Driver>),
    Video(Box<video::VideoDriver>),
}

/// Stateful executor independent of terminal input, output, and OS signals.
///
/// Each web runtime owns an isolated browser, initially detached. Video remains
/// read-only. Call `close` even after a failed command to await provider cleanup.
/// Cancellation after dispatch does not prove that an external effect stopped.
/// Commands use the documented Surface JSON protocol; captured references never
/// restore action authority. Requires the `surface-runtime` feature.
pub struct Runtime {
    provider: Option<Provider>,
    output: PathBuf,
}
impl Debug for Runtime {
    fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
        f.debug_struct("SurfaceRuntime")
            .field("closed", &self.provider.is_none())
            .finish_non_exhaustive()
    }
}
impl Runtime {
    /// Opens a web source using installed regular Stable Chrome and ChromeDriver.
    /// Optional Archive storage checkpoints captures and command receipts.
    pub async fn open_web(
        url: &str,
        headless: bool,
        output: PathBuf,
        archive: Option<PathBuf>,
    ) -> StdResult<Self, RuntimeError> {
        let driver = open_web(url, headless, output.clone(), archive)
            .await
            .map_err(RuntimeError)?;
        Ok(Self {
            provider: Some(Provider::Web(Box::new(driver))),
            output,
        })
    }
    /// Freezes a local video source and opens bounded read-only navigation.
    /// `max_side` bounds decoded frame dimensions; Archive storage is optional.
    pub async fn open_video(
        file: &Path,
        output: PathBuf,
        archive: Option<PathBuf>,
        max_side: u32,
    ) -> StdResult<Self, RuntimeError> {
        let driver = video::open(file, output.clone(), archive, max_side)
            .await
            .map_err(RuntimeError)?;
        Ok(Self {
            provider: Some(Provider::Video(Box::new(driver))),
            output,
        })
    }
    /// Returns provider metadata and the initial bounded observation.
    pub fn ready(&mut self) -> StdResult<Value, RuntimeError> {
        match self.provider.as_mut() {
            Some(Provider::Web(driver)) => driver.ready(),
            Some(Provider::Video(driver)) => driver.ready(),
            None => Err(io::Error::other("surface runtime is closed").into()),
        }
        .map_err(RuntimeError)
    }
    /// Validates and executes one JSON command, preserving receipts and trace.
    /// Returns an error on invalid input, unsupported capabilities or execution
    /// failure. Errors do not imply rollback; inspect the saved trace/receipts.
    /// The terminal transport alone wraps the result with its request ID.
    pub async fn execute(&mut self, command: Value) -> StdResult<Value, RuntimeError> {
        self.execute_inner(command).await.map_err(RuntimeError)
    }
    async fn execute_inner(&mut self, command: Value) -> Result<Value> {
        if serde_json::to_vec(&command)?.len() > 65536 {
            return Err(io::Error::other("command exceeds 64 KiB").into());
        }
        let request: Request = serde_json::from_value(command)?;
        if !(1024..=16384).contains(&request.budget) || serde_json::to_vec(&request.id)?.len() > 64
        {
            return Err(
                io::Error::other("budget must be 1024..16384; id must fit 64 bytes").into(),
            );
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
            return Err(
                io::Error::other("effects require a reply budget of at least 4096 bytes").into(),
            );
        }
        match self.provider.as_mut() {
            Some(Provider::Web(driver)) => execute(driver.as_mut(), &request, &self.output).await,
            Some(Provider::Video(driver)) => execute(driver.as_mut(), &request, &self.output).await,
            None => Err(io::Error::other("surface runtime is closed").into()),
        }
    }
    /// Releases subscriptions/authority, closes the browser and checkpoints the
    /// optional Archive. Safe to call again after completion. A failure does not
    /// invent successful cleanup or discard previously captured receipts.
    pub async fn close(&mut self) -> StdResult<(), RuntimeError> {
        let result = match self.provider.take() {
            Some(Provider::Web(mut driver)) => driver.close().await,
            Some(Provider::Video(mut driver)) => driver.close().await,
            None => Ok(()),
        };
        result.map_err(RuntimeError)
    }
    /// Verifies captured observations offline without starting a browser.
    /// Video replay uses saved PNG evidence and does not start a decoder.
    pub async fn replay(
        record: &Path,
        repeat: usize,
        query: Option<&str>,
        output: Option<&Path>,
    ) -> StdResult<Value, RuntimeError> {
        recording::replay(record, repeat, query, output)
            .await
            .map_err(RuntimeError)
    }
    /// Resolves recorded click intentions in a fresh browser for each iteration.
    /// Ambiguous, incomplete or ineligible targets fail before dispatch.
    /// Calls `on_iteration` after each confirmed iteration, retaining progress
    /// when a later iteration fails. The callback must not block or panic.
    pub async fn repeat(
        record: &Path,
        count: usize,
        headless: bool,
        output: &Path,
        on_iteration: impl FnMut(Value),
    ) -> StdResult<(), RuntimeError> {
        repeating::run(record, count, headless, output, on_iteration)
            .await
            .map_err(RuntimeError)
    }
}
async fn execute(
    driver: &mut impl AgentSurface,
    request: &Request,
    output: &Path,
) -> Result<Value> {
    let result = driver.command(request).await;
    driver.trace().reply(&request.operation, &result)?;
    let result = driver.persist_command(&request.operation, result).await;
    let trace = driver.trace();
    fs::write(
        output.join("trace.json"),
        serde_json::to_vec_pretty(
            &json!({"sdk":"ys::surface","events":trace.events,"dropped_events":trace.dropped_events}),
        )?,
    )?;
    result
}
