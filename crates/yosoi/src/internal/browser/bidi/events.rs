//! Scoped BiDi network/log subscriptions and decoded response-body ownership.

use base64::{Engine as _, engine::general_purpose::STANDARD};
use serde_json::{Value, json};
use std::fmt;
use std::{
    collections::{BTreeMap, BTreeSet},
    time::Duration,
};
use tokio::runtime::Handle;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;

use super::{
    session::{Page, SessionError},
    transport::{BidiEvent, EventStream},
};
use crate::browser::BrowserEngine;

// Leave room for JSON/base64 expansion within the transport's 16 MiB frame
// limit. This is provider materialization, separate from retained body limits.
const COLLECTOR_ITEM_BYTES: usize = 2 * 1024 * 1024;

pub struct ScopedCapture {
    page: Page,
    events: EventStream,
    subscription: Option<String>,
    collector: Option<String>,
    contexts: BTreeSet<String>,
    response_sizes: BTreeMap<String, usize>,
    sources: Sources,
}

#[derive(Clone, Copy)]
struct Sources {
    network: bool,
    logs: bool,
    bodies: bool,
}

pub struct ResponseBody {
    pub bytes: Vec<u8>,
    pub complete_bytes: usize,
}

impl fmt::Debug for ScopedCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ScopedCapture")
            .field("body_collection", &self.collector.is_some())
            .field("context_count", &self.contexts.len())
            .finish_non_exhaustive()
    }
}

impl fmt::Debug for ResponseBody {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ResponseBody")
            .field("retained_bytes", &self.bytes.len())
            .field("complete_bytes", &self.complete_bytes)
            .finish()
    }
}

