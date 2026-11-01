use super::archive::repeating;
use super::{backend::Browser, process::ELEMENT};
use crate::documents::{Document, FileDocument, FileLimits, FileMetadata, file_from_bytes};
use crate::session::{Session as NativeSession, Tab, Work};
use crate::surface::{
    ActionStatus, ArchivePolicy, ArchivedSource, Budget, Cursor, ExecutionError, NetworkPayload,
    NetworkPayloadKind, NetworkPayloadRef, NetworkPayloadState, NetworkPayloadValue,
    NetworkSubscription, NetworkWindow, Outcome, Reference, Session, SessionPolicy,
    SurfaceConnection, SurfacePolicy,
    archive::Recording,
    browser::WebSurface,
    connection::{
        AgentSurface, Connection, Expectation, Operation, Request, Result, Trace, connection,
    },
    model::{self, SurfaceRead},
};
use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use sha2::{Digest, Sha256};
use std::{
    collections::{BTreeMap, VecDeque},
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
    pub(super) network_evidence: VecDeque<WebSurface>,
    pub(super) network_evidence_limit: usize,
}

fn request_observation(request: &model::ReadRequest) -> Option<String> {
    let reference = match &request.operation {
        model::ReadOperation::Expand { reference }
        | model::ReadOperation::Inspect { reference }
        | model::ReadOperation::Parent { reference } => Some(reference),
        model::ReadOperation::Overview | model::ReadOperation::Search { .. } => None,
    };
    reference
        .map(|reference| reference.observation.as_str().to_owned())
        .or_else(|| {
            request
                .continuation
                .as_ref()
                .and_then(|token| serde_json::from_str::<Value>(token.as_str()).ok())
                .and_then(|value| {
                    value
                        .get("observation")
                        .and_then(Value::as_str)
                        .map(str::to_owned)
                })
        })
}

fn retained_network_payloads(
    browser: &Browser,
    snapshot: &Value,
) -> Result<
    Vec<(
        crate::surface::NetworkPayloadRef,
        crate::surface::NetworkPayload,
    )>,
> {
    let Some(payloads) = snapshot
        .pointer("/network/payloads")
        .and_then(Value::as_array)
    else {
        return Ok(Vec::new());
    };
    let mut retained = Vec::new();
    for value in payloads {
        let reference: crate::surface::NetworkPayloadRef = serde_json::from_value(value.clone())?;
        if !matches!(
            reference.state,
            crate::surface::NetworkPayloadState::Retained
                | crate::surface::NetworkPayloadState::Truncated
        ) {
            continue;
        }
        let Some((retained_reference, value)) = browser.retained_network_payload(&reference.id)
        else {
            return Err(
                io::Error::other("network payload reference has no retained body value").into(),
            );
        };
        if retained_reference != reference {
            return Err(io::Error::other(
                "network payload metadata differs from the retained body value",
            )
            .into());
        }
        retained.push((reference.clone(), NetworkPayload { reference, value }));
    }
    Ok(retained)
}

