//! Native DOM hints and root-document response watches with owned collectors.

use super::{
    events::ScopedCapture,
    session::{Page, moli_realm_alias},
    transport::EventStream,
};
use crate::browser::BrowserEngine;
use crate::internal::browser::{
    CompletedResponseCandidate, DocumentScope, ObservationChange, ObservationResponseBody,
    ObservationWatchOptions, Result, VoidCrawlError, controller::map_bidi,
    page::observation_watch::next_watch_id,
};
use serde_json::{Value, json};
use std::{
    collections::BTreeMap,
    fmt,
    sync::{
        Arc, Weak,
        atomic::{AtomicBool, Ordering},
    },
    time::Duration,
};
use tokio::{runtime::Handle, sync::Mutex, time::Instant};
use tokio_util::sync::CancellationToken;

pub(in crate::internal::browser) struct Inner {
    page: Page,
    id: u64,
    scope: DocumentScope,
    realm: String,
    frame: String,
    channel: String,
    active: AtomicBool,
    network: Mutex<Option<ScopedCapture>>,
    handle: Mutex<Option<String>>,
}

pub struct ObservationWatch {
    inner: Arc<Inner>,
    events: EventStream,
    options: ObservationWatchOptions,
    pending: BTreeMap<String, Pending>,
    pending_bytes: usize,
    filter_bytes: usize,
    sequence: u64,
}

impl fmt::Debug for ObservationWatch {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("BidiObservationWatch")
            .field("active", &self.inner.active.load(Ordering::Acquire))
            .finish_non_exhaustive()
    }
}

struct Pending {
    url: String,
    method: String,
    started: u64,
    weight: usize,
}

impl Page {
    pub async fn start_observation_watch(
        &self,
        options: ObservationWatchOptions,
    ) -> Result<ObservationWatch> {
        let filter_bytes = options.validate()?;
        if options.observe_accessibility {
            return Err(VoidCrawlError::UnsupportedCapability {
                operation: "BiDi native AX change notifications",
            });
        }
        let token = CancellationToken::new();
        let deadline = operation_deadline()?;
        let mut current = self.active_watch.lock().await;
        if current
            .as_ref()
            .and_then(Weak::upgrade)
            .is_some_and(|watch| watch.active.load(Ordering::Acquire))
        {
            return Err(lost("another observation watch owns this page"));
        }
        let events = self
            .session
            .connection
            .subscribe()
            .map_err(|_| lost("event stream unavailable"))?;
        let scope = self
            .document_scope(&token, deadline)
            .await
            .map_err(map_bidi)?;
        let (_, realm) = self
            .evaluate("0", &token, deadline)
            .await
            .map_err(map_bidi)?;
        let id = next_watch_id()?;
        let inner = Arc::new(Inner {
            page: self.clone(),
            id,
            scope,
            realm,
            frame: format!("bidi-frame-{}", self.frame_id),
            channel: format!("yosoi-watch-{id}"),
            active: AtomicBool::new(true),
            network: Mutex::new(None),
            handle: Mutex::new(None),
        });
        *current = Some(Arc::downgrade(&inner));
        if !options.response_filters.is_empty() {
            *inner.network.lock().await =
                Some(self.arm_network(&token, deadline).await.map_err(map_bidi)?);
        }
        if options.observe_dom {
            let reply = self
                .command(
                    "script.callFunction",
                    json!({
                        "target":{"realm":inner.realm},"functionDeclaration":DOM_OBSERVER,
                        "arguments":[{"type":"channel","value":{"channel":inner.channel}}],
                        "awaitPromise":false,"resultOwnership":"root",
                        "serializationOptions":{"maxObjectDepth":0,"maxDomDepth":0},
                    }),
                    &token,
                    deadline,
                )
                .await
                .map_err(map_bidi)?;
            let handle = reply
                .get("result")
                .and_then(|result| result.get("handle"))
                .and_then(Value::as_str)
                .filter(|handle| !handle.is_empty() && handle.len() <= 512);
            if reply.get("type").and_then(Value::as_str) != Some("success")
                || reply.get("realm").and_then(Value::as_str) != Some(inner.realm.as_str())
                || handle.is_none()
            {
                self.session.connection.fence();
                return Err(lost("DOM observer installation has no owned handle"));
            }
            *inner.handle.lock().await = handle.map(str::to_owned);
        }
        inner.verify(self, &token, deadline).await?;
        drop(current);
        Ok(ObservationWatch {
            inner,
            events,
            options,
            pending: BTreeMap::new(),
            pending_bytes: 0,
            filter_bytes,
            sequence: 0,
        })
    }

