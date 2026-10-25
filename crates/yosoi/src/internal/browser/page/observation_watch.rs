//! Event-driven, bounded notifications used by repeated browser assertions.
//!
//! The watch only reports change hints and bounded request metadata. DOM, AX,
//! and response-body reads stay explicit Page operations so callers can make
//! them under their normal browser-worker capacity.

use super::{Page, shared::event_listener_config};
use crate::internal::browser::vendor::chromiumoxide::cdp::js_protocol::runtime as js_runtime;
use crate::internal::browser::vendor::chromiumoxide::{
    Page as CdpPage,
    cdp::{
        IntoEventKind,
        browser_protocol::{
            accessibility::{
                DisableParams as AccessibilityDisableParams,
                EnableParams as AccessibilityEnableParams, EventLoadComplete, EventNodesUpdated,
            },
            network::{
                EventLoadingFailed, EventLoadingFinished, EventRequestWillBeSent,
                EventResponseReceived, GetResponseBodyParams, RequestId,
            },
            page::EventFrameNavigated,
        },
        js_protocol::runtime::{
            AddBindingParams, CallFunctionOnParams, EventBindingCalled, ReleaseObjectParams,
            RemoteObjectId, RemoveBindingParams,
        },
    },
    listeners::{EventDelivery, EventOverflowPolicy, EventStream},
};
use crate::internal::browser::{DocumentEpoch, DocumentScope, Result, VoidCrawlError};
use base64::{engine::general_purpose::STANDARD, read::DecoderReader};
use futures::{StreamExt, future::pending};
use serde::{Deserialize, Serialize};
use std::mem as std_mem;
use std::{
    collections::{HashMap, HashSet},
    fmt,
    io::{Cursor, Read},
    sync::{
        Mutex, OnceLock,
        atomic::{AtomicU64, Ordering},
    },
    time::Duration,
};
use tokio::runtime::Handle;
use tokio::time as tokio_time;

const BINDING_NAME: &str = "__yosoi_observation_watch";
const MAX_WATCH_EVENTS: usize = 4_096;
const MAX_WATCH_BYTES: usize = 8 * 1024 * 1024;
const MAX_RESPONSE_BODY_BYTES: usize = 8 * 1024 * 1024;
const MAX_FILTERS: usize = 64;
const MAX_URL_BYTES: usize = 16 * 1024;
const MAX_PROVIDER_EVENT_CAPACITY: usize = 256;

static NEXT_WATCH_ID: AtomicU64 = AtomicU64::new(1);

pub(in crate::internal::browser) fn next_watch_id() -> Result<u64> {
    NEXT_WATCH_ID
        .try_update(Ordering::Relaxed, Ordering::Relaxed, |current| {
            current.checked_add(1)
        })
        .map_err(|_| watch_lost("observation watch identifier space exhausted"))
}
static ACTIVE_WATCHES: OnceLock<Mutex<HashSet<String>>> = OnceLock::new();

/// Selects event sources and bounds listener queues plus retained metadata.
#[derive(Clone)]
pub struct ObservationWatchOptions {
    /// Subscribe to coalesced top-level DOM, interaction, lifecycle, and layout hints.
    pub observe_dom: bool,
    /// Subscribe to page-target AX change hints.
    pub observe_accessibility: bool,
    /// Exact URL and optional method/status filters for response metadata.
    pub response_filters: Vec<ObservationResponseFilter>,
    /// Per-listener queue capacity upper bound and maximum concurrent retained
    /// metadata. Provider queues cap at 256; consumed events free capacity.
    pub max_events: usize,
    /// Bound for filter, pending, early, ignored, and individual emitted metadata.
    /// A response-body read uses its own caller-supplied byte limit.
    pub max_bytes: usize,
}

impl fmt::Debug for ObservationWatchOptions {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ObservationWatchOptions")
            .field("observe_dom", &self.observe_dom)
            .field("observe_accessibility", &self.observe_accessibility)
            .field("response_filter_count", &self.response_filters.len())
            .field("max_events", &self.max_events)
            .field("max_bytes", &self.max_bytes)
            .finish()
    }
}

impl Default for ObservationWatchOptions {
    fn default() -> Self {
        Self {
            observe_dom: true,
            observe_accessibility: false,
            response_filters: Vec::new(),
            max_events: 1_024,
            max_bytes: 256 * 1024,
        }
    }
}

impl ObservationWatchOptions {
    pub(in crate::internal::browser) fn validate(&self) -> Result<usize> {
        if !self.observe_dom && !self.observe_accessibility && self.response_filters.is_empty() {
            return Err(invalid_watch_input("at least one event source is required"));
        }
        if self.max_events == 0 || self.max_events > MAX_WATCH_EVENTS {
            return Err(invalid_watch_input("max_events must be between 1 and 4096"));
        }
        if self.max_bytes == 0 || self.max_bytes > MAX_WATCH_BYTES {
            return Err(invalid_watch_input("max_bytes must be between 1 and 8 MiB"));
        }
        if self.response_filters.len() > MAX_FILTERS {
            return Err(invalid_watch_input("too many response filters"));
        }
        let mut filter_bytes = 0usize;
        for filter in &self.response_filters {
            if filter.url.is_empty() || filter.url.len() > MAX_URL_BYTES {
                return Err(invalid_watch_input(
                    "response filter URL is empty or too large",
                ));
            }
            if filter
                .method
                .as_ref()
                .is_some_and(|method| method.is_empty() || method.len() > 64 || !method.is_ascii())
            {
                return Err(invalid_watch_input("response filter method is invalid"));
            }
            if filter
                .status
                .is_some_and(|status| !(100..=599).contains(&status))
            {
                return Err(invalid_watch_input(
                    "response filter status is outside HTTP range",
                ));
            }
            filter_bytes = filter_bytes
                .checked_add(filter.url.len())
                .and_then(|size| size.checked_add(filter.method.as_ref().map_or(0, String::len)))
                .and_then(|size| size.checked_add(24))
                .ok_or_else(|| invalid_watch_input("response filters exceed byte accounting"))?;
        }
        if filter_bytes > self.max_bytes {
            return Err(invalid_watch_input("response filters exceed max_bytes"));
        }
        Ok(filter_bytes)
    }
}

/// Exact response metadata filter. No glob or substring matching is applied.
#[derive(Clone, PartialEq, Eq)]
pub struct ObservationResponseFilter {
    pub url: String,
    pub method: Option<String>,
    pub status: Option<u16>,
}

impl fmt::Debug for ObservationResponseFilter {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ObservationResponseFilter")
            .field("url", &"<redacted>")
            .field("method", &self.method)
            .field("status", &self.status)
            .finish()
    }
}

impl ObservationResponseFilter {
    pub(in crate::internal::browser) fn matches_request(&self, url: &str, method: &str) -> bool {
        self.url == url
            && self
                .method
                .as_deref()
                .is_none_or(|expected| expected == method)
    }

