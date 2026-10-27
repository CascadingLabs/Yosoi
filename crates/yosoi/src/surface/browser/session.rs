use super::archive::repeating;
use super::process::{Browser, ELEMENT};
use crate::surface::{
    ActionStatus, ArchivePolicy, Budget, Cursor, ExecutionError, Outcome, Reference, Session,
    SessionPolicy, SurfaceConnection, SurfacePolicy,
    archive::Recording,
    browser::WebSurface,
    connection::{
        AgentSurface, Connection, Expectation, Operation, Request, Result, Trace, connection,
    },
    model::{self, SurfaceRead},
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    error::Error,
    fmt::{self, Debug, Formatter},
    fs, io,
    result::Result as StdResult,
};
pub(super) struct Driver {
    pub(super) browser: Browser,
    pub(super) session: Session,
    pub(super) cursor: Cursor,
    pub(super) epoch: u64,
    pub(super) trace: Trace,
    pub(super) recording_fault: bool,
    pub(super) recording: Option<Recording>,
    pub(super) evidence: BTreeMap<super::BrowserRepresentation, WebSurface>,
}
impl Driver {
    pub(super) fn web_view(&self) -> Result<WebSurface> {
        Ok(WebSurface::with_policy(
            self.session.current()?,
            model::SourceId::new(format!("browser:{}", self.browser.session_key()))?,
            self.browser.documents.dom,
        )?)
    }
    pub(super) fn describe(&self) -> Result<Value> {
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
            json!({"descriptor":descriptor,"observation":view.observation(),"root":view.root_reference(),"representations":["dom","ax","network"],"documents":self.browser.documents}),
        )
    }
    pub(super) fn status(&self) -> Result<Value> {
        let current = self.session.current()?;
        Ok(
            json!({"capture":current.identity(),"root":current.root(),"nodes":current.node_count(),
            "cursor":self.cursor.status()?,"surface_read_bytes":self.trace.read_bytes,"recording":self.recording.as_ref().map_or_else(||json!({"mode":"off"}),Recording::status),"recording_fault":self.recording_fault,"controllable":true,"observation":"explicit captures; refresh to publish new evidence"}),
        )
    }
    pub(super) async fn refresh(&mut self) -> Result<Value> {
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(|| io::Error::other("capture epoch exhausted"))?;
        self.session
            .invalidate("explicit browser capture requested")?;
        let (surface, document, snapshot) =
            match self.browser.capture(self.epoch, &mut self.trace).await {
                Ok(value) => value,
                Err(error) => {
                    if let Some(recording) = &mut self.recording {
                        recording.fault();
                    }
                    return Err(error);
                }
            };
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
    pub(super) fn native_id(&self, reference: &Reference) -> Result<u64> {
        let surface = self.session.current()?;
        surface.validate(reference)?;
        let coordinate = surface.coordinate(reference)?;
        if coordinate.kind != "dom_node" {
            return Err(io::Error::other("reference is not a live DOM node").into());
        }
        Ok(coordinate.value.parse()?)
    }
    pub(super) async fn command(&mut self, request: &Request) -> Result<Value> {
        let budget = self.browser.documents.dom.budget(Budget {
            bytes: request.budget.saturating_sub(256),
            items: request.items.min(100),
        });
        let token = request.continuation.as_ref();
        match &request.operation {
            Operation::Describe => self.describe(),
            Operation::Observe { representation } => self.observe(*representation).await,
            Operation::ReadView {
                representation,
                request: read,
            } => {
                let view = if *representation == super::BrowserRepresentation::Dom {
                    self.web_view()?
                } else {
                    self.evidence.get(representation).cloned().ok_or_else(|| {
                        io::Error::other("observe this representation before reading it")
                    })?
                };
                let mut read = read.clone();
                read.budget.bytes = read.budget.bytes.min(request.budget.saturating_sub(256));
                Ok(serde_json::to_value(view.read(&read)?)?)
            }
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
    async fn observe(&mut self, representation: super::BrowserRepresentation) -> Result<Value> {
        if representation == super::BrowserRepresentation::Dom {
            self.refresh().await?;
            let view = self.web_view()?;
            return Ok(
                json!({"descriptor":view.descriptor(),"observation":view.observation(),"root":view.root_reference()}),
            );
        }
        self.epoch = self
            .epoch
            .checked_add(1)
            .ok_or_else(|| io::Error::other("capture epoch exhausted"))?;
        let (index, document, snapshot) = self
            .browser
            .capture_evidence(self.epoch, representation)
            .await?;
        let view = WebSurface::with_policy(
            index.clone(),
            model::SourceId::new(format!(
                "browser:{}:{representation:?}",
                self.browser.session_key()
            ))?,
            representation.policy(&self.browser.documents),
        )?;
        if let Some(recording) = &mut self.recording
            && let Err(error) = recording
                .capture(&document, &index, &snapshot, self.epoch)
                .await
        {
            self.recording_fault = true;
            recording.fault();
            self.session.detach()?;
            return Err(error);
        }
        let reply = json!({"descriptor":view.descriptor(),"observation":view.observation(),"root":view.root_reference()});
        self.evidence.insert(representation, view);
        Ok(reply)
    }
    pub(super) fn record_reply(
        &mut self,
        operation: &Operation,
        result: &Result<Value>,
    ) -> Result<()> {
        if matches!(
            operation,
            Operation::Read { .. }
                | Operation::ReadView { .. }
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
    pub(super) async fn persist_command(
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
    pub(super) async fn effect(
        &mut self,
        reference: &Reference,
        operation: &Operation,
    ) -> Result<Value> {
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
        }
        | Operation::Fill {
            target: Some(target),
            ..
        }
        | Operation::Key {
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
        if let Some(recording) = &mut self.recording
            && let Err(error) = recording.dispatch(serde_json::to_value(operation)?).await
        {
            self.recording_fault = true;
            self.session.detach()?;
            return Err(error);
        }
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
    pub(super) async fn execute(
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
                self.postcondition(expect.as_ref(), before).await
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
            Operation::Key { key, expect, .. } => {
                let element = element.ok_or_else(|| io::Error::other("key requires an element"))?;
                self.browser
                    .post(
                        &format!("/element/{element}/value"),
                        json!({"text":key_code(key)?}),
                    )
                    .await?;
                self.postcondition(expect.as_ref(), before).await
            }
            Operation::Scroll {
                delta_x,
                delta_y,
                expect,
                ..
            } => {
                self.browser.post("/actions",json!({"actions":[{"type":"wheel","id":"surface-wheel","actions":[{"type":"scroll","x":300,"y":300,"deltaX":delta_x,"deltaY":delta_y,"duration":0,"origin":"viewport"}]}]})).await?;
                self.postcondition(expect.as_ref(), before).await
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
    pub(super) async fn postcondition(
        &self,
        expect: Option<&Expectation>,
        before: &Value,
    ) -> Result<Value> {
        let expectation = match expect {
            Some(Expectation::Text { text, present }) => {
                json!({"kind":"text","text":text,"present":present})
            }
            Some(Expectation::Article) => json!({"kind":"article"}),
            Some(Expectation::Navigation) => json!({"kind":"navigation"}),
            None => {
                return Ok(
                    json!({"confirmed":false,"note":"native effect dispatched without an explicit postcondition"}),
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
pub(super) fn validate_url(value: &str) -> Result<()> {
    let url = url::Url::parse(value)?;
    if !matches!(url.scheme(), "http" | "https") {
        return Err(io::Error::other("URL must use HTTP(S)").into());
    }
    Ok(())
}
pub(super) fn validate_effect(operation: &Operation) -> Result<()> {
    if let Operation::Click {
        expect: Some(Expectation::Text { text, .. }),
        ..
    }
    | Operation::Key {
        expect: Some(Expectation::Text { text, .. }),
        ..
    }
    | Operation::Scroll {
        expect: Some(Expectation::Text { text, .. }),
        ..
    } = operation
        && (text.is_empty() || text.len() > 512)
    {
        return Err(io::Error::other("expected text must be 1..512 bytes").into());
    }
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
        _ => Ok(()),
    }
}

impl AgentSurface for Driver {
    fn outcome(&self) -> Option<Outcome> {
        self.recording.as_ref().map(Recording::outcome)
    }
    async fn close(mut self) -> (Option<Outcome>, Result<()>) {
        let detached = self.session.detach();
        let closed = self.browser.close().await;
        let archived = if let Some(recording) = &mut self.recording {
            recording.close(&closed).await
        } else {
            Ok(())
        };
        let outcome = self.recording.as_ref().map(Recording::outcome);
        (
            outcome,
            archived
                .and_then(|()| detached.map_err(Into::into))
                .and(closed),
        )
    }

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

/// An isolated live browser source, initially detached from observation and control.
/// Call `close` even after failure; cancellation does not prove an effect was undone.
pub struct BrowserSurface {
    inner: Connection<Driver>,
}
impl BrowserSurface {
    /// Captures fresh evidence without acquiring live action authority.
    /// AX is native and depth-limited; network covers a best-effort log window.
    /// Replacing a view invalidates its previous addresses, while other views
    /// remain immutable historical observations. DOM capture invalidates live targets.
    pub async fn observe(
        &mut self,
        representation: super::BrowserRepresentation,
    ) -> StdResult<super::BrowserObservation, ExecutionError> {
        let value = self
            .inner
            .execute(json!({"op":"observe","representation":representation}))
            .await?;
        serde_json::from_value(value).map_err(|e| ExecutionError::Operation(Box::new(e)))
    }
    /// Reads a previously observed representation under both caller and SDK policy bounds.
    /// Network and AX addresses cannot be used as DOM action references. Requests
    /// larger than the transport ceiling are reduced to 65280 result bytes.
    pub async fn read(
        &mut self,
        representation: super::BrowserRepresentation,
        mut request: model::ReadRequest,
    ) -> StdResult<model::ReadResult, ExecutionError> {
        request.budget.bytes = request.budget.bytes.min(65_280);
        let value = self.inner.execute(json!({"op":"read_view","representation":representation,"budget":request.budget.bytes.saturating_add(256).max(1024),"request":request})).await?;
        serde_json::from_value(value).map_err(|e| ExecutionError::Operation(Box::new(e)))
    }
    /// Opens a supported regular Chrome/Chromium source under explicit archive policy.
    /// `headless` selects this browser's display mode and is not a generic Surface policy.
    pub async fn open(
        url: &str,
        policy: SurfacePolicy,
        headless: bool,
    ) -> StdResult<Self, ExecutionError> {
        Self::open_inner(url, policy, headless)
            .await
            .map_err(super::archive::error)
    }
    async fn open_inner(url: &str, policy: SurfacePolicy, headless: bool) -> Result<Self> {
        validate_url(url)?;
        policy.archive_limits.validate()?;
        policy.documents.validate()?;
        let temporary = tempfile::tempdir()?;
        let output = policy
            .output
            .clone()
            .unwrap_or_else(|| temporary.path().join("artifacts"));
        fs::create_dir_all(&output)?;
        let mut trace = Trace::new(&output);
        let root = policy
            .archive_root
            .clone()
            .unwrap_or_else(|| temporary.path().join("archive"));
        let mut recording = if policy.archive == ArchivePolicy::Enabled {
            let mut recording = Recording::open(&root, &output, url).await?;
            recording.set_limits(policy.archive_limits);
            Some(recording)
        } else {
            None
        };
        let mut browser = match Browser::open_with_policy(headless, policy.documents).await {
            Ok(browser) => browser,
            Err(source) => {
                if let Some(recording) = &mut recording {
                    recording.fault();
                    let _ = recording
                        .command(
                            json!({"op":"open"}),
                            &Err(io::Error::other(source.to_string()).into()),
                        )
                        .await;
                    let _ = recording
                        .close(&Err(io::Error::other(
                            "browser initialization did not confirm cleanup",
                        )
                        .into()))
                        .await;
                    return Err(Box::new(repeating::RunFailure {
                        outcomes: vec![recording.outcome()],
                        source,
                    }));
                }
                return Err(source);
            }
        };
        let initial = async {
            browser.post("/url", json!({"url":url})).await?;
            let (surface, document, snapshot) = browser.capture(1, &mut trace).await?;
            if let Some(recording) = &mut recording {
                recording.capture(&document, &surface, &snapshot, 1).await?;
            }
            let session = Session::new(surface, SessionPolicy::default())?;
            let cursor = session.cursor()?;
            Ok::<_, Box<dyn Error + Send + Sync>>((session, cursor))
        }
        .await;
        let (session, cursor) = match initial {
            Ok(value) => value,
            Err(error) => {
                let closed = browser.close().await;
                if let Some(recording) = &mut recording {
                    recording.fault();
                    let _ = recording
                        .command(
                            json!({"op":"open"}),
                            &Err(io::Error::other(error.to_string()).into()),
                        )
                        .await;
                    let _ = recording.close(&closed).await;
                    return Err(Box::new(repeating::RunFailure {
                        outcomes: vec![recording.outcome()],
                        source: error,
                    }));
                }
                return Err(error);
            }
        };
        Ok(Self {
            inner: Connection::new(
                Driver {
                    browser,
                    session,
                    cursor,
                    epoch: 1,
                    trace,
                    recording_fault: false,
                    recording,
                    evidence: BTreeMap::new(),
                },
                output,
                temporary,
            ),
        })
    }
}
connection!(BrowserSurface);