    pub async fn capture_observation_response_body(
        &self,
        candidate: &CompletedResponseCandidate,
        max_bytes: usize,
    ) -> Result<ObservationResponseBody> {
        if max_bytes == 0 || max_bytes > 8 * 1024 * 1024 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "capture_response_body",
                reason: "body limit must be between 1 and 8 MiB",
            });
        }
        let inner = self
            .active_watch
            .lock()
            .await
            .as_ref()
            .and_then(Weak::upgrade)
            .ok_or_else(|| lost("response collector is no longer active"))?;
        if !candidate.native
            || candidate.watch_id != inner.id
            || candidate.page_target_id != self.context
            || candidate.epoch != inner.scope.epoch
        {
            return Err(lost("response candidate belongs to another scope"));
        }
        let token = CancellationToken::new();
        let deadline = operation_deadline()?;
        inner.verify(self, &token, deadline).await?;
        let body = {
            let network = inner.network.lock().await;
            if !inner.active.load(Ordering::Acquire) {
                return Err(lost("response watch settled"));
            }
            network
                .as_ref()
                .ok_or_else(|| lost("response collector unavailable"))?
                .retained_response_body(&candidate.request_id, max_bytes, &token, deadline)
                .await
                .map_err(map_bidi)?
        };
        drop(inner);
        Ok(ObservationResponseBody {
            complete: body.bytes.len() == body.complete_bytes,
            bytes: body.bytes,
        })
    }

    pub async fn evaluate_in_watch(&self, source: &str, watch: &ObservationWatch) -> Result<Value> {
        let token = CancellationToken::new();
        let deadline = operation_deadline()?;
        watch.inner.verify(self, &token, deadline).await?;
        self.evaluate_realm(source, &watch.inner.realm, &token, deadline)
            .await
            .map(|value| value.0)
            .map_err(map_bidi)
    }

    pub async fn click_in_watch(&self, selector: &str, watch: &ObservationWatch) -> Result<()> {
        let token = CancellationToken::new();
        let deadline = operation_deadline()?;
        watch.inner.verify(self, &token, deadline).await?;
        self.click_in_realm(selector, Some(&watch.inner.realm), &token, deadline)
            .await
            .map_err(map_bidi)
    }

    pub async fn type_in_watch(
        &self,
        selector: &str,
        text: &str,
        watch: &ObservationWatch,
    ) -> Result<()> {
        let token = CancellationToken::new();
        let deadline = operation_deadline()?;
        watch.inner.verify(self, &token, deadline).await?;
        self.type_in_realm(selector, text, Some(&watch.inner.realm), &token, deadline)
            .await
            .map_err(map_bidi)
    }
}

impl Inner {
    async fn verify(
        &self,
        page: &Page,
        token: &CancellationToken,
        deadline: Instant,
    ) -> Result<()> {
        if !self.active.load(Ordering::Acquire)
            || !Arc::ptr_eq(&self.page.active_watch, &page.active_watch)
        {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        let scope = page
            .document_scope(token, deadline)
            .await
            .map_err(map_bidi)?;
        if scope.frame_id != self.scope.frame_id
            || scope.epoch != self.scope.epoch
            || scope.frame != self.scope.frame
        {
            return Err(VoidCrawlError::NavigationStateUncertain);
        }
        Ok(())
    }
}

impl ObservationWatch {
    pub fn start_scope(&self) -> &DocumentScope {
        &self.inner.scope
    }
    pub fn frame_id(&self) -> &str {
        &self.inner.frame
    }