    pub(in crate::internal::browser) fn matches_response(
        &self,
        url: &str,
        method: &str,
        status: u16,
    ) -> bool {
        self.url == url
            && self
                .method
                .as_deref()
                .is_none_or(|expected| expected == method)
            && self.status.is_none_or(|expected| expected == status)
    }
}

/// Kind of AX notification. AX events only wake the caller; the caller obtains
/// a fresh bounded tree or query under browser-worker capacity.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum AccessibilityChangeKind {
    NodesUpdated,
    LoadComplete,
}

/// One event-driven notification or a completed matching response candidate.
#[derive(Debug, Clone, PartialEq, Eq)]
pub enum ObservationChange {
    DomChanged {
        sequence: u64,
    },
    AccessibilityChanged {
        kind: AccessibilityChangeKind,
        updated_nodes: usize,
    },
    ResponseCompleted(CompletedResponseCandidate),
}

/// Bounded response metadata from a request that began after this watch armed.
///
/// The response request ID is serialized as source evidence; private target and
/// watch identities remain unavailable to consumers.
#[derive(Clone, PartialEq, Eq, Serialize)]
pub struct CompletedResponseCandidate {
    pub request_id: String,
    #[serde(skip)]
    pub(in crate::internal::browser) page_target_id: String,
    #[serde(skip)]
    pub(in crate::internal::browser) watch_id: u64,
    #[serde(skip)]
    pub(in crate::internal::browser) native: bool,
    pub url: String,
    pub method: String,
    pub status: u16,
    pub loader_id: Option<String>,
    pub frame_id: Option<String>,
    pub top_level: bool,
    /// Provider request-start time represented in Unix microseconds. BiDi's
    /// millisecond timestamp is converted without claiming finer precision.
    pub started_at_unix_us: u64,
    pub epoch: DocumentEpoch,
}

impl fmt::Debug for CompletedResponseCandidate {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("CompletedResponseCandidate")
            .field("request_id", &"<opaque>")
            .field("url", &"<redacted>")
            .field("method", &self.method)
            .field("status", &self.status)
            .field("loader_id", &self.loader_id.as_ref().map(|_| "<opaque>"))
            .field("frame_id", &self.frame_id.as_ref().map(|_| "<opaque>"))
            .field("top_level", &self.top_level)
            .field("started_at_unix_us", &self.started_at_unix_us)
            .field("epoch", &self.epoch)
            .finish_non_exhaustive()
    }
}

impl CompletedResponseCandidate {
    pub fn request_id(&self) -> &str {
        &self.request_id
    }

    /// Known watched document epoch, when the attached page has one.
    pub const fn document_epoch(&self) -> Option<u64> {
        match self.epoch {
            DocumentEpoch::Known(epoch) => Some(epoch),
            DocumentEpoch::UnavailableForAttachedPage => None,
        }
    }
}

/// Bounded decoded response bytes. A truncated body cannot confirm a JSON
/// expectation because the caller can see that the source is incomplete.
#[derive(Clone, PartialEq, Eq)]
pub struct ObservationResponseBody {
    pub(in crate::internal::browser) bytes: Vec<u8>,
    pub complete: bool,
}

impl fmt::Debug for ObservationResponseBody {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ObservationResponseBody")
            .field("retained_bytes", &self.bytes.len())
            .field("complete", &self.complete)
            .finish()
    }
}

impl ObservationResponseBody {
    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }
}

/// Acknowledged event subscription set for one page.
///
/// Accessibility notifications have page-target scope and are not correlated
/// with individual OOPIF sessions. The bounded snapshot/query APIs remain
/// top-level unless the caller explicitly selects a frame.
pub struct ObservationWatch {
    page: CdpPage,
    options: ObservationWatchOptions,
    start_scope: DocumentScope,
    start_frame_id: String,
    start_loader_id: String,
    main_context_id: Option<js_runtime::ExecutionContextId>,
    watch_id: u64,
    reservation: Option<PageWatchReservation>,
    dom_observer: Option<RemoteObjectId>,
    remove_binding: bool,
    disable_accessibility: bool,
    frame_navigations: Option<EventStream<EventFrameNavigated>>,
    dom_events: Option<EventStream<EventBindingCalled>>,
    ax_nodes: Option<EventStream<EventNodesUpdated>>,
    ax_load: Option<EventStream<EventLoadComplete>>,
    requests: Option<EventStream<EventRequestWillBeSent>>,
    responses: Option<EventStream<EventResponseReceived>>,
    finished: Option<EventStream<EventLoadingFinished>>,
    failed: Option<EventStream<EventLoadingFailed>>,
    pending_requests: HashMap<String, PendingRequest>,
    early_responses: HashMap<String, EarlyResponse>,
    early_finished: HashSet<String>,
    early_failed: HashSet<String>,
    ignored_requests: IgnoredRequestIds,
    pending_bytes: usize,
    auxiliary_bytes: usize,
    last_dom_sequence: u64,
    active: bool,
    executor: Handle,
}

impl fmt::Debug for ObservationWatch {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ObservationWatch")
            .field("start_epoch", &self.start_scope.epoch)
            .field("pending_response_count", &self.pending_requests.len())
            .field("active", &self.active)
            .finish_non_exhaustive()
    }
}

impl ObservationWatch {
    pub(super) fn belongs_to_page(&self, page: &Page) -> bool {
        self.active && self.page.target_id() == page.inner.target_id()
    }

    /// The document scope observed before installation was activated.
    pub const fn start_scope(&self) -> &DocumentScope {
        &self.start_scope
    }

    /// Raw browser frame ID that anchors top-level response candidates.
    pub fn frame_id(&self) -> &str {
        &self.start_frame_id
    }

    /// Raw document loader ID that anchors top-level response candidates.
    pub fn loader_id(&self) -> &str {
        &self.start_loader_id
    }

    pub const fn document_epoch(&self) -> DocumentEpoch {
        self.start_scope.epoch
    }