impl Driver {
    pub(super) fn web_view(&self) -> Result<WebSurface> {
        Ok(WebSurface::with_policy(
            self.session.current()?,
            model::SourceId::new(format!("browser:{}", self.browser.session_key()))?,
            self.browser.documents.dom,
        )?)
    }
    fn network_view(&self, request: &model::ReadRequest) -> Result<WebSurface> {
        let requested = request_observation(request);
        if let Some(observation) = requested {
            if let Some(view) = self
                .network_evidence
                .iter()
                .find(|view| view.observation().id.as_str() == observation.as_str())
            {
                return Ok(view.clone());
            }
            return Err(
                io::Error::other("network observation was evicted or never captured").into(),
            );
        }
        self.network_evidence
            .back()
            .cloned()
            .ok_or_else(|| io::Error::other("observe network evidence before reading it").into())
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
        if self.browser.native().is_some() {
            descriptor.capabilities.push(model::Capability {
                id: "web.network.observe@1".into(),
                access: model::Access::Read,
                control_domain: None,
                input_schema: "yosoi.web.network-window.v1".into(),
            });
        }
        Ok(
            json!({"descriptor":descriptor,"observation":view.observation(),"root":view.root_reference(),"representations":if self.browser.native().is_some() { vec!["dom","ax","network"] } else { vec!["dom"] },"documents":self.browser.documents,"source":self.browser.capabilities}),
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
                .capture(&document, &surface, &snapshot, self.epoch, &[])
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
                let view = match representation {
                    super::BrowserRepresentation::Dom => self.web_view()?,
                    super::BrowserRepresentation::Network => self.network_view(read)?,
                    _ => self.evidence.get(representation).cloned().ok_or_else(|| {
                        io::Error::other("observe this representation before reading it")
                    })?,
                };
                let mut read = read.clone();
                read.budget.bytes = read.budget.bytes.min(request.budget.saturating_sub(256));
                Ok(serde_json::to_value(view.read(&read)?)?)
            }
            Operation::NetworkSubscribe { retain_bodies } => {
                self.browser.subscribe_network(*retain_bodies).await
            }
            Operation::NetworkCancel => self.browser.cancel_network().await,
            Operation::NetworkWait {
                after_sequence,
                timeout_ms,
            } => {
                self.browser
                    .wait_network_event(*after_sequence, *timeout_ms)
                    .await
            }
            Operation::NetworkPayload {
                reference,
                offset,
                max_bytes,
            } => {
                let transport_limit = request.budget.saturating_sub(512).saturating_mul(3) / 4;
                let max_bytes = (*max_bytes).min(transport_limit).clamp(1, 32_768);
                self.browser
                    .read_network_payload(reference, *offset, max_bytes)
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
            Operation::Seek { .. }
            | Operation::Frame { .. }
            | Operation::Crop { .. }
            | Operation::ImageDirect
            | Operation::OverviewImage { .. }
            | Operation::ResizeImage { .. }
            | Operation::CropImage { .. } => Err(io::Error::other(
                "web surface does not advertise pixel materialization capabilities",
            )
            .into()),
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
                let artifact = self.browser.screenshot_artifact().await?;
                let path = self.trace.output.join("surface.png");
                fs::write(&path, artifact.bytes())?;
                let archive_ref = if let Some(recording) = &mut self.recording {
                    let image_reference = recording.archive.write(artifact.document()).await?;
                    let reference = artifact.write_to(&recording.archive).await?;
                    let document = recording.archive.read_document(&reference.document).await?;
                    let mut pixel_source = ArchivedSource::new_pixel_artifact(
                        artifact.info().identity.clone(),
                        &artifact,
                        1,
                        None,
                    );
                    pixel_source.file_archive = Some(
                        crate::archive::FileDocumentArchiveRef::Image(image_reference),
                    );
                    recording.outcome.retain(pixel_source)?;
                    let mut metadata_source =
                        ArchivedSource::new(reference.document.to_string(), &document, None);
                    metadata_source.document_archive = Some(reference.document.clone());
                    recording.outcome.retain(metadata_source)?;
                    Some(reference)
                } else {
                    None
                };
                Ok(json!({"path":path,"info":artifact.info(),"archive_ref":archive_ref}))
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
                .capture(
                    &document,
                    &index,
                    &snapshot,
                    self.epoch,
                    &retained_network_payloads(&self.browser, &snapshot)?,
                )
                .await
        {
            self.recording_fault = true;
            recording.fault();
            self.session.detach()?;
            self.browser.discard_pending_network_payloads()?;
            return Err(error);
        }
        let reply = json!({"descriptor":view.descriptor(),"observation":view.observation(),"root":view.root_reference()});
        if representation == super::BrowserRepresentation::Network {
            self.browser.commit_network_window(&snapshot)?;
            self.network_evidence.push_back(view.clone());
            while self.network_evidence.len() > self.network_evidence_limit {
                self.network_evidence.pop_front();
            }
        }
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
        if let Some(native) = self.browser.native()
            && let Err(error) = native.authorize(operation)
        {
            let receipt = lease.finish(ActionStatus::Rejected, error.to_string())?;
            return Ok(json!({"receipt":receipt}));
        }
        let element = if self.browser.native().is_some() {
            None
        } else if let Some(id) = id {
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
        if self.browser.native().is_some() {
            return self.execute_native(operation, before).await;
        }
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

    #[expect(
        clippy::significant_drop_tightening,
        reason = "NativeBrowser is borrowed here; ending this reference cannot release its Work, which the connection owns until close."
    )]
    async fn execute_native(&self, operation: &Operation, before: &Value) -> Result<Value> {
        use crate::internal::browser::page::SurfaceInput;
        let receipt = {
            let native = self
                .browser
                .native()
                .ok_or_else(|| io::Error::other("native binding missing"))?;
            match operation {
                Operation::Click { reference, .. } => {
                    native
                        .input(SurfaceInput::Click {
                            node: self.native_id(reference)?,
                        })
                        .await?
                }
                Operation::Fill {
                    reference, text, ..
                } => {
                    native
                        .input(SurfaceInput::Fill {
                            node: self.native_id(reference)?,
                            text: text.clone(),
                        })
                        .await?
                }
                Operation::Key { reference, key, .. } => {
                    native
                        .input(SurfaceInput::Key {
                            node: self.native_id(reference)?,
                            key: key.clone(),
                        })
                        .await?
                }
                Operation::Scroll {
                    delta_x, delta_y, ..
                } => {
                    native
                        .input(SurfaceInput::Scroll {
                            delta_x: *delta_x,
                            delta_y: *delta_y,
                        })
                        .await?
                }
                Operation::Navigate { url, .. } => native.navigate(url).await?,
                _ => {
                    return Err(io::Error::other("operation is not a native Surface effect").into());
                }
            }
        };
        let mut result = match operation {
            Operation::Fill {
                reference, text, ..
            } => {
                let node = self.native_id(reference)?;
                let value = self
                    .browser
                    .script("value", json!({"id":node,"expected":text}))
                    .await?;
                json!({"confirmed":value.get("matches")==Some(&Value::Bool(true)),"value":value})
            }
            Operation::Navigate { url, .. } => {
                let location = self.browser.script("location", json!({})).await?;
                json!({"confirmed":location.get("url").and_then(Value::as_str)==Some(url.as_str()),"location":location})
            }
            Operation::Click { expect, .. }
            | Operation::Key { expect, .. }
            | Operation::Scroll { expect, .. } => {
                self.postcondition(expect.as_ref(), before).await?
            }
            _ => return Err(io::Error::other("operation is not a native Surface effect").into()),
        };
        result
            .as_object_mut()
            .ok_or_else(|| io::Error::other("native action result is not an object"))?
            .insert("native_receipt_id".into(), receipt.into());
        Ok(result)
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
        let native = self.browser.native().is_some();
        let closed = self.browser.close().await;
        let archived = if let Some(recording) = &mut self.recording {
            if native {
                recording.release_work(&closed).await
            } else {
                recording.close(&closed).await
            }
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
            json!({"event":"ready","sdk":"ys::surface","state":self.status()?,"browser":self.browser.capabilities.get("browserVersion"),"source":self.browser.capabilities,"representation":"yosoi.web.document.v1","controllable":true,"protocol":"JSON lines; describe and read share the video protocol; close or EOF releases resources"}),
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

/// A live browser source, initially detached from observation and control.
///
/// Open an isolated source or bind an existing native Session/Work owner.
/// Call `close` even after failure; cancellation does not prove an effect was undone.
pub struct BrowserSurface {
    inner: Connection<Driver>,
}
impl BrowserSurface {
    /// Arms native Chrome request events on the consumed Session tab.
    ///
    /// Network capture is explicit. URLs, headers, event history, response
    /// buffers and optional bodies remain subject to `SurfacePolicy` bounds.
    /// BiDi and the isolated ChromeDriver provider report an unsupported
    /// capability. Enabling a subscription escalates this tab's CDP Network
    /// instrumentation for its remaining Page lifetime.
    pub async fn subscribe_network(
        &mut self,
        retain_bodies: Option<bool>,
    ) -> StdResult<NetworkSubscription, ExecutionError> {
        let mut command = json!({"op":"network_subscribe"});
        if let Some(retain_bodies) = retain_bodies {
            if let Some(fields) = command.as_object_mut() {
                fields.insert("retain_bodies".into(), Value::Bool(retain_bodies));
            }
        }
        let value = self.inner.execute(command).await?;
        serde_json::from_value(value).map_err(|error| ExecutionError::Operation(Box::new(error)))
    }

    /// Cancels the active event subscription and releases its listener queues.
    /// The Page-level Network domain remains enabled if shared browser work uses it.
    pub async fn cancel_network(&mut self) -> StdResult<Value, ExecutionError> {
        self.inner.execute(json!({"op":"network_cancel"})).await
    }

    /// Waits for an event sequence after an event-driven, bounded timeout.
    pub async fn wait_network_event(
        &mut self,
        after_sequence: u64,
        timeout_ms: u64,
    ) -> StdResult<Value, ExecutionError> {
        self.inner
            .execute(json!({"op":"network_wait","after_sequence":after_sequence,"timeout_ms":timeout_ms}))
            .await
    }

    /// Captures a frozen network window through the shared bounded read protocol.
    pub async fn observe_network(
        &mut self,
    ) -> StdResult<(super::BrowserObservation, NetworkWindow), ExecutionError> {
        let observation = self.observe(super::BrowserRepresentation::Network).await?;
        let mut request = model::ReadRequest {
            operation: model::ReadOperation::Inspect {
                reference: observation.root.clone(),
            },
            budget: Budget {
                bytes: 65_280,
                items: 100,
            },
            continuation: None,
        };
        let mut content = String::new();
        loop {
            match self
                .read(super::BrowserRepresentation::Network, request.clone())
                .await?
            {
                model::ReadResult::Inspection(detail) => {
                    content.push_str(&detail.content);
                    let Some(next) = detail.next else {
                        break;
                    };
                    request.continuation = Some(next);
                }
                _ => {
                    return Err(ExecutionError::Operation(
                        io::Error::other(
                            "network window inspection returned a non-inspection result",
                        )
                        .into(),
                    ));
                }
            }
        }
        let window: NetworkWindow = serde_json::from_str(&content)
            .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
        window
            .validate()
            .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
        Ok((observation, window))
    }

    /// Reads an opt-in response body in bounded chunks and restores its existing
    /// HTML, JSON, or FileDocument projection.
    pub async fn network_payload(
        &mut self,
        reference: &NetworkPayloadRef,
        chunk_bytes: usize,
    ) -> StdResult<NetworkPayload, ExecutionError> {
        if !matches!(
            reference.state,
            NetworkPayloadState::Retained | NetworkPayloadState::Truncated
        ) {
            return Err(ExecutionError::Operation(
                io::Error::other("network response body was not retained").into(),
            ));
        }
        if !(1..=32_768).contains(&chunk_bytes) {
            return Err(ExecutionError::Operation(
                io::Error::other("network payload chunk must be between 1 and 32768 bytes").into(),
            ));
        }
        let mut offset = 0usize;
        let mut total_bytes = None;
        let mut content = Vec::new();
        loop {
            let reply = self
                .inner
                .execute(json!({"op":"network_payload","reference":reference,
                    "offset":offset,"max_bytes":chunk_bytes,"budget":65536}))
                .await?;
            let total = reply
                .get("total_bytes")
                .and_then(Value::as_u64)
                .and_then(|value| usize::try_from(value).ok())
                .ok_or_else(|| {
                    ExecutionError::Operation(
                        io::Error::other("network payload omitted its byte length").into(),
                    )
                })?;
            if total_bytes.is_some_and(|prior| prior != total) {
                return Err(ExecutionError::Operation(
                    io::Error::other("network payload length changed during read").into(),
                ));
            }
            total_bytes = Some(total);
            let current_offset = reply
                .get("offset")
                .and_then(Value::as_u64)
                .and_then(|value| usize::try_from(value).ok())
                .ok_or_else(|| {
                    ExecutionError::Operation(
                        io::Error::other("network payload omitted its offset").into(),
                    )
                })?;
            if current_offset != offset {
                return Err(ExecutionError::Operation(
                    io::Error::other("network payload returned a different offset").into(),
                ));
            }
            let encoded = reply
                .get("data_base64")
                .and_then(Value::as_str)
                .ok_or_else(|| {
                    ExecutionError::Operation(
                        io::Error::other("network payload omitted its bytes").into(),
                    )
                })?;
            let chunk = STANDARD
                .decode(encoded)
                .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
            if chunk.is_empty() && offset < total {
                return Err(ExecutionError::Operation(
                    io::Error::other("network payload read made no progress").into(),
                ));
            }
            offset = offset.checked_add(chunk.len()).ok_or_else(|| {
                ExecutionError::Operation(
                    io::Error::other("network payload offset overflowed").into(),
                )
            })?;
            if offset > total {
                return Err(ExecutionError::Operation(
                    io::Error::other("network payload exceeded its declared length").into(),
                ));
            }
            content.extend_from_slice(&chunk);
            if offset >= total {
                break;
            }
        }
        if let Some(expected) = reference.sha256.as_deref()
            && format!("{:x}", Sha256::digest(&content)) != expected
        {
            return Err(ExecutionError::Operation(
                io::Error::other("network payload digest did not match its response reference")
                    .into(),
            ));
        }
        let id = reference
            .document_id
            .as_deref()
            .map_or(reference.id.as_str(), |value| value);
        let value = match reference.document_kind {
            Some(NetworkPayloadKind::Html) => NetworkPayloadValue::Document(
                Document::html(id, content)
                    .map_err(|error| ExecutionError::Operation(Box::new(error)))?,
            ),
            Some(NetworkPayloadKind::Json) => NetworkPayloadValue::Document(
                Document::json(id, content)
                    .map_err(|error| ExecutionError::Operation(Box::new(error)))?,
            ),
            Some(NetworkPayloadKind::File) => {
                let metadata = FileMetadata::new()
                    .with_capture_id(reference.request_id.clone())
                    .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
                let limit = u64::try_from(content.len()).map_err(|_| {
                    ExecutionError::Operation(
                        io::Error::other("network payload size is unsupported").into(),
                    )
                })?;
                let limits = FileLimits::new(limit)
                    .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
                let file: FileDocument = file_from_bytes(id, content, metadata, limits)
                    .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
                NetworkPayloadValue::File(file)
            }
            None => {
                return Err(ExecutionError::Operation(
                    io::Error::other("network payload has no retained projection kind").into(),
                ));
            }
        };
        Ok(NetworkPayload {
            reference: reference.clone(),
            value,
        })
    }

    /// Retains the native Session owner and acquires Work for its initial tab.
    /// This never launches ChromeDriver or another browser. The existing Session
    /// policy and execution pool remain authoritative. Closing this binding releases
    /// its Work only; keep a Session handle for explicit shared-browser cleanup.
    /// The consumed binding currently supports native Chrome DOM and AX evidence.
    pub async fn consume_session(
        session: NativeSession,
        policy: SurfacePolicy,
    ) -> StdResult<Self, ExecutionError> {
        let work = session
            .work()
            .await
            .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
        Self::consume_work(work, policy).await
    }

    /// Acquires and retains Work for one existing native tab.
    /// Sibling tabs keep their own control and scheduling. Closing releases this
    /// tab's Work without closing the tab or its shared Session.
    pub async fn consume_tab(tab: &Tab, policy: SurfacePolicy) -> StdResult<Self, ExecutionError> {
        let work = tab
            .work()
            .await
            .map_err(|error| ExecutionError::Operation(Box::new(error)))?;
        Self::consume_work(work, policy).await
    }

    /// Transfers already-admitted native Work into a Surface connection.
    /// No second controller is acquired. Captures and effects use this Work's
    /// tab, policy, cancellation and execution pool. Close releases Work and does
    /// not explicitly close the retained Session/tab. Arbitrary JavaScript is not
    /// required; native Surface's trusted adapter owns its capture implementation.
    pub async fn consume_work(
        work: Work,
        policy: SurfacePolicy,
    ) -> StdResult<Self, ExecutionError> {
        Self::consume_work_inner(work, policy)
            .await
            .map_err(super::archive::error)
    }

    async fn consume_work_inner(work: Work, policy: SurfacePolicy) -> Result<Self> {
        policy.archive_limits.validate()?;
        policy.documents.validate()?;
        policy.network_observation.validate()?;
        let mut browser =
            Browser::consume_work(work, policy.documents, policy.network_observation).await?;
        let location = browser.script("location", json!({})).await?;
        let url = location
            .get("url")
            .and_then(Value::as_str)
            .ok_or_else(|| io::Error::other("native tab URL missing"))?;
        let temporary = tempfile::tempdir()?;
        let output = policy
            .output
            .clone()
            .unwrap_or_else(|| temporary.path().join("artifacts"));
        fs::create_dir_all(&output)?;
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
        let mut trace = Trace::new(&output);
        let initialized = async {
            if let Some(recording) = &mut recording {
                recording
                    .native_binding(browser.capabilities.clone())
                    .await?;
            }
            let (surface, document, snapshot) = browser.capture(1, &mut trace).await?;
            if let Some(recording) = &mut recording {
                recording
                    .capture(&document, &surface, &snapshot, 1, &[])
                    .await?;
            }
            let session = Session::new(surface, SessionPolicy::default())?;
            let cursor = session.cursor()?;
            Ok::<_, Box<dyn Error + Send + Sync>>((session, cursor))
        }
        .await;
        let (session, cursor) = match initialized {
            Ok(value) => value,
            Err(source) => {
                let released = browser.close().await;
                if let Some(recording) = &mut recording {
                    recording.fault();
                    let _ = recording
                        .command(
                            json!({"op":"consume_work"}),
                            &Err(io::Error::other(source.to_string()).into()),
                        )
                        .await;
                    let _ = recording.release_work(&released).await;
                    return Err(Box::new(repeating::RunFailure {
                        outcomes: vec![recording.outcome()],
                        source,
                    }));
                }
                released?;
                return Err(source);
            }
        };
        let network_evidence_limit = browser.network_window_limit().map_or(1, |limit| limit);
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
                    network_evidence: VecDeque::new(),
                    network_evidence_limit,
                },
                output,
                temporary,
            ),
        })
    }

    /// Captures fresh evidence without acquiring live action authority.
    /// Native Session bindings support depth-limited AX. The isolated provider
    /// supports DOM only; unsupported representations return an error.
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
        policy.network_observation.validate()?;
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
                recording
                    .capture(&document, &surface, &snapshot, 1, &[])
                    .await?;
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
        let network_evidence_limit = browser.network_window_limit().map_or(1, |limit| limit);
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
                    network_evidence: VecDeque::new(),
                    network_evidence_limit,
                },
                output,
                temporary,
            ),
        })
    }
}
connection!(BrowserSurface);