    pub async fn next(&mut self) -> Result<ObservationChange> {
        if !self.inner.active.load(Ordering::Acquire) {
            return Err(lost("watch is settled"));
        }
        let token = CancellationToken::new();
        // The invocation owns the actual deadline and cancellation. This long
        // bound only caps a standalone parked receive; it does not poll.
        let deadline = Instant::now()
            .checked_add(Duration::from_hours(24))
            .ok_or_else(|| lost("deadline overflow"))?;
        loop {
            let event = self
                .events
                .next(&token, deadline)
                .await
                .map_err(|_| lost("event stream lost"))?;
            if event.method == "script.realmDestroyed"
                && event.params.get("realm").and_then(Value::as_str)
                    == Some(self.inner.realm.as_str())
            {
                return Err(lost("watched realm destroyed"));
            }
            if event.method == "script.message"
                && event.params.get("channel").and_then(Value::as_str)
                    == Some(self.inner.channel.as_str())
            {
                let source = event
                    .params
                    .get("source")
                    .ok_or_else(|| lost("DOM hint source missing"))?;
                let raw = source
                    .get("realm")
                    .and_then(Value::as_str)
                    .ok_or_else(|| lost("DOM hint realm missing"))?;
                let realm = if self.inner.page.session.config.engine == BrowserEngine::Moli {
                    moli_realm_alias(&self.inner.page.context, raw).map_err(map_bidi)?
                } else {
                    raw.to_owned()
                };
                if source.get("context").and_then(Value::as_str)
                    != Some(self.inner.page.context.as_str())
                    || realm != self.inner.realm
                {
                    return Err(lost("DOM hint scope changed"));
                }
                if event.params.pointer("/data/type").and_then(Value::as_str) != Some("number") {
                    return Err(lost("DOM hint has invalid type"));
                }
                let sequence = event
                    .params
                    .pointer("/data/value")
                    .and_then(Value::as_u64)
                    .ok_or_else(|| lost("invalid DOM sequence"))?;
                if self.sequence.checked_add(1) != Some(sequence) {
                    return Err(lost("DOM hints lost or reordered"));
                }
                self.sequence = sequence;
                return Ok(ObservationChange::DomChanged { sequence });
            }
            if event.params.get("context").and_then(Value::as_str)
                != Some(self.inner.page.context.as_str())
            {
                continue;
            }
            if event.method == "browsingContext.contextDestroyed" {
                return Err(lost("watched context closed"));
            }
            if event.method == "script.realmCreated" {
                let raw = event
                    .params
                    .get("realm")
                    .and_then(Value::as_str)
                    .ok_or_else(|| lost("realm identity missing"))?;
                let realm = if self.inner.page.session.config.engine == BrowserEngine::Moli {
                    moli_realm_alias(&self.inner.page.context, raw).map_err(map_bidi)?
                } else {
                    raw.to_owned()
                };
                if event.params.get("sandbox").is_none() && realm != self.inner.realm {
                    return Err(lost("watched document changed"));
                }
            }
            if let Some(candidate) = self.network_event(&event.method, &event.params)? {
                if let Some(collector) = self.inner.network.lock().await.as_mut() {
                    collector
                        .record_response_extent(&event.params)
                        .map_err(map_bidi)?;
                }
                return Ok(ObservationChange::ResponseCompleted(candidate));
            }
        }
    }

    fn network_event(
        &mut self,
        method: &str,
        params: &Value,
    ) -> Result<Option<CompletedResponseCandidate>> {
        if !method.starts_with("network.") {
            return Ok(None);
        }
        let request = params
            .get("request")
            .ok_or_else(|| lost("request metadata missing"))?;
        let id = request
            .get("request")
            .and_then(Value::as_str)
            .filter(|id| !id.is_empty() && id.len() <= 512)
            .ok_or_else(|| lost("request identity invalid"))?;
        if method == "network.beforeRequestSent" {
            if let Some(old) = self.pending.remove(id) {
                self.pending_bytes = self
                    .pending_bytes
                    .checked_sub(old.weight)
                    .ok_or_else(|| lost("metadata accounting underflow"))?;
            }
            let url = request
                .get("url")
                .and_then(Value::as_str)
                .ok_or_else(|| lost("request URL missing"))?;
            let verb = request
                .get("method")
                .and_then(Value::as_str)
                .ok_or_else(|| lost("request method missing"))?;
            if !self
                .options
                .response_filters
                .iter()
                .any(|filter| filter.matches_request(url, verb))
            {
                return Ok(None);
            }
            let started = params
                .get("timestamp")
                .and_then(Value::as_u64)
                .and_then(|value| value.checked_mul(1000))
                .filter(|value| *value > 0)
                .ok_or_else(|| lost("request wall time invalid"))?;
            let weight = id
                .len()
                .checked_mul(2)
                .and_then(|weight| weight.checked_add(url.len()))
                .and_then(|weight| weight.checked_add(verb.len()))
                .and_then(|weight| weight.checked_add(64))
                .ok_or_else(|| lost("metadata accounting overflow"))?;
            let size = self
                .pending_bytes
                .checked_add(weight)
                .and_then(|size| size.checked_add(self.filter_bytes))
                .ok_or_else(|| lost("metadata accounting overflow"))?;
            if self.pending.len() >= self.options.max_events || size > self.options.max_bytes {
                return Err(lost("response metadata limit reached"));
            }
            self.pending_bytes = self
                .pending_bytes
                .checked_add(weight)
                .ok_or_else(|| lost("metadata accounting overflow"))?;
            self.pending.insert(
                id.to_owned(),
                Pending {
                    url: url.to_owned(),
                    method: verb.to_owned(),
                    started,
                    weight,
                },
            );
        } else if matches!(method, "network.responseCompleted" | "network.fetchError") {
            let Some(pending) = self.pending.remove(id) else {
                return Ok(None);
            };
            self.pending_bytes = self
                .pending_bytes
                .checked_sub(pending.weight)
                .ok_or_else(|| lost("metadata accounting underflow"))?;
            if method == "network.fetchError" {
                return Ok(None);
            }
            let status = params
                .pointer("/response/status")
                .and_then(Value::as_u64)
                .and_then(|status| u16::try_from(status).ok())
                .filter(|status| (100..=599).contains(status))
                .ok_or_else(|| lost("response status invalid"))?;
            let url = params
                .pointer("/response/url")
                .and_then(Value::as_str)
                .ok_or_else(|| lost("response URL missing"))?;
            if url != pending.url
                || !self
                    .options
                    .response_filters
                    .iter()
                    .any(|filter| filter.matches_response(url, &pending.method, status))
            {
                return Ok(None);
            }
            return Ok(Some(CompletedResponseCandidate {
                request_id: id.to_owned(),
                page_target_id: self.inner.page.context.clone(),
                watch_id: self.inner.id,
                native: true,
                url: pending.url,
                method: pending.method,
                status,
                loader_id: None,
                frame_id: Some(self.inner.frame.clone()),
                top_level: true,
                started_at_unix_us: pending.started,
                epoch: self.inner.scope.epoch,
            }));
        }
        Ok(None)
    }

