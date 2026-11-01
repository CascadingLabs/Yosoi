//! Bounded command protocol and state shared by source-specific connections.
use super::{Budget, Continuation, ExecutionError, Outcome, PixelRect, Reference, model};
use serde::{Deserialize, Serialize};
use serde_json::{Value, json};
use std::{
    collections::VecDeque,
    error::Error,
    fs,
    future::Future,
    io,
    path::{Path, PathBuf},
    result::Result as StdResult,
    time::Instant,
};
pub(super) type Result<T> = StdResult<T, Box<dyn Error + Send + Sync>>;
#[derive(Debug)]
pub(super) struct Trace {
    pub(super) start: Instant,
    pub(super) events: VecDeque<Value>,
    pub(super) read_bytes: usize,
    pub(super) dropped_events: usize,
    pub(super) output: PathBuf,
}
impl Trace {
    pub(super) fn new(output: &Path) -> Self {
        Self {
            start: Instant::now(),
            events: VecDeque::new(),
            read_bytes: 0,
            dropped_events: 0,
            output: output.to_owned(),
        }
    }
    pub(super) fn event(&mut self, operation: &str, evidence: Value) {
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
    pub(super) fn read(&mut self, operation: &str, value: &impl serde::Serialize) -> Result<()> {
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
pub(super) struct Request {
    #[serde(default)]
    pub(super) id: Value,
    #[serde(default = "default_budget")]
    pub(super) budget: usize,
    #[serde(default = "default_items")]
    pub(super) items: usize,
    #[serde(default)]
    pub(super) continuation: Option<Continuation>,
    #[serde(flatten)]
    pub(super) operation: Operation,
}
const fn default_budget() -> usize {
    4096
}
const fn default_items() -> usize {
    20
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "op", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Operation {
    Describe,
    Observe {
        representation: super::browser::BrowserRepresentation,
    },
    ReadView {
        representation: super::browser::BrowserRepresentation,
        request: model::ReadRequest,
    },
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
        #[serde(default)]
        target: Option<Target>,
    },
    Key {
        reference: Reference,
        key: String,
        #[serde(default)]
        target: Option<Target>,
        #[serde(default)]
        expect: Option<Expectation>,
    },
    Scroll {
        reference: Reference,
        delta_y: i32,
        #[serde(default)]
        delta_x: i32,
        #[serde(default)]
        expect: Option<Expectation>,
    },
    Navigate {
        reference: Reference,
        url: String,
    },
    Close,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(deny_unknown_fields)]
pub(super) struct Target {
    pub(super) query: String,
    pub(super) tag: String,
}
#[derive(Clone, Debug, Deserialize, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum Expectation {
    Navigation,
    Article,
    Text { text: String, present: bool },
}
pub(super) trait AgentSurface: Send {
    fn ready(&mut self) -> Result<Value>;
    fn command(&mut self, request: &Request) -> impl Future<Output = Result<Value>> + Send;
    fn record_reply(&mut self, operation: &Operation, result: &Result<Value>) -> Result<()>;
    fn persist_command(
        &mut self,
        operation: &Operation,
        result: Result<Value>,
    ) -> impl Future<Output = Result<Value>> + Send;
    fn trace(&mut self) -> &mut Trace;
    fn outcome(&self) -> Option<Outcome>;
    fn close(self) -> impl Future<Output = (Option<Outcome>, Result<()>)> + Send;
}

/// Common lifecycle for one bound source, without assuming its modality or OS.
/// Reading does not grant control; each source rejects unsupported capabilities.
pub trait SurfaceConnection: Send {
    /// Returns source capabilities and its initial bounded observation.
    fn ready(&mut self) -> StdResult<Value, ExecutionError>;
    /// Executes one bounded command. Dispatched effects are never assumed undone on error.
    fn execute(
        &mut self,
        command: Value,
    ) -> impl Future<Output = StdResult<Value, ExecutionError>> + Send;
    /// Returns retained evidence, including partial attempts, when archive policy is enabled.
    fn outcome(&self) -> Option<Outcome>;
    /// Awaits source-specific cleanup and preserves evidence even if cleanup fails.
    /// Repeated calls return the last retained outcome without reacquiring authority.
    fn close(&mut self) -> impl Future<Output = StdResult<Option<Outcome>, ExecutionError>> + Send;
}

pub(super) struct Connection<D> {
    driver: Option<D>,
    output: PathBuf,
    saved: Option<Outcome>,
    _temporary: tempfile::TempDir,
}
impl<D: AgentSurface> Connection<D> {
    pub(super) const fn new(driver: D, output: PathBuf, temporary: tempfile::TempDir) -> Self {
        Self {
            driver: Some(driver),
            output,
            saved: None,
            _temporary: temporary,
        }
    }
    pub(super) fn ready(&mut self) -> StdResult<Value, ExecutionError> {
        self.driver
            .as_mut()
            .ok_or_else(|| {
                ExecutionError::Operation(io::Error::other("surface connection is closed").into())
            })?
            .ready()
            .map_err(ExecutionError::Operation)
    }
    pub(super) async fn execute(&mut self, command: Value) -> StdResult<Value, ExecutionError> {
        self.execute_inner(command)
            .await
            .map_err(ExecutionError::Operation)
    }
    async fn execute_inner(&mut self, command: Value) -> Result<Value> {
        if serde_json::to_vec(&command)?.len() > 65536 {
            return Err(io::Error::other("command exceeds 64 KiB").into());
        }
        let request: Request = serde_json::from_value(command)?;
        if !(1024..=65536).contains(&request.budget) || serde_json::to_vec(&request.id)?.len() > 64
        {
            return Err(
                io::Error::other("budget must be 1024..65536; id must fit 64 bytes").into(),
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
        let driver = self
            .driver
            .as_mut()
            .ok_or_else(|| io::Error::other("surface connection is closed"))?;
        let result = driver.command(&request).await;
        driver.record_reply(&request.operation, &result)?;
        let result = driver.persist_command(&request.operation, result).await;
        let trace = driver.trace();
        fs::write(
            self.output.join("trace.json"),
            serde_json::to_vec_pretty(
                &json!({"sdk":"ys::surface","events":trace.events,"dropped_events":trace.dropped_events}),
            )?,
        )?;
        let value = result?;
        if serde_json::to_vec(&value)?.len() > request.budget.saturating_sub(128) {
            return Err(io::Error::other(
                "response exceeds budget; effects remain in the retained outcome",
            )
            .into());
        }
        Ok(value)
    }
    pub(super) fn outcome(&self) -> Option<Outcome> {
        self.driver
            .as_ref()
            .and_then(AgentSurface::outcome)
            .or_else(|| self.saved.clone())
    }
    pub(super) async fn close(&mut self) -> StdResult<Option<Outcome>, ExecutionError> {
        if let Some(driver) = self.driver.take() {
            let (outcome, result) = driver.close().await;
            self.saved = outcome;
            result.map_err(ExecutionError::Operation)?;
        }
        Ok(self.saved.clone())
    }
}
macro_rules! connection {
    ($name:ident) => {
        impl SurfaceConnection for $name {
            /// Returns source capabilities and the initial bounded observation.
            /// A closed connection returns an error instead of reopening its source.
            fn ready(&mut self) -> StdResult<Value, ExecutionError> {
                self.inner.ready()
            }
            /// Executes one bounded JSON command against this source.
            /// Errors after dispatch do not imply that effects were undone; inspect the retained outcome.
            async fn execute(&mut self, command: Value) -> StdResult<Value, ExecutionError> {
                self.inner.execute(command).await
            }
            /// Returns retained evidence, including partial attempts, when archive policy is enabled.
            fn outcome(&self) -> Option<Outcome> {
                self.inner.outcome()
            }
            /// Awaits source cleanup and retains its outcome even when cleanup fails.
            /// Repeated calls return the saved outcome without reacquiring control.
            async fn close(&mut self) -> StdResult<Option<Outcome>, ExecutionError> {
                self.inner.close().await
            }
        }
        impl Debug for $name {
            fn fmt(&self, f: &mut Formatter<'_>) -> fmt::Result {
                f.debug_struct(stringify!($name)).finish_non_exhaustive()
            }
        }
    };
}
pub(super) use connection;