    /// Consume the next event without issuing a browser command.
    pub async fn next(&mut self) -> Result<ObservationChange> {
        if !self.active {
            return Err(watch_lost("observation watch is settled"));
        }

        loop {
            match self.next_source_event().await {
                SourceEvent::Dom(delivery) => {
                    if let Some(change) = self.observe_dom_delivery(delivery)? {
                        return Ok(change);
                    }
                }
                SourceEvent::AxNodes(delivery) => match delivery {
                    Some(EventDelivery::Event(event)) => {
                        return self.report_change(
                            ObservationChange::AccessibilityChanged {
                                kind: AccessibilityChangeKind::NodesUpdated,
                                updated_nodes: event.nodes.len(),
                            },
                            16,
                        );
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "AX nodes listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("AX nodes event stream closed")),
                },
                SourceEvent::AxLoad(delivery) => match delivery {
                    Some(EventDelivery::Event(_event)) => {
                        return self.report_change(
                            ObservationChange::AccessibilityChanged {
                                kind: AccessibilityChangeKind::LoadComplete,
                                updated_nodes: 1,
                            },
                            16,
                        );
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "AX load listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("AX load event stream closed")),
                },
                SourceEvent::Request(delivery) => match delivery {
                    Some(EventDelivery::Event(event)) => {
                        if let Some(candidate) = self.observe_request(&event)? {
                            let weight = candidate_weight(&candidate)?;
                            return self.report_change(
                                ObservationChange::ResponseCompleted(candidate),
                                weight,
                            );
                        }
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "network request listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("network request stream closed")),
                },
                SourceEvent::Response(delivery) => match delivery {
                    Some(EventDelivery::Event(event)) => {
                        if let Some(candidate) = self.observe_response(&event)? {
                            let weight = candidate_weight(&candidate)?;
                            return self.report_change(
                                ObservationChange::ResponseCompleted(candidate),
                                weight,
                            );
                        }
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "network response listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("network response stream closed")),
                },
                SourceEvent::Finished(delivery) => match delivery {
                    Some(EventDelivery::Event(event)) => {
                        if let Some(candidate) = self.observe_finished(event.request_id.inner())? {
                            let weight = candidate_weight(&candidate)?;
                            return self.report_change(
                                ObservationChange::ResponseCompleted(candidate),
                                weight,
                            );
                        }
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "network completion listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("network completion stream closed")),
                },
                SourceEvent::Failed(delivery) => match delivery {
                    Some(EventDelivery::Event(event)) => {
                        self.observe_failed(event.request_id.inner())?;
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "network failure listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("network failure stream closed")),
                },
                SourceEvent::FrameNavigation(delivery) => match delivery {
                    Some(EventDelivery::Event(event)) => {
                        if event.frame.parent_id.is_none()
                            && (event.frame.id.inner() != &self.start_frame_id
                                || event.frame.loader_id.inner() != &self.start_loader_id)
                        {
                            return Err(watch_lost(
                                "top-level document navigated while the watch was active",
                            ));
                        }
                    }
                    Some(EventDelivery::Lagged { dropped }) => {
                        return Err(watch_lost(&format!(
                            "frame navigation listener lost {} event(s)",
                            dropped.get()
                        )));
                    }
                    None => return Err(watch_lost("frame navigation stream closed")),
                },
            }
        }
    }

    fn observe_dom_delivery(
        &mut self,
        delivery: Option<EventDelivery<EventBindingCalled>>,
    ) -> Result<Option<ObservationChange>> {
        match delivery {
            Some(EventDelivery::Event(event)) => {
                if event.name != BINDING_NAME
                    || self
                        .main_context_id
                        .as_ref()
                        .is_some_and(|context| context != &event.execution_context_id)
                {
                    return Ok(None);
                }
                if event.payload.len() > 128 {
                    return Err(watch_lost("DOM notification exceeded its bound"));
                }
                let notification: DomNotification = serde_json::from_str(&event.payload)
                    .map_err(|_| watch_lost("DOM notification was malformed"))?;
                if notification.watch_id != self.watch_id {
                    return Ok(None);
                }
                let expected_sequence = self
                    .last_dom_sequence
                    .checked_add(1)
                    .ok_or_else(|| watch_lost("DOM notification sequence exhausted"))?;
                if notification.sequence != expected_sequence {
                    return Err(watch_lost("DOM notification sequence was incomplete"));
                }
                self.last_dom_sequence = notification.sequence;
                self.report_change(
                    ObservationChange::DomChanged {
                        sequence: notification.sequence,
                    },
                    16,
                )
                .map(Some)
            }
            Some(EventDelivery::Lagged { dropped }) => Err(watch_lost(&format!(
                "DOM notification listener lost {} event(s)",
                dropped.get()
            ))),
            None => Err(watch_lost("DOM notification stream closed")),
        }
    }

    /// Stop the JS observer, unregister its binding, and disable AX events.
    /// Repeated calls are harmless; all cleanup commands have a one-second cap.
    pub async fn settle(&mut self) -> Result<()> {
        if !self.active {
            return Ok(());
        }
        cleanup_watch(
            &self.page,
            self.dom_observer.clone(),
            self.remove_binding.then_some(self.watch_id),
            self.remove_binding,
            self.disable_accessibility,
        )
        .await?;
        self.active = false;
        self.drop_event_streams();
        drop(self.dom_observer.take());
        self.remove_binding = false;
        self.disable_accessibility = false;
        drop(self.reservation.take());
        Ok(())
    }

    async fn next_source_event(&mut self) -> SourceEvent {
        tokio::select! {
            biased;
            event = next_delivery(&mut self.requests) => SourceEvent::Request(event),
            event = next_delivery(&mut self.responses) => SourceEvent::Response(event),
            event = next_delivery(&mut self.finished) => SourceEvent::Finished(event),
            event = next_delivery(&mut self.failed) => SourceEvent::Failed(event),
            event = next_delivery(&mut self.frame_navigations) => SourceEvent::FrameNavigation(event),
            event = next_delivery(&mut self.dom_events) => SourceEvent::Dom(event),
            event = next_delivery(&mut self.ax_nodes) => SourceEvent::AxNodes(event),
            event = next_delivery(&mut self.ax_load) => SourceEvent::AxLoad(event),
        }
    }

    fn report_change(
        &self,
        change: ObservationChange,
        byte_weight: usize,
    ) -> Result<ObservationChange> {
        if !event_weight_fits(self.options.max_bytes, byte_weight) {
            return Err(watch_lost("one observation event exceeded max_bytes"));
        }
        Ok(change)
    }

    fn observe_request(
        &mut self,
        event: &EventRequestWillBeSent,
    ) -> Result<Option<CompletedResponseCandidate>> {
        let request_id = event.request_id.inner().clone();
        self.remove_pending(&request_id)?;
        self.remove_ignored_request(&request_id)?;
        let early = self.take_early_state(&request_id)?;
        let matches_filter = self
            .options
            .response_filters
            .iter()
            .any(|filter| filter.matches_request(&event.request.url, &event.request.method));
        if !matches_filter {
            if !early.finished && !early.failed {
                self.insert_ignored_request(&request_id)?;
            }
            return Ok(None);
        }

        if early.failed {
            return Ok(None);
        }
        let started_at_unix_us = unix_micros_from_seconds(*event.wall_time.inner())?;

        let mut pending = PendingRequest {
            request_id: request_id.clone(),
            url: event.request.url.clone(),
            method: event.request.method.clone(),
            loader_id: nonempty(event.loader_id.inner()),
            frame_id: event.frame_id.as_ref().map(|frame| frame.inner().clone()),
            started_at_unix_us,
            status: None,
            finished: early.finished,
        };
        if let Some(response) = early.response {
            let response_status = u16::try_from(response.status).ok();
            if response.url != pending.url
                || response_status.is_none()
                || !self.options.response_filters.iter().any(|filter| {
                    response_status.is_some_and(|status| {
                        filter.matches_response(&response.url, &pending.method, status)
                    })
                })
            {
                if !pending.finished {
                    self.insert_ignored_request(&request_id)?;
                }
                return Ok(None);
            }
            pending.status = response_status;
        }

        let weight = pending_weight(&pending)?;
        self.ensure_metadata_capacity(1, weight)?;
        self.pending_bytes = self
            .pending_bytes
            .checked_add(weight)
            .ok_or_else(|| watch_lost("pending response byte count overflowed"))?;
        self.pending_requests.insert(request_id.clone(), pending);
        self.complete_pending(&request_id)
    }

    fn observe_response(
        &mut self,
        event: &EventResponseReceived,
    ) -> Result<Option<CompletedResponseCandidate>> {
        let request_id = event.request_id.inner().as_str();
        if self.ignored_requests.ids.contains(request_id) {
            return Ok(None);
        }
        if let Some(pending) = self.pending_requests.get(request_id) {
            let status = u16::try_from(event.response.status).ok();
            let matches = status.is_some()
                && event.response.url == pending.url
                && self.options.response_filters.iter().any(|filter| {
                    status.is_some_and(|status| {
                        filter.matches_response(&event.response.url, &pending.method, status)
                    })
                });
            if !matches {
                let pending = self.remove_pending(request_id)?;
                self.remove_early_state(request_id)?;
                if pending.is_some_and(|pending| !pending.finished) {
                    self.insert_ignored_request(request_id)?;
                }
                return Ok(None);
            }
            if let Some(current) = self.pending_requests.get_mut(request_id) {
                current.status = status;
            }
            return self.complete_pending(request_id);
        }
        self.store_early_response(request_id, &event.response.url, event.response.status)?;
        Ok(None)
    }

    fn observe_finished(&mut self, request_id: &str) -> Result<Option<CompletedResponseCandidate>> {
        if self.remove_ignored_request(request_id)? {
            return Ok(None);
        }
        if let Some(pending) = self.pending_requests.get_mut(request_id) {
            pending.finished = true;
            return self.complete_pending(request_id);
        }
        self.store_early_mark(request_id, false)?;
        Ok(None)
    }

    fn observe_failed(&mut self, request_id: &str) -> Result<()> {
        if self.remove_ignored_request(request_id)? {
            return Ok(());
        }
        if self.pending_requests.contains_key(request_id) {
            self.remove_pending(request_id)?;
            self.remove_early_state(request_id)?;
            return Ok(());
        }
        self.remove_early_response(request_id)?;
        let _ = self.take_early_mark(request_id, false)?;
        self.store_early_mark(request_id, true)
    }

    fn complete_pending(&mut self, request_id: &str) -> Result<Option<CompletedResponseCandidate>> {
        let ready = self
            .pending_requests
            .get(request_id)
            .is_some_and(|pending| pending.finished && pending.status.is_some());
        if !ready {
            return Ok(None);
        }
        let Some(pending) = self.remove_pending(request_id)? else {
            return Ok(None);
        };
        let Some(status) = pending.status else {
            return Ok(None);
        };
        let top_level = pending.frame_id.as_deref() == Some(self.start_frame_id.as_str())
            && pending.loader_id.as_deref() == Some(self.start_loader_id.as_str());
        if !top_level {
            return Ok(None);
        }
        let page_target_id = self
            .reservation
            .as_ref()
            .map(|reservation| reservation.target_id.clone())
            .ok_or_else(|| watch_lost("response candidate lost its page reservation"))?;
        Ok(Some(CompletedResponseCandidate {
            request_id: pending.request_id,
            page_target_id,
            watch_id: self.watch_id,
            native: false,
            url: pending.url,
            method: pending.method,
            status,
            loader_id: pending.loader_id,
            frame_id: pending.frame_id,
            top_level,
            started_at_unix_us: pending.started_at_unix_us,
            epoch: self.start_scope.epoch,
        }))
    }

    fn remove_pending(&mut self, request_id: &str) -> Result<Option<PendingRequest>> {
        let pending = self.pending_requests.remove(request_id);
        if let Some(entry) = &pending {
            let weight = pending_weight(entry)?;
            self.pending_bytes = self
                .pending_bytes
                .checked_sub(weight)
                .ok_or_else(|| watch_lost("pending response byte accounting was inconsistent"))?;
        }
        Ok(pending)
    }

    fn store_early_response(&mut self, request_id: &str, url: &str, status: i64) -> Result<()> {
        self.remove_early_response(request_id)?;
        let weight = early_response_weight(request_id, url)?;
        self.ensure_metadata_capacity(1, weight)?;
        self.auxiliary_bytes = self
            .auxiliary_bytes
            .checked_add(weight)
            .ok_or_else(|| watch_lost("early response byte count overflowed"))?;
        self.early_responses.insert(
            request_id.to_owned(),
            EarlyResponse {
                url: url.to_owned(),
                status,
            },
        );
        Ok(())
    }

    fn store_early_mark(&mut self, request_id: &str, failed: bool) -> Result<()> {
        let exists = if failed {
            self.early_failed.contains(request_id)
        } else {
            self.early_finished.contains(request_id)
        };
        if exists {
            return Ok(());
        }
        let weight = early_mark_weight(request_id)?;
        self.ensure_metadata_capacity(1, weight)?;
        self.auxiliary_bytes = self
            .auxiliary_bytes
            .checked_add(weight)
            .ok_or_else(|| watch_lost("early request byte count overflowed"))?;
        if failed {
            self.early_failed.insert(request_id.to_owned());
        } else {
            self.early_finished.insert(request_id.to_owned());
        }
        Ok(())
    }

    fn take_early_response(&mut self, request_id: &str) -> Result<Option<EarlyResponse>> {
        let response = self.early_responses.remove(request_id);
        if let Some(response) = &response {
            self.subtract_auxiliary(early_response_weight(request_id, &response.url)?)?;
        }
        Ok(response)
    }

    fn take_early_mark(&mut self, request_id: &str, failed: bool) -> Result<bool> {
        let removed = if failed {
            self.early_failed.remove(request_id)
        } else {
            self.early_finished.remove(request_id)
        };
        if removed {
            self.subtract_auxiliary(early_mark_weight(request_id)?)?;
        }
        Ok(removed)
    }

    fn remove_early_response(&mut self, request_id: &str) -> Result<()> {
        self.take_early_response(request_id).map(|_| ())
    }

    fn take_early_state(&mut self, request_id: &str) -> Result<EarlyState> {
        Ok(EarlyState {
            response: self.take_early_response(request_id)?,
            finished: self.take_early_mark(request_id, false)?,
            failed: self.take_early_mark(request_id, true)?,
        })
    }

    fn remove_early_state(&mut self, request_id: &str) -> Result<()> {
        let _ = self.take_early_state(request_id)?;
        Ok(())
    }

    fn ensure_metadata_capacity(&self, extra_items: usize, extra_bytes: usize) -> Result<()> {
        let item_count = self
            .pending_requests
            .len()
            .checked_add(self.early_responses.len())
            .and_then(|count| count.checked_add(self.early_finished.len()))
            .and_then(|count| count.checked_add(self.early_failed.len()))
            .and_then(|count| count.checked_add(self.ignored_requests.ids.len()))
            .and_then(|count| count.checked_add(extra_items))
            .ok_or_else(|| watch_lost("network metadata item count overflowed"))?;
        let retained = self
            .pending_bytes
            .checked_add(self.ignored_requests.retained_bytes)
            .and_then(|bytes| bytes.checked_add(self.auxiliary_bytes))
            .and_then(|bytes| bytes.checked_add(extra_bytes))
            .ok_or_else(|| watch_lost("network metadata byte count overflowed"))?;
        if item_count > self.options.max_events || retained > self.options.max_bytes {
            return Err(watch_lost(
                "network metadata exceeded its configured event or byte bound",
            ));
        }
        Ok(())
    }

    fn insert_ignored_request(&mut self, request_id: &str) -> Result<()> {
        let other_items = self
            .pending_requests
            .len()
            .checked_add(self.early_responses.len())
            .and_then(|count| count.checked_add(self.early_finished.len()))
            .and_then(|count| count.checked_add(self.early_failed.len()))
            .ok_or_else(|| watch_lost("network metadata item count overflowed"))?;
        let other_bytes = self
            .pending_bytes
            .checked_add(self.auxiliary_bytes)
            .ok_or_else(|| watch_lost("network metadata byte count overflowed"))?;
        insert_bounded_id(
            &mut self.ignored_requests.ids,
            &mut self.ignored_requests.retained_bytes,
            request_id,
            other_items,
            other_bytes,
            self.options.max_events,
            self.options.max_bytes,
        )
    }

    fn remove_ignored_request(&mut self, request_id: &str) -> Result<bool> {
        remove_bounded_id(
            &mut self.ignored_requests.ids,
            &mut self.ignored_requests.retained_bytes,
            request_id,
        )
    }

    fn subtract_auxiliary(&mut self, bytes: usize) -> Result<()> {
        self.auxiliary_bytes = self
            .auxiliary_bytes
            .checked_sub(bytes)
            .ok_or_else(|| watch_lost("early response byte accounting was inconsistent"))?;
        Ok(())
    }

    fn drop_event_streams(&mut self) {
        self.frame_navigations.take();
        self.dom_events.take();
        self.ax_nodes.take();
        self.ax_load.take();
        self.requests.take();
        self.responses.take();
        self.finished.take();
        self.failed.take();
        self.pending_requests.clear();
        self.early_responses.clear();
        self.early_finished.clear();
        self.early_failed.clear();
        self.ignored_requests.ids.clear();
        self.ignored_requests.retained_bytes = 0;
        self.pending_bytes = 0;
        self.auxiliary_bytes = 0;
    }
}

impl Drop for ObservationWatch {
    fn drop(&mut self) {
        if !self.active {
            return;
        }
        self.active = false;
        self.drop_event_streams();
        let page = self.page.clone();
        let object = self.dom_observer.take();
        let watch_id = self.remove_binding.then_some(self.watch_id);
        let remove_binding = self.remove_binding;
        let disable_accessibility = self.disable_accessibility;
        let reservation = self.reservation.take();
        let executor = self.executor.clone();
        executor.spawn(async move {
            let _reservation = reservation;
            let _ = cleanup_watch(
                &page,
                object,
                watch_id,
                remove_binding,
                disable_accessibility,
            )
            .await;
        });
    }
}

impl Page {
    /// Register every event stream, enable selected domains, and acknowledge
    /// observer installation before returning. Call this before the triggering
    /// action so no initial response or DOM mutation can race registration.
    pub async fn start_observation_watch(
        &self,
        options: ObservationWatchOptions,
    ) -> Result<ObservationWatch> {
        let retained_filter_bytes = options.validate()?;
        self.ensure_active().await?;
        let executor = Handle::try_current()
            .map_err(|_| watch_lost("observation watch requires an async runtime"))?;
        let target_id = self.inner.target_id().inner().clone();
        let reservation = PageWatchReservation::acquire(target_id.clone())?;
        let capacity = provider_event_capacity(options.max_events);
        let listener_config = event_listener_config(capacity, EventOverflowPolicy::Close);

        // Scope and all event listeners are fixed before any selected domain
        // is activated. The final identity read detects a navigation mid-arm.
        let frame_navigations = self
            .inner
            .event_listener::<EventFrameNavigated>(listener_config)
            .await
            .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        let start_identity = self.top_level_document_identity().await?;
        let start_scope = self.scope_for_identity(&start_identity, false)?;

        let dom_events = if options.observe_dom {
            Some(
                self.inner
                    .event_listener::<EventBindingCalled>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            )
        } else {
            None
        };
        let (ax_nodes, ax_load) = if options.observe_accessibility {
            (
                Some(
                    self.inner
                        .event_listener::<EventNodesUpdated>(listener_config)
                        .await
                        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
                ),
                Some(
                    self.inner
                        .event_listener::<EventLoadComplete>(listener_config)
                        .await
                        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
                ),
            )
        } else {
            (None, None)
        };
        let (requests, responses, finished, failed) = if options.response_filters.is_empty() {
            (None, None, None, None)
        } else {
            (
                Some(
                    self.inner
                        .event_listener::<EventRequestWillBeSent>(listener_config)
                        .await
                        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
                ),
                Some(
                    self.inner
                        .event_listener::<EventResponseReceived>(listener_config)
                        .await
                        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
                ),
                Some(
                    self.inner
                        .event_listener::<EventLoadingFinished>(listener_config)
                        .await
                        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
                ),
                Some(
                    self.inner
                        .event_listener::<EventLoadingFailed>(listener_config)
                        .await
                        .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
                ),
            )
        };

        let mut setup = SetupCleanup::new(self.inner.clone(), executor.clone(), reservation);
        let watch_id = next_watch_id()?;
        setup.watch_id = Some(watch_id);
        if options.observe_dom {
            self.ensure_runtime_enabled().await?;
            self.wait_for_main_execution_context().await?;
            let main_context_id = self
                .inner
                .execution_context()
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?
                .ok_or_else(|| watch_lost("main execution context was unavailable"))?;
            let add_binding = AddBindingParams::builder()
                .name(BINDING_NAME)
                .build()
                .map_err(VoidCrawlError::JsEvalError)?;
            setup.remove_binding = true;
            self.inner
                .execute(add_binding)
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
            let source = dom_observer_source(watch_id)?;
            let params = js_runtime::EvaluateParams::builder()
                .expression(source)
                .await_promise(false)
                .return_by_value(false)
                .build()
                .map_err(VoidCrawlError::JsEvalError)?;
            let evaluated = self
                .inner
                .evaluate_expression(params)
                .await
                .map_err(|error| VoidCrawlError::JsEvalError(error.to_string()))?;
            setup.dom_observer.clone_from(&evaluated.object().object_id);
            if setup.dom_observer.is_none() {
                return Err(watch_lost("DOM observer installation returned no handle"));
            }
            setup.main_context_id = Some(main_context_id);
        }
        if !options.response_filters.is_empty() {
            self.ensure_network_enabled().await?;
        }
        if options.observe_accessibility {
            setup.disable_accessibility = true;
            self.inner
                .execute(AccessibilityEnableParams::default())
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?;
        }

        let current_identity = self.top_level_document_identity().await?;
        if !start_identity.same_document(&current_identity) {
            return Err(watch_lost(
                "document scope changed during observer installation",
            ));
        }
        let current_scope = self.scope_for_identity(&current_identity, false)?;
        if !same_scope(&start_scope, &current_scope) {
            return Err(watch_lost(
                "document scope changed during observer installation",
            ));
        }

        let watch_id = setup
            .watch_id
            .ok_or_else(|| watch_lost("observation watch identifier was unavailable"))?;
        let watch = ObservationWatch {
            page: self.inner.clone(),
            options,
            start_scope,
            start_frame_id: start_identity.frame_id.inner().clone(),
            start_loader_id: start_identity.loader_id,
            main_context_id: setup.main_context_id.take(),
            watch_id,
            reservation: setup.reservation.take(),
            dom_observer: setup.dom_observer.take(),
            remove_binding: std_mem::replace(&mut setup.remove_binding, false),
            disable_accessibility: std_mem::replace(&mut setup.disable_accessibility, false),
            frame_navigations: Some(frame_navigations),
            dom_events,
            ax_nodes,
            ax_load,
            requests,
            responses,
            finished,
            failed,
            pending_requests: HashMap::new(),
            early_responses: HashMap::new(),
            early_finished: HashSet::new(),
            early_failed: HashSet::new(),
            ignored_requests: IgnoredRequestIds::default(),
            pending_bytes: 0,
            auxiliary_bytes: retained_filter_bytes,
            last_dom_sequence: 0,
            active: true,
            executor,
        };
        setup.committed = true;
        Ok(watch)
    }

    /// Fetch a completed response candidate's body under the caller's worker
    /// permit. The returned decoded bytes never exceed max_bytes.
    pub async fn capture_observation_response_body(
        &self,
        candidate: &CompletedResponseCandidate,
        max_bytes: usize,
    ) -> Result<ObservationResponseBody> {
        self.ensure_active().await?;
        if candidate.native
            || candidate.page_target_id != self.inner.target_id().inner().as_str()
            || candidate.watch_id == 0
        {
            return Err(watch_lost("response candidate belongs to another page"));
        }
        if max_bytes == 0 || max_bytes > MAX_RESPONSE_BODY_BYTES {
            return Err(invalid_watch_input(
                "response body limit must be between 1 and 8 MiB",
            ));
        }
        let request_id = RequestId::new(candidate.request_id.clone());
        let response = self
            .inner
            .execute(GetResponseBodyParams::new(request_id))
            .await
            .map_err(|error| VoidCrawlError::ResponseBody(error.to_string()))?;
        let probe_limit = max_bytes
            .checked_add(1)
            .ok_or_else(|| invalid_watch_input("response body limit overflowed"))?;
        let read_limit = u64::try_from(probe_limit)
            .map_err(|_| invalid_watch_input("response body limit is unsupported"))?;
        let mut bytes = Vec::with_capacity(probe_limit.min(64 * 1024));
        if response.result.base64_encoded {
            let decoder = DecoderReader::new(response.result.body.as_bytes(), &STANDARD);
            decoder
                .take(read_limit)
                .read_to_end(&mut bytes)
                .map_err(|error| VoidCrawlError::ResponseBody(error.to_string()))?;
        } else {
            Cursor::new(response.result.body.as_bytes())
                .take(read_limit)
                .read_to_end(&mut bytes)
                .map_err(|error| VoidCrawlError::ResponseBody(error.to_string()))?;
        }
        let complete = bytes.len() <= max_bytes;
        if !complete {
            bytes.truncate(max_bytes);
        }
        Ok(ObservationResponseBody { bytes, complete })
    }
}

struct PendingRequest {
    request_id: String,
    url: String,
    method: String,
    loader_id: Option<String>,
    frame_id: Option<String>,
    started_at_unix_us: u64,
    status: Option<u16>,
    finished: bool,
}

struct EarlyResponse {
    url: String,
    status: i64,
}

#[derive(Default)]
struct IgnoredRequestIds {
    ids: HashSet<String>,
    retained_bytes: usize,
}

struct EarlyState {
    response: Option<EarlyResponse>,
    finished: bool,
    failed: bool,
}

fn pending_weight(request: &PendingRequest) -> Result<usize> {
    [
        request.request_id.len(),
        request.url.len(),
        request.method.len(),
        std_mem::size_of::<u64>(),
    ]
    .into_iter()
    .chain([
        request.loader_id.as_ref().map_or(0, String::len),
        request.frame_id.as_ref().map_or(0, String::len),
    ])
    .try_fold(96usize, usize::checked_add)
    .ok_or_else(|| watch_lost("network metadata size overflowed"))
}

fn candidate_weight(candidate: &CompletedResponseCandidate) -> Result<usize> {
    [
        candidate.request_id.len(),
        candidate.url.len(),
        candidate.method.len(),
        std_mem::size_of::<u64>(),
        candidate.loader_id.as_ref().map_or(0, String::len),
        candidate.frame_id.as_ref().map_or(0, String::len),
    ]
    .into_iter()
    .try_fold(96usize, usize::checked_add)
    .ok_or_else(|| watch_lost("response candidate size overflowed"))
}

fn early_response_weight(request_id: &str, url: &str) -> Result<usize> {
    request_id
        .len()
        .checked_add(url.len())
        .and_then(|size| size.checked_add(96))
        .ok_or_else(|| watch_lost("early response size overflowed"))
}

fn early_mark_weight(request_id: &str) -> Result<usize> {
    request_id
        .len()
        .checked_add(64)
        .ok_or_else(|| watch_lost("early request marker size overflowed"))
}

const fn event_weight_fits(max_bytes: usize, byte_weight: usize) -> bool {
    byte_weight <= max_bytes
}

const fn provider_event_capacity(max_events: usize) -> usize {
    if max_events < MAX_PROVIDER_EVENT_CAPACITY {
        max_events
    } else {
        MAX_PROVIDER_EVENT_CAPACITY
    }
}

fn insert_bounded_id(
    ids: &mut HashSet<String>,
    retained_bytes: &mut usize,
    request_id: &str,
    other_items: usize,
    other_bytes: usize,
    max_events: usize,
    max_bytes: usize,
) -> Result<()> {
    if ids.contains(request_id) {
        return Ok(());
    }
    let item_count = other_items
        .checked_add(ids.len())
        .and_then(|count| count.checked_add(1))
        .ok_or_else(|| watch_lost("ignored request count overflowed"))?;
    let marker_bytes = early_mark_weight(request_id)?;
    let total_bytes = other_bytes
        .checked_add(*retained_bytes)
        .and_then(|bytes| bytes.checked_add(marker_bytes))
        .ok_or_else(|| watch_lost("ignored request byte count overflowed"))?;
    if item_count > max_events || total_bytes > max_bytes {
        return Err(watch_lost(
            "ignored request metadata exceeded its configured bound",
        ));
    }
    *retained_bytes = (*retained_bytes)
        .checked_add(marker_bytes)
        .ok_or_else(|| watch_lost("ignored request byte count overflowed"))?;
    ids.insert(request_id.to_owned());
    Ok(())
}

fn remove_bounded_id(
    ids: &mut HashSet<String>,
    retained_bytes: &mut usize,
    request_id: &str,
) -> Result<bool> {
    if !ids.remove(request_id) {
        return Ok(false);
    }
    *retained_bytes = (*retained_bytes)
        .checked_sub(early_mark_weight(request_id)?)
        .ok_or_else(|| watch_lost("ignored request byte accounting was inconsistent"))?;
    Ok(true)
}

fn unix_micros_from_seconds(seconds: f64) -> Result<u64> {
    if !seconds.is_finite() || seconds < 0.0 {
        return Err(watch_lost(
            "request wallTime was not a finite Unix timestamp",
        ));
    }
    let duration = Duration::try_from_secs_f64(seconds)
        .map_err(|_| watch_lost("request wallTime was outside the supported range"))?;
    let micros = u64::try_from(duration.as_micros())
        .map_err(|_| watch_lost("request wallTime exceeded Unix microsecond range"))?;
    if micros == 0 {
        return Err(watch_lost(
            "request wallTime had no positive Unix microsecond timestamp",
        ));
    }
    Ok(micros)
}

fn nonempty(value: &str) -> Option<String> {
    (!value.is_empty()).then(|| value.to_owned())
}

fn same_scope(left: &DocumentScope, right: &DocumentScope) -> bool {
    left.frame_id == right.frame_id
        && left.epoch == right.epoch
        && left.frame == right.frame
        && left.url == right.url
}

fn dom_observer_source(watch_id: u64) -> Result<String> {
    let binding = serde_json::to_string(BINDING_NAME)
        .map_err(|_| watch_lost("binding name could not be encoded"))?;
    Ok(format!(
        r#"(() => {{
            const binding = globalThis[{binding}];
            if (typeof binding !== 'function') throw new Error('binding unavailable');
            const registryKey = Symbol.for('yosoi.observation.watchers');
            let registry = globalThis[registryKey];
            if (!(registry instanceof Map)) {{
                registry = new Map();
                Object.defineProperty(globalThis, registryKey, {{value:registry,configurable:true}});
            }}
            let active = true;
            let pending = false;
            let sequence = 0;
            const notify = () => {{
                if (!active || pending) return;
                pending = true;
                queueMicrotask(() => {{
                    pending = false;
                    if (active) binding(JSON.stringify({{watch_id:{watch_id},sequence:++sequence}}));
                }});
            }};
            const documentEvents = ['load', 'transitionend', 'animationend', 'input', 'change', 'focusin', 'focusout'];
            const observer = new MutationObserver(notify);
            observer.observe(document, {{subtree:true,childList:true,attributes:true,characterData:true}});
            for (const event of documentEvents) document.addEventListener(event, notify, true);
            window.addEventListener('resize', notify);
            const state = {{stop() {{
                if (!active) return;
                active = false;
                observer.disconnect();
                for (const event of documentEvents) document.removeEventListener(event, notify, true);
                window.removeEventListener('resize', notify);
                registry.delete({watch_id});
                if (registry.size === 0 && globalThis[registryKey] === registry) delete globalThis[registryKey];
            }}}};
            registry.set({watch_id}, state);
            return state;
        }})()"#
    ))
}

#[derive(Deserialize)]
struct DomNotification {
    watch_id: u64,
    sequence: u64,
}

enum SourceEvent {
    Dom(Option<EventDelivery<EventBindingCalled>>),
    AxNodes(Option<EventDelivery<EventNodesUpdated>>),
    AxLoad(Option<EventDelivery<EventLoadComplete>>),
    Request(Option<EventDelivery<EventRequestWillBeSent>>),
    Response(Option<EventDelivery<EventResponseReceived>>),
    Finished(Option<EventDelivery<EventLoadingFinished>>),
    Failed(Option<EventDelivery<EventLoadingFailed>>),
    FrameNavigation(Option<EventDelivery<EventFrameNavigated>>),
}

async fn next_delivery<T>(stream: &mut Option<EventStream<T>>) -> Option<EventDelivery<T>>
where
    T: IntoEventKind + Send + Sync + Unpin + 'static,
{
    match stream {
        Some(stream) => stream.next().await,
        None => pending().await,
    }
}

struct PageWatchReservation {
    target_id: String,
}

impl PageWatchReservation {
    fn acquire(target_id: String) -> Result<Self> {
        let active = ACTIVE_WATCHES.get_or_init(|| Mutex::new(HashSet::new()));
        let mut active = active
            .lock()
            .map_err(|_| watch_lost("page watch reservation lock was poisoned"))?;
        if !active.insert(target_id.clone()) {
            return Err(watch_lost(
                "this page already has an active observation watch",
            ));
        }
        drop(active);
        Ok(Self { target_id })
    }
}

impl Drop for PageWatchReservation {
    fn drop(&mut self) {
        if let Some(active) = ACTIVE_WATCHES.get()
            && let Ok(mut active) = active.lock()
        {
            active.remove(&self.target_id);
        }
    }
}

struct SetupCleanup {
    page: CdpPage,
    executor: Handle,
    reservation: Option<PageWatchReservation>,
    dom_observer: Option<RemoteObjectId>,
    remove_binding: bool,
    disable_accessibility: bool,
    watch_id: Option<u64>,
    main_context_id: Option<js_runtime::ExecutionContextId>,
    committed: bool,
}

impl SetupCleanup {
    const fn new(page: CdpPage, executor: Handle, reservation: PageWatchReservation) -> Self {
        Self {
            page,
            executor,
            reservation: Some(reservation),
            dom_observer: None,
            remove_binding: false,
            disable_accessibility: false,
            watch_id: None,
            main_context_id: None,
            committed: false,
        }
    }
}

impl Drop for SetupCleanup {
    fn drop(&mut self) {
        if self.committed {
            return;
        }
        let page = self.page.clone();
        let object = self.dom_observer.take();
        let watch_id = self.remove_binding.then_some(self.watch_id).flatten();
        let remove_binding = self.remove_binding;
        let disable_accessibility = self.disable_accessibility;
        let reservation = self.reservation.take();
        self.executor.spawn(async move {
            let _reservation = reservation;
            let _ = cleanup_watch(
                &page,
                object,
                watch_id,
                remove_binding,
                disable_accessibility,
            )
            .await;
        });
    }
}

async fn cleanup_watch(
    page: &CdpPage,
    object: Option<RemoteObjectId>,
    watch_id: Option<u64>,
    remove_binding: bool,
    disable_accessibility: bool,
) -> Result<()> {
    let mut first_error = None;
    if let Some(watch_id) = watch_id {
        let source = format!(
            "(() => {{ const registry = globalThis[Symbol.for('yosoi.observation.watchers')]; const state = registry instanceof Map ? registry.get({watch_id}) : undefined; if (state) state.stop(); return !!state; }})()"
        );
        let params = js_runtime::EvaluateParams::builder()
            .expression(source)
            .await_promise(false)
            .return_by_value(true)
            .build()
            .map_err(VoidCrawlError::JsEvalError);
        match params {
            Ok(params) => {
                if let Err(error) =
                    tokio_time::timeout(Duration::from_secs(1), page.execute(params))
                        .await
                        .map_err(|_| watch_lost("DOM observer registry cleanup timed out"))
                        .and_then(|result| {
                            result.map_err(|error| VoidCrawlError::PageError(error.to_string()))
                        })
                {
                    first_error = Some(error);
                }
            }
            Err(error) => first_error = Some(error),
        }
    }
    if let Some(object) = object {
        let stop = CallFunctionOnParams::builder()
            .function_declaration("function() { this.stop(); return true; }")
            .object_id(object.clone())
            .return_by_value(true)
            .build()
            .map_err(VoidCrawlError::JsEvalError);
        match stop {
            Ok(params) => {
                if let Err(error) =
                    tokio_time::timeout(Duration::from_secs(1), page.execute(params))
                        .await
                        .map_err(|_| watch_lost("DOM observer cleanup timed out"))
                        .and_then(|result| {
                            result.map_err(|error| VoidCrawlError::PageError(error.to_string()))
                        })
                {
                    first_error = Some(error);
                }
            }
            Err(error) => first_error = Some(error),
        }
        if let Err(error) = tokio_time::timeout(
            Duration::from_secs(1),
            page.execute(ReleaseObjectParams::new(object)),
        )
        .await
        .map_err(|_| watch_lost("observer handle release timed out"))
        .and_then(|result| result.map_err(|error| VoidCrawlError::PageError(error.to_string())))
            && first_error.is_none()
        {
            first_error = Some(error);
        }
    }
    if remove_binding
        && let Err(error) = tokio_time::timeout(
            Duration::from_secs(1),
            page.execute(RemoveBindingParams::new(BINDING_NAME)),
        )
        .await
        .map_err(|_| watch_lost("runtime binding cleanup timed out"))
        .and_then(|result| result.map_err(|error| VoidCrawlError::PageError(error.to_string())))
        && first_error.is_none()
    {
        first_error = Some(error);
    }
    if disable_accessibility
        && let Err(error) = tokio_time::timeout(
            Duration::from_secs(1),
            page.execute(AccessibilityDisableParams::default()),
        )
        .await
        .map_err(|_| watch_lost("AX event cleanup timed out"))
        .and_then(|result| result.map_err(|error| VoidCrawlError::PageError(error.to_string())))
        && first_error.is_none()
    {
        first_error = Some(error);
    }
    first_error.map_or(Ok(()), Err)
}

const fn invalid_watch_input(reason: &'static str) -> VoidCrawlError {
    VoidCrawlError::InvalidInput {
        operation: "start_observation_watch",
        reason,
    }
}

fn watch_lost(reason: &str) -> VoidCrawlError {
    VoidCrawlError::PageError(format!("observation watch incomplete: {reason}"))
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn consumed_change_hints_have_no_lifetime_count_limit() {
        for _ in 0..17 {
            assert!(event_weight_fits(16, 16));
        }
        assert!(!event_weight_fits(15, 16));
    }

    #[test]
    fn completed_ignored_requests_release_their_bounded_slots() {
        let mut ids = HashSet::new();
        let mut retained_bytes = 0usize;
        for index in 0..129 {
            let id = format!("ignored-{index}");
            assert!(
                insert_bounded_id(&mut ids, &mut retained_bytes, &id, 0, 0, 16, 2_048,).is_ok()
            );
            assert!(remove_bounded_id(&mut ids, &mut retained_bytes, &id).is_ok());
        }
        assert!(ids.is_empty());
        assert_eq!(retained_bytes, 0);
    }

    #[test]
    fn concurrent_ignored_metadata_respects_current_capacity() {
        let mut ids = HashSet::new();
        let mut retained_bytes = 0usize;
        for index in 0..16 {
            let id = format!("queued-{index}");
            assert!(
                insert_bounded_id(&mut ids, &mut retained_bytes, &id, 0, 0, 16, 2_048,).is_ok()
            );
        }
        assert!(
            insert_bounded_id(&mut ids, &mut retained_bytes, "overflow", 0, 0, 16, 2_048,).is_err()
        );
        assert!(remove_bounded_id(&mut ids, &mut retained_bytes, "queued-0").is_ok());
        assert!(
            insert_bounded_id(
                &mut ids,
                &mut retained_bytes,
                "released-slot",
                0,
                0,
                16,
                2_048,
            )
            .is_ok()
        );
    }

    #[test]
    fn listener_queue_capacity_is_bounded_and_respects_small_watch_limits() {
        assert_eq!(provider_event_capacity(16), 16);
        assert_eq!(provider_event_capacity(4_096), MAX_PROVIDER_EVENT_CAPACITY);
    }

    #[test]
    fn request_wall_time_is_checked_and_reported_in_unix_microseconds() {
        assert_eq!(unix_micros_from_seconds(1.25).ok(), Some(1_250_000));
        assert_eq!(unix_micros_from_seconds(0.000_001).ok(), Some(1));
        assert!(unix_micros_from_seconds(0.0).is_err());
        assert!(unix_micros_from_seconds(0.000_000_1).is_err());
        assert!(unix_micros_from_seconds(-1.0).is_err());
        assert!(unix_micros_from_seconds(f64::NAN).is_err());
        assert!(unix_micros_from_seconds(f64::INFINITY).is_err());
        assert!(unix_micros_from_seconds(18_446_744_073_710.0).is_err());
    }
}