    pub async fn settle(&mut self) -> Result<()> {
        self.inner.active.store(false, Ordering::Release);
        let token = CancellationToken::new();
        let deadline = operation_deadline()?;
        let mut handle = self.inner.handle.lock().await;
        if let Some(value) = handle.as_ref() {
            stop_observer(&self.inner.page, &self.inner.realm, value, &token, deadline).await?;
            *handle = None;
        }
        drop(handle);
        let mut network = self.inner.network.lock().await;
        if let Some(capture) = network.as_mut() {
            capture.close(&token, deadline).await.map_err(map_bidi)?;
        }
        *network = None;
        self.pending.clear();
        self.pending_bytes = 0;
        Ok(())
    }
}

impl Drop for Inner {
    #[allow(
        clippy::significant_drop_tightening,
        reason = "Collectors move into bounded async cleanup, which must acknowledge their removal."
    )]
    fn drop(&mut self) {
        self.active.store(false, Ordering::Release);
        let handle = self.handle.get_mut().take();
        let mut network = self.network.get_mut().take();
        if handle.is_none() && network.is_none() {
            return;
        }
        let page = self.page.clone();
        let realm = self.realm.clone();
        let Ok(runtime) = Handle::try_current() else {
            page.session.connection.fence();
            return;
        };
        runtime.spawn(async move {
            let Some(deadline) = Instant::now().checked_add(Duration::from_secs(2)) else {
                page.session.connection.fence();
                return;
            };
            let token = CancellationToken::new();
            if let Some(handle) = handle
                && stop_observer(&page, &realm, &handle, &token, deadline)
                    .await
                    .is_err()
            {
                page.session.connection.fence();
            }
            if let Some(capture) = network.as_mut()
                && capture.close(&token, deadline).await.is_err()
            {
                page.session.connection.fence();
            }
        });
    }
}

async fn stop_observer(
    page: &Page,
    realm: &str,
    handle: &str,
    token: &CancellationToken,
    deadline: Instant,
) -> Result<()> {
    let result=page.command("script.callFunction",json!({"target":{"realm":realm},"functionDeclaration":"observer=>observer.stop()","arguments":[{"handle":handle}],"awaitPromise":false,"resultOwnership":"none"}),token,deadline).await.map_err(map_bidi)?;
    if result.get("type").and_then(Value::as_str) != Some("success") {
        return Err(lost("DOM observer cleanup failed"));
    }
    page.command(
        "script.disown",
        json!({"target":{"realm":realm},"handles":[handle]}),
        token,
        deadline,
    )
    .await
    .map_err(map_bidi)?;
    Ok(())
}

fn operation_deadline() -> Result<Instant> {
    Instant::now()
        .checked_add(Duration::from_secs(30))
        .ok_or_else(|| lost("deadline overflow"))
}
fn lost(reason: &str) -> VoidCrawlError {
    VoidCrawlError::PageError(format!("observation watch incomplete: {reason}"))
}

const DOM_OBSERVER: &str = r#"notify=>{
    let active=true,queued=false,sequence=0;
    const hint=()=>{if(!active||queued)return;queued=true;queueMicrotask(()=>{queued=false;if(active)notify(++sequence)})};
    const observer=new MutationObserver(hint);
    observer.observe(document,{subtree:true,childList:true,attributes:true,characterData:true});
    const events=['input','change','focusin','focusout','click','scroll','load','animationend','transitionend'];
    for(const event of events)document.addEventListener(event,hint,true);
    window.addEventListener('resize',hint,true);window.addEventListener('scroll',hint,true);
    return {stop(){active=false;observer.disconnect();for(const event of events)document.removeEventListener(event,hint,true);window.removeEventListener('resize',hint,true);window.removeEventListener('scroll',hint,true);return true}};
}"#;

#[cfg(test)]
mod tests;