impl Page {
    pub async fn arm_network(
        &self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ScopedCapture, SessionError> {
        self.arm_events(
            Sources {
                network: true,
                logs: false,
                bodies: true,
            },
            cancellation,
            deadline,
        )
        .await
    }

    pub async fn arm_observation_events(
        &self,
        network: bool,
        logs: bool,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ScopedCapture, SessionError> {
        self.arm_events(
            Sources {
                network,
                logs,
                bodies: false,
            },
            cancellation,
            deadline,
        )
        .await
    }

    async fn arm_events(
        &self,
        sources: Sources,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ScopedCapture, SessionError> {
        self.ensure_owned().await?;
        // Register the local receiver first; events can precede subscribe's
        // reply. A collector is armed before navigation, never retroactively.
        let mut capture = ScopedCapture {
            page: self.clone(),
            events: self.session.connection.subscribe()?,
            subscription: None,
            collector: None,
            contexts: BTreeSet::new(),
            response_sizes: BTreeMap::new(),
            sources,
        };
        capture.contexts.insert(self.context.clone());
        if sources.network || sources.logs {
            capture.contexts.extend(
                self.frames(cancellation, deadline)
                    .await?
                    .into_iter()
                    .map(|frame| frame.context),
            );
        }
        if sources.bodies {
            let result = self.command(
            "network.addDataCollector",
            json!({"dataTypes":["response"],"maxEncodedDataSize":COLLECTOR_ITEM_BYTES,"contexts":[self.context]}),
            cancellation,
            deadline,
        ).await?;
            capture.collector = Some(identifier(&result, "collector")?);
        }
        let mut methods = Vec::new();
        if sources.network {
            methods.extend([
                "network.beforeRequestSent",
                "network.responseStarted",
                "network.responseCompleted",
                "network.fetchError",
            ]);
        }
        if sources.logs {
            methods.push("log.entryAdded");
        }
        if !methods.is_empty() {
            let result = self
                .command(
                    "session.subscribe",
                    json!({"events":methods,"contexts":[self.context]}),
                    cancellation,
                    deadline,
                )
                .await?;
            capture.subscription = Some(identifier(&result, "subscription")?);
        }
        Ok(capture)
    }
}

impl ScopedCapture {
    pub async fn next(
        &mut self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<BidiEvent, SessionError> {
        loop {
            let event = self.events.next(cancellation, deadline).await?;
            // The browser scopes this subscription to the root and descendants;
            // other subscriptions share the connection, so filter its methods.
            let context = event.params.get("context").and_then(Value::as_str);
            if event.method == "browsingContext.contextDestroyed"
                && context == Some(self.page.context.as_str())
            {
                return Err(SessionError::Context);
            }
            if event.method == "browsingContext.contextCreated"
                && event
                    .params
                    .get("parent")
                    .and_then(Value::as_str)
                    .is_some_and(|parent| self.contexts.contains(parent))
                && let Some(context) = context
            {
                if self.contexts.len() >= 4096 && !self.contexts.contains(context) {
                    return Err(SessionError::Capacity);
                }
                self.contexts.insert(context.to_owned());
            }
            let selected = (self.sources.network && event.method.starts_with("network."))
                || (self.sources.logs && event.method == "log.entryAdded");
            if !selected {
                continue;
            }
            let context = if event.method == "log.entryAdded" {
                event
                    .params
                    .pointer("/source/context")
                    .and_then(Value::as_str)
            } else {
                context
            };
            if context.is_none() {
                return Err(SessionError::Context);
            }
            if context.is_some_and(|context| self.contexts.contains(context)) {
                if self.sources.bodies && event.method == "network.responseCompleted" {
                    self.record_response_extent(&event.params)?;
                }
                return Ok(event);
            }
            // Scope routing is local and ordered with the event stream. Never
            // dispatch a command from a receive future that a stop may cancel.
        }
    }

    // The response watch owns a separate DOM/network event receiver. It records
    // only its already scope-checked completed candidate into this collector.
    pub(super) fn record_response_extent(&mut self, params: &Value) -> Result<(), SessionError> {
        let request = identifier(
            params.get("request").ok_or(SessionError::Serialization)?,
            "request",
        )?;
        if self.response_sizes.len() >= 4096 && !self.response_sizes.contains_key(&request) {
            return Err(SessionError::Capacity);
        }
        if let Some(size) = completed_decoded_extent(params) {
            self.response_sizes.insert(request, size);
        }
        Ok(())
    }

    pub async fn response_body(
        &self,
        request: &str,
        max_bytes: usize,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ResponseBody, SessionError> {
        self.body(request, max_bytes, true, cancellation, deadline)
            .await
    }

    pub(super) async fn retained_response_body(
        &self,
        request: &str,
        max_bytes: usize,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ResponseBody, SessionError> {
        self.body(request, max_bytes, false, cancellation, deadline)
            .await
    }

    async fn body(
        &self,
        request: &str,
        max_bytes: usize,
        disown: bool,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<ResponseBody, SessionError> {
        if max_bytes == 0 {
            return Err(SessionError::Capacity);
        }
        let collector = self.collector.as_ref().ok_or(SessionError::Context)?;
        let result = self.page.command(
            "network.getData",
            json!({"dataType":"response","request":request,"collector":collector,"disown":disown}),
            cancellation,
            deadline,
        ).await?;
        let body = decode_body(&result, max_bytes)?;
        if self.page.session.config.engine == BrowserEngine::Firefox
            && self.response_sizes.get(request).copied() != Some(body.complete_bytes)
        {
            // Firefox's text-MIME path can return a Latin-1 byte string after
            // failed UTF-8 conversion, mislabeled as network.StringValue.
            // Re-encoding it changes the HTTP body. Never guess a replacement
            // encoding or claim these altered bytes are a complete source.
            return Err(SessionError::Unsupported(
                "Firefox response body byte fidelity",
            ));
        }
        Ok(body)
    }

    pub async fn close(
        &mut self,
        cancellation: &CancellationToken,
        deadline: Instant,
    ) -> Result<(), SessionError> {
        // Keep failed handles owned so Drop can attempt bounded cleanup.
        if let Some(subscription) = &self.subscription {
            self.page
                .command(
                    "session.unsubscribe",
                    json!({"subscriptions":[subscription]}),
                    cancellation,
                    deadline,
                )
                .await?;
            self.subscription = None;
        }
        if let Some(collector) = &self.collector {
            self.page
                .command(
                    "network.removeDataCollector",
                    json!({"collector":collector}),
                    cancellation,
                    deadline,
                )
                .await?;
            self.collector = None;
        }
        Ok(())
    }
}

impl Drop for ScopedCapture {
    fn drop(&mut self) {
        let subscription = self.subscription.take();
        let collector = self.collector.take();
        if subscription.is_none() && collector.is_none() {
            return;
        }
        let page = self.page.clone();
        if let Ok(runtime) = Handle::try_current() {
            runtime.spawn(async move {
                let Some(deadline) = Instant::now().checked_add(Duration::from_secs(5)) else {
                    page.session.connection.fence();
                    return;
                };
                let token = CancellationToken::new();
                for (method, params) in [
                    subscription.map(|id| ("session.unsubscribe", json!({"subscriptions":[id]}))),
                    collector.map(|id| ("network.removeDataCollector", json!({"collector":id}))),
                ]
                .into_iter()
                .flatten()
                {
                    if page
                        .command(method, params, &token, deadline)
                        .await
                        .is_err()
                    {
                        page.session.connection.fence();
                        break;
                    }
                }
            });
        } else {
            page.session.connection.fence();
        }
    }
}

fn identifier(value: &Value, key: &str) -> Result<String, SessionError> {
    value
        .get(key)
        .and_then(Value::as_str)
        .filter(|id| !id.is_empty() && id.len() <= 512)
        .map(str::to_owned)
        .ok_or(SessionError::Serialization)
}

fn decode_body(result: &Value, max_bytes: usize) -> Result<ResponseBody, SessionError> {
    let bytes = result.get("bytes").ok_or(SessionError::Serialization)?;
    let value = bytes
        .get("value")
        .and_then(Value::as_str)
        .ok_or(SessionError::Serialization)?;
    let mut bytes = match bytes.get("type").and_then(Value::as_str) {
        Some("string") => value.as_bytes().to_vec(),
        Some("base64") => STANDARD
            .decode(value)
            .map_err(|_| SessionError::Serialization)?,
        _ => return Err(SessionError::Serialization),
    };
    let complete_bytes = bytes.len();
    bytes.truncate(max_bytes);
    Ok(ResponseBody {
        bytes,
        complete_bytes,
    })
}

fn completed_decoded_extent(params: &Value) -> Option<usize> {
    let response = params.get("response")?;
    let reported = response.pointer("/content/size").and_then(Value::as_u64);
    let size = if reported.is_some_and(|size| size > 0) {
        reported
    } else {
        // Firefox 158 can report decoded size 0 for a nonempty response.
        // Encoded bodySize proves the extent only without content coding.
        let headers = response.get("headers")?.as_array()?;
        if headers.iter().any(|header| {
            header
                .get("name")
                .and_then(Value::as_str)
                .is_some_and(|name| name.eq_ignore_ascii_case("content-encoding"))
        }) {
            return None;
        }
        response.get("bodySize").and_then(Value::as_u64)
    }?;
    usize::try_from(size).ok()
}

#[cfg(test)]
mod tests;
