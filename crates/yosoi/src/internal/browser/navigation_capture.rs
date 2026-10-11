//! Bounded main-document source and browser resource-graph capture.
//!
//! This is a concrete Chromium/CDP collector, not a provider abstraction or a
//! Yosoi artifact model. Raw URLs, headers, and source bytes are held in
//! non-serializable wrappers with redacted `Debug` implementations.

#[cfg(feature = "browser")]
use crate::internal::browser as void_crawl_core;

use std::{
    collections::HashMap,
    fmt,
    io::Read,
    mem,
    num::NonZeroUsize,
    result::Result as StdResult,
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};

use crate::internal::browser::vendor::chromiumoxide::{
    Page as CdpPage,
    cdp::browser_protocol::network::{
        EventLoadingFailed, EventLoadingFinished, EventRequestWillBeSent, EventResponseReceived,
        GetResponseBodyParams, RequestId, ResourceType, Response,
    },
    listeners::{EventDelivery, EventListenerConfig, EventOverflowPolicy, EventStream},
};
use crate::internal::types::{
    BrowserResourceId, BrowserResourceOutcome, ByteCount, ByteLimit, ByteLimitError,
};
use base64::engine::general_purpose::STANDARD as BASE64;
use futures::StreamExt;
use serde::Serialize;
use tokio::{
    sync::{mpsc, oneshot},
    task::JoinHandle,
    time,
};

use crate::internal::browser::{
    BrowserBudgetScope, BrowserByteDomain, BrowserByteReport, BrowserByteReportError,
    BrowserByteSpec, BrowserLimitScope, BrowserPayloadUnavailableReason, MeasuredCount,
    ResponseBodyState, Result, VoidCrawlError,
};

/// Hard bounds for one navigation capture.
#[derive(Debug, Clone, Copy)]
#[allow(
    clippy::struct_field_names,
    reason = "capture limits retain their explicit maximum field names"
)]
pub struct NavigationCaptureOptions {
    pub max_events: usize,
    pub max_resources: usize,
    pub max_source_bytes: usize,
    pub max_duration: Duration,
}

impl Default for NavigationCaptureOptions {
    fn default() -> Self {
        Self {
            max_events: 4_096,
            max_resources: 512,
            max_source_bytes: 8 * 1024 * 1024,
            max_duration: Duration::from_secs(30),
        }
    }
}

impl NavigationCaptureOptions {
    /// Construct options from typed byte limits while retaining the legacy
    /// usize fields.
    pub fn with_source_limit(mut self, limit: ByteLimit) -> Result<Self> {
        self.max_source_bytes = limit.as_usize().map_err(|_| VoidCrawlError::InvalidInput {
            operation: "navigation_capture",
            reason: "source-byte limit is too large",
        })?;
        Ok(self)
    }

    pub fn source_limit(&self) -> StdResult<ByteLimit, ByteLimitError> {
        ByteLimit::try_from(self.max_source_bytes)
    }

    pub(in crate::internal::browser) const fn validate(self) -> Result<Self> {
        if self.max_events == 0 || self.max_resources == 0 || self.max_source_bytes == 0 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "navigation_capture",
                reason: "event, resource, and source-byte limits must be positive",
            });
        }
        if self.max_duration.is_zero() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "navigation_capture",
                reason: "duration must be positive",
            });
        }
        Ok(self)
    }
}

/// A raw URL that is explicit to access and safe to format accidentally.
#[derive(Clone, PartialEq, Eq)]
pub struct ProtectedUrl(String);

impl ProtectedUrl {
    pub(in crate::internal::browser) const fn new(value: String) -> Self {
        Self(value)
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Debug for ProtectedUrl {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter.write_str("ProtectedUrl(<redacted>)")
    }
}

/// Raw HTTP headers protected from serialization and accidental debug output.
#[derive(Clone, PartialEq, Eq)]
pub struct ProtectedHeaders(Vec<(String, String)>);

impl ProtectedHeaders {
    pub fn as_slice(&self) -> &[(String, String)] {
        &self.0
    }
}

impl fmt::Debug for ProtectedHeaders {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProtectedHeaders")
            .field("count", &self.0.len())
            .finish_non_exhaustive()
    }
}

/// Capture-local frame identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ResourceFrameId(pub u64);

/// Capture-local loader identity.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Hash)]
pub struct ResourceLoaderId(pub u64);

/// One bounded resource-graph node.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct ResourceRecord {
    pub id: BrowserResourceId,
    pub redirect_from: Option<BrowserResourceId>,
    pub frame: Option<ResourceFrameId>,
    pub loader: Option<ResourceLoaderId>,
    pub url: ProtectedUrl,
    pub resource_type: String,
    pub status: Option<u16>,
    pub mime_type: Option<String>,
    pub headers: ProtectedHeaders,
    pub from_cache: bool,
    pub from_service_worker: bool,
    pub encoded_data_length: Option<u64>,
    pub outcome: BrowserResourceOutcome,
}

/// Explicit edge between two resource nodes in a redirect chain.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct RedirectHop {
    pub from: BrowserResourceId,
    pub to: BrowserResourceId,
    pub status: Option<u16>,
}

/// The semantic byte layer returned by Chromium's `Network.getResponseBody`.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum BrowserBodyLayer {
    /// Content codings have already been removed by Chromium. These are not
    /// transport-framed or content-coded wire bytes.
    DecodedRepresentation,
}

/// Why final main-document source bytes were unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum SourceBodyUnavailableReason {
    RequestFailed,
    CdpBodyUnavailable,
    InvalidBase64,
    CaptureEndedBeforeBody,
}

/// Final main-document response and independently retained source bytes.
#[derive(Clone, PartialEq, Eq)]
pub struct MainDocumentSource {
    pub resource_id: BrowserResourceId,
    pub url: ProtectedUrl,
    pub status: Option<u16>,
    pub headers: ProtectedHeaders,
    pub mime_type: Option<String>,
    pub from_cache: bool,
    pub from_service_worker: bool,
    pub body_layer: Option<BrowserBodyLayer>,
    pub body_state: ResponseBodyState,
    pub body_unavailable: Option<SourceBodyUnavailableReason>,
    pub retained_bytes: usize,
    pub complete_bytes: Option<usize>,
    /// Capture-local offset when the source outcome became owned.
    pub captured_at_micros: u64,
    body: Arc<[u8]>,
    max_source_bytes: usize,
}

impl MainDocumentSource {
    pub fn body(&self) -> &[u8] {
        &self.body
    }

    pub fn source_limit(&self) -> StdResult<ByteLimit, ByteLimitError> {
        ByteLimit::try_from(self.max_source_bytes)
    }

    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        let spec = self.max_source_spec()?;
        match self.body_state {
            ResponseBodyState::Unavailable => match self.body_unavailable {
                Some(SourceBodyUnavailableReason::RequestFailed) => BrowserByteReport::failed(
                    BrowserByteDomain::CdpDecodedBody,
                    Some(spec),
                    void_crawl_core::BrowserPayloadFailureReason::ProviderRejected,
                ),
                Some(SourceBodyUnavailableReason::InvalidBase64) => BrowserByteReport::failed(
                    BrowserByteDomain::CdpDecodedBody,
                    Some(spec),
                    void_crawl_core::BrowserPayloadFailureReason::InvalidEncoding,
                ),
                Some(
                    SourceBodyUnavailableReason::CdpBodyUnavailable
                    | SourceBodyUnavailableReason::CaptureEndedBeforeBody,
                )
                | None => BrowserByteReport::unavailable_with_spec(
                    BrowserByteDomain::CdpDecodedBody,
                    Some(spec),
                    BrowserPayloadUnavailableReason::ProviderDidNotReport,
                ),
            },
            ResponseBodyState::Available | ResponseBodyState::Truncated => {
                Ok(BrowserByteReport::from_known_extent(
                    BrowserByteDomain::CdpDecodedBody,
                    Some(spec),
                    ByteCount::try_from_usize(self.complete_bytes.unwrap_or(self.retained_bytes))?,
                    ByteCount::try_from_usize(self.retained_bytes)?,
                )?)
            }
        }
    }

    fn max_source_spec(&self) -> StdResult<BrowserByteSpec, BrowserByteReportError> {
        Ok(BrowserByteSpec::new(
            BrowserByteDomain::CdpDecodedBody,
            ByteLimit::try_from(self.max_source_bytes)?,
            BrowserLimitScope::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ))
    }
}

impl fmt::Debug for MainDocumentSource {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("MainDocumentSource")
            .field("resource_id", &self.resource_id)
            .field("url", &self.url)
            .field("status", &self.status)
            .field("headers", &self.headers)
            .field("mime_type", &self.mime_type)
            .field("from_cache", &self.from_cache)
            .field("from_service_worker", &self.from_service_worker)
            .field("body_layer", &self.body_layer)
            .field("body_state", &self.body_state)
            .field("body_unavailable", &self.body_unavailable)
            .field("retained_bytes", &self.retained_bytes)
            .field("complete_bytes", &self.complete_bytes)
            .field("captured_at_micros", &self.captured_at_micros)
            .finish_non_exhaustive()
    }
}

/// Kind of browser network event received by the capture coordinator.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum NavigationEventKind {
    Request,
    Response,
    Finished,
    Failed,
}

/// One retained browser network event in coordinator receipt order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct NavigationEvent {
    pub sequence: u64,
    pub offset_micros: u64,
    pub kind: NavigationEventKind,
    pub resource_id: Option<BrowserResourceId>,
}

/// Why a bounded navigation capture stopped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NavigationCaptureTermination {
    Finished,
    Cancelled,
    DeadlineReached,
    EventLimitReached,
    ProviderDisconnected,
}

/// Availability of credential-bearing `Network.*ExtraInfo` events.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum NetworkExtraInfoState {
    /// The vendored chromiumoxide 0.9.1 path has been measured delivering no
    /// request/response ExtraInfo events. Cookie and raw `Set-Cookie` values
    /// must be obtained through separately scoped browser-state APIs.
    UnavailableInCurrentClient,
}

/// Owned terminal result of one navigation capture.
#[derive(Debug, Clone, PartialEq, Eq)]
pub struct NavigationCaptureReport {
    pub started_at_unix_ms: Option<u64>,
    pub elapsed_micros: u64,
    pub termination: NavigationCaptureTermination,
    pub requested_url: Option<ProtectedUrl>,
    pub final_url: Option<ProtectedUrl>,
    pub redirects: Vec<RedirectHop>,
    pub main_document: Option<MainDocumentSource>,
    pub resources: Vec<ResourceRecord>,
    pub events: Vec<NavigationEvent>,
    pub events_admitted: u64,
    pub events_retained: u64,
    pub events_dropped: MeasuredCount,
    pub resources_dropped: u64,
    pub additional_loss_unknown: bool,
    pub network_extra_info: NetworkExtraInfoState,
    pub cleanup_complete: bool,
}

/// Armed browser navigation capture.
pub struct NavigationCapture {
    stop: Option<oneshot::Sender<NavigationStop>>,
    worker: Option<JoinHandle<NavigationCaptureReport>>,
}

impl fmt::Debug for NavigationCapture {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("NavigationCapture")
            .finish_non_exhaustive()
    }
}

impl NavigationCapture {
    pub(in crate::internal::browser) async fn arm(
        page: CdpPage,
        options: NavigationCaptureOptions,
    ) -> Result<Self> {
        let options = options.validate()?;
        let streams = RegisteredStreams::register(&page, options.max_events).await?;
        let started = Instant::now();
        let started_at_unix_ms = unix_millis(SystemTime::now());
        let capacity = options.max_events.clamp(1, 2_048);
        let (events_tx, events_rx) = mpsc::channel(capacity);
        let collectors = streams.spawn(events_tx);
        let (stop, stop_rx) = oneshot::channel();
        let worker = tokio::spawn(run_capture(
            page,
            events_rx,
            stop_rx,
            collectors,
            options,
            started,
            started_at_unix_ms,
        ));
        Ok(Self {
            stop: Some(stop),
            worker: Some(worker),
        })
    }

    pub async fn finish(self) -> Result<NavigationCaptureReport> {
        self.stop_with(NavigationStop::Finished).await
    }

    pub async fn cancel(self) -> Result<NavigationCaptureReport> {
        self.stop_with(NavigationStop::Cancelled).await
    }

    pub async fn wait(mut self) -> Result<NavigationCaptureReport> {
        self.join_worker().await
    }

    async fn stop_with(mut self, stop: NavigationStop) -> Result<NavigationCaptureReport> {
        if let Some(sender) = self.stop.take() {
            let _ = sender.send(stop);
        }
        self.join_worker().await
    }

    async fn join_worker(&mut self) -> Result<NavigationCaptureReport> {
        // Keep the handle in `self` across the await: if this outer future is
        // cancelled, `Drop` still owns and aborts the coordinator, including
        // an in-progress response-body retrieval.
        self.worker
            .as_mut()
            .ok_or_else(|| VoidCrawlError::Other("navigation capture already consumed".into()))?
            .await
            .map_err(|error| {
                VoidCrawlError::Other(format!("navigation capture worker failed: {error}"))
            })
    }
}

impl Drop for NavigationCapture {
    fn drop(&mut self) {
        if let Some(worker) = self.worker.take() {
            worker.abort();
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum NavigationStop {
    Finished,
    Cancelled,
}

struct RegisteredStreams {
    requests: EventStream<EventRequestWillBeSent>,
    responses: EventStream<EventResponseReceived>,
    finished: EventStream<EventLoadingFinished>,
    failed: EventStream<EventLoadingFailed>,
}

impl RegisteredStreams {
    async fn register(page: &CdpPage, max_events: usize) -> Result<Self> {
        let listener_capacity =
            NonZeroUsize::new(max_events.clamp(1, 2_048)).ok_or(VoidCrawlError::InvalidInput {
                operation: "navigation_capture",
                reason: "event listener capacity must be positive",
            })?;
        // Resource-graph correctness depends on receiving each lifecycle
        // transition. A bounded listener therefore closes on overflow; the
        // coordinator reports the resulting capture as incomplete.
        let listener_config =
            EventListenerConfig::new(listener_capacity, EventOverflowPolicy::Close);
        Ok(Self {
            requests: page
                .event_listener::<EventRequestWillBeSent>(listener_config)
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            responses: page
                .event_listener::<EventResponseReceived>(listener_config)
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            finished: page
                .event_listener::<EventLoadingFinished>(listener_config)
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            failed: page
                .event_listener::<EventLoadingFailed>(listener_config)
                .await
                .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
        })
    }

    fn spawn(self, sender: mpsc::Sender<RawNetworkEvent>) -> CollectorTasks {
        CollectorTasks(vec![forward_network(self, sender)])
    }
}

struct CollectorTasks(Vec<JoinHandle<()>>);

impl CollectorTasks {
    async fn shutdown(&mut self) {
        for task in &self.0 {
            task.abort();
        }
        for task in mem::take(&mut self.0) {
            let _ = task.await;
        }
    }
}

impl Drop for CollectorTasks {
    fn drop(&mut self) {
        for task in &self.0 {
            task.abort();
        }
    }
}

enum RawNetworkEvent {
    Request(Arc<EventRequestWillBeSent>),
    Response(Arc<EventResponseReceived>),
    Finished(Arc<EventLoadingFinished>),
    Failed(Arc<EventLoadingFailed>),
    StreamLagged,
    StreamClosed,
}

struct BodyCaptureRequest {
    resource: ResourceRecord,
    request_id: RequestId,
}

enum EventResult {
    Continue,
    CaptureBody(BodyCaptureRequest),
    StreamClosed,
}

struct CaptureState {
    resources: Vec<ResourceRecord>,
    by_request: HashMap<String, usize>,
    frame_ids: HashMap<String, ResourceFrameId>,
    loader_ids: HashMap<String, ResourceLoaderId>,
    redirects: Vec<RedirectHop>,
    requested_url: Option<ProtectedUrl>,
    main_frame: Option<ResourceFrameId>,
    main_index: Option<usize>,
    main_document: Option<MainDocumentSource>,
    events: Vec<NavigationEvent>,
    events_admitted: u64,
    resources_dropped: u64,
}

impl CaptureState {
    fn new() -> Self {
        Self {
            resources: Vec::new(),
            by_request: HashMap::new(),
            frame_ids: HashMap::new(),
            loader_ids: HashMap::new(),
            redirects: Vec::new(),
            requested_url: None,
            main_frame: None,
            main_index: None,
            main_document: None,
            events: Vec::new(),
            events_admitted: 0,
            resources_dropped: 0,
        }
    }

    fn on_event(
        &mut self,
        event: RawNetworkEvent,
        options: NavigationCaptureOptions,
        offset_micros: u64,
    ) -> EventResult {
        if matches!(
            event,
            RawNetworkEvent::StreamLagged | RawNetworkEvent::StreamClosed
        ) {
            return EventResult::StreamClosed;
        }
        let (kind, request_id) = match &event {
            RawNetworkEvent::Request(event) => (
                NavigationEventKind::Request,
                event.request_id.inner().clone(),
            ),
            RawNetworkEvent::Response(event) => (
                NavigationEventKind::Response,
                event.request_id.inner().clone(),
            ),
            RawNetworkEvent::Finished(event) => (
                NavigationEventKind::Finished,
                event.request_id.inner().clone(),
            ),
            RawNetworkEvent::Failed(event) => (
                NavigationEventKind::Failed,
                event.request_id.inner().clone(),
            ),
            RawNetworkEvent::StreamLagged | RawNetworkEvent::StreamClosed => {
                return EventResult::StreamClosed;
            }
        };
        let result = match event {
            RawNetworkEvent::Request(event) => {
                self.on_request(&event, options);
                EventResult::Continue
            }
            RawNetworkEvent::Response(event) => {
                self.on_response(&event);
                EventResult::Continue
            }
            RawNetworkEvent::Finished(event) => self
                .on_finished(&event)
                .map_or(EventResult::Continue, EventResult::CaptureBody),
            RawNetworkEvent::Failed(event) => {
                self.on_failed(&event, options.max_source_bytes, offset_micros);
                EventResult::Continue
            }
            RawNetworkEvent::StreamLagged | RawNetworkEvent::StreamClosed => {
                return EventResult::StreamClosed;
            }
        };
        let resource_id = self
            .by_request
            .get(&request_id)
            .and_then(|index| self.resources.get(*index))
            .map(|resource| resource.id);
        let sequence = self.events_admitted;
        self.events.push(NavigationEvent {
            sequence,
            offset_micros,
            kind,
            resource_id,
        });
        self.events_admitted = self.events_admitted.saturating_add(1);
        result
    }

    fn on_request(&mut self, event: &EventRequestWillBeSent, options: NavigationCaptureOptions) {
        let request_id = event.request_id.inner().clone();
        let redirect_from = self.by_request.get(&request_id).copied();
        if let (Some(index), Some(response)) = (redirect_from, event.redirect_response.as_ref())
            && let Some(resource) = self.resources.get_mut(index)
        {
            Self::apply_response(resource, response);
            resource.outcome = BrowserResourceOutcome::Redirected;
        }

        if self.resources.len() >= options.max_resources {
            self.resources_dropped = self.resources_dropped.saturating_add(1);
            self.by_request.remove(&request_id);
            // A retained redirect response is not the final document. If its
            // successor cannot be retained, do not expose stale final URL or
            // main-document identity from the redirecting node.
            if redirect_from == self.main_index
                && event.redirect_response.is_some()
                && matches!(event.r#type, Some(ResourceType::Document))
            {
                self.main_index = None;
                self.main_document = None;
            }
            return;
        }

        let id = BrowserResourceId(u64::try_from(self.resources.len()).unwrap_or(u64::MAX));
        let previous_id = redirect_from
            .and_then(|index| self.resources.get(index))
            .map(|resource| resource.id);
        let frame = event.frame_id.as_ref().map(|id| self.frame_id(id.inner()));
        let loader = Some(self.loader_id(event.loader_id.inner()));
        let resource_type = event.r#type.as_ref().map_or_else(
            || "other".to_string(),
            |kind| format!("{kind:?}").to_ascii_lowercase(),
        );
        let is_document = matches!(event.r#type, Some(ResourceType::Document));
        let index = self.resources.len();
        self.resources.push(ResourceRecord {
            id,
            redirect_from: previous_id,
            frame,
            loader,
            url: ProtectedUrl(event.request.url.clone()),
            resource_type,
            status: None,
            mime_type: None,
            headers: ProtectedHeaders(Vec::new()),
            from_cache: false,
            from_service_worker: false,
            encoded_data_length: None,
            outcome: BrowserResourceOutcome::Pending,
        });
        self.by_request.insert(request_id, index);

        if let Some(previous) = previous_id {
            let status = redirect_from
                .and_then(|old| self.resources.get(old))
                .and_then(|resource| resource.status);
            self.redirects.push(RedirectHop {
                from: previous,
                to: id,
                status,
            });
        }
        if is_document && self.main_frame.is_none() {
            self.requested_url = Some(ProtectedUrl(event.request.url.clone()));
            self.main_frame = frame;
            self.main_index = Some(index);
        } else if is_document && frame == self.main_frame && previous_id.is_some() {
            self.main_index = Some(index);
        }
    }

    fn on_response(&mut self, event: &EventResponseReceived) {
        let Some(resource) = self
            .by_request
            .get(event.request_id.inner())
            .and_then(|index| self.resources.get_mut(*index))
        else {
            return;
        };
        Self::apply_response(resource, &event.response);
        if !matches!(resource.outcome, BrowserResourceOutcome::Failed { .. }) {
            resource.outcome = BrowserResourceOutcome::ResponseReceived;
        }
    }

    fn on_finished(&mut self, event: &EventLoadingFinished) -> Option<BodyCaptureRequest> {
        let index = self.by_request.get(event.request_id.inner()).copied()?;
        let resource = self.resources.get_mut(index)?;
        if matches!(resource.outcome, BrowserResourceOutcome::Failed { .. }) {
            return None;
        }
        resource.encoded_data_length = whole_nonnegative(event.encoded_data_length);
        resource.outcome = BrowserResourceOutcome::Complete;
        (self.main_index == Some(index)).then(|| BodyCaptureRequest {
            resource: resource.clone(),
            request_id: event.request_id.clone(),
        })
    }

    fn on_failed(
        &mut self,
        event: &EventLoadingFailed,
        max_source_bytes: usize,
        captured_at_micros: u64,
    ) {
        let Some(index) = self.by_request.get(event.request_id.inner()).copied() else {
            return;
        };
        let Some(resource) = self.resources.get_mut(index) else {
            return;
        };
        resource.outcome = BrowserResourceOutcome::Failed {
            cancelled: event.canceled.unwrap_or(false),
            blocked: event.blocked_reason.is_some(),
        };
        if self.main_index == Some(index) {
            self.main_document = Some(unavailable_main_document(
                resource,
                SourceBodyUnavailableReason::RequestFailed,
                max_source_bytes,
                captured_at_micros,
            ));
        }
    }

    fn apply_response(resource: &mut ResourceRecord, response: &Response) {
        resource.url = ProtectedUrl(response.url.clone());
        resource.status = http_status(response.status);
        resource.mime_type = nonempty(response.mime_type.clone());
        resource.headers = ProtectedHeaders(flatten_headers(response.headers.inner()));
        resource.from_cache = response.from_disk_cache.unwrap_or(false)
            || response.from_prefetch_cache.unwrap_or(false);
        resource.from_service_worker = response.from_service_worker.unwrap_or(false);
    }

    fn frame_id(&mut self, raw: &str) -> ResourceFrameId {
        let next = ResourceFrameId(u64::try_from(self.frame_ids.len()).unwrap_or(u64::MAX));
        *self.frame_ids.entry(raw.to_string()).or_insert(next)
    }

    fn loader_id(&mut self, raw: &str) -> ResourceLoaderId {
        let next = ResourceLoaderId(u64::try_from(self.loader_ids.len()).unwrap_or(u64::MAX));
        *self.loader_ids.entry(raw.to_string()).or_insert(next)
    }
}

#[allow(
    clippy::cognitive_complexity,
    reason = "the nested select keeps stop/deadline cancellation active during CDP body retrieval"
)]
async fn run_capture(
    page: CdpPage,
    mut events_rx: mpsc::Receiver<RawNetworkEvent>,
    mut stop_rx: oneshot::Receiver<NavigationStop>,
    mut collectors: CollectorTasks,
    options: NavigationCaptureOptions,
    started: Instant,
    started_at_unix_ms: Option<u64>,
) -> NavigationCaptureReport {
    let deadline_at = time::Instant::now()
        .checked_add(options.max_duration)
        .unwrap_or_else(time::Instant::now);
    let deadline = time::sleep_until(deadline_at);
    tokio::pin!(deadline);
    let mut state = CaptureState::new();

    let mut termination = 'capture: loop {
        tokio::select! {
            biased;
            stop = &mut stop_rx => {
                break match stop {
                    Ok(NavigationStop::Finished) => NavigationCaptureTermination::Finished,
                    Ok(NavigationStop::Cancelled) | Err(_) => NavigationCaptureTermination::Cancelled,
                };
            }
            () = &mut deadline => break NavigationCaptureTermination::DeadlineReached,
            event = events_rx.recv() => {
                let Some(event) = event else {
                    break NavigationCaptureTermination::ProviderDisconnected;
                };
                match state.on_event(event, options, duration_micros(started.elapsed())) {
                    EventResult::Continue => {}
                    EventResult::StreamClosed => {
                        break NavigationCaptureTermination::ProviderDisconnected;
                    }
                    EventResult::CaptureBody(request) => {
                        tokio::select! {
                            biased;
                            stop = &mut stop_rx => {
                                break 'capture match stop {
                                    Ok(NavigationStop::Finished) => NavigationCaptureTermination::Finished,
                                    Ok(NavigationStop::Cancelled) | Err(_) => NavigationCaptureTermination::Cancelled,
                                };
                            }
                            () = &mut deadline => {
                                break 'capture NavigationCaptureTermination::DeadlineReached;
                            }
                            source = capture_main_document(
                                &page,
                                &request.resource,
                                request.request_id,
                                options.max_source_bytes,
                                started,
                            ) => state.main_document = Some(source),
                        }
                    }
                }
                if usize::try_from(state.events_admitted).unwrap_or(usize::MAX) >= options.max_events {
                    break NavigationCaptureTermination::EventLimitReached;
                }
            }
        }
    };

    collectors.shutdown().await;
    while usize::try_from(state.events_admitted).unwrap_or(usize::MAX) < options.max_events {
        let Ok(event) = events_rx.try_recv() else {
            break;
        };
        match state.on_event(event, options, duration_micros(started.elapsed())) {
            EventResult::Continue => {}
            EventResult::StreamClosed => break,
            EventResult::CaptureBody(request) => {
                state.main_document = Some(unavailable_main_document(
                    &request.resource,
                    SourceBodyUnavailableReason::CaptureEndedBeforeBody,
                    options.max_source_bytes,
                    duration_micros(started.elapsed()),
                ));
            }
        }
    }
    if termination == NavigationCaptureTermination::Finished
        && usize::try_from(state.events_admitted).unwrap_or(usize::MAX) >= options.max_events
    {
        termination = NavigationCaptureTermination::EventLimitReached;
    }
    let final_url = state
        .main_index
        .and_then(|index| state.resources.get(index))
        .map(|resource| resource.url.clone());
    if state.main_document.is_none()
        && let Some(index) = state.main_index
        && let Some(resource) = state.resources.get(index)
    {
        state.main_document = Some(unavailable_main_document(
            resource,
            SourceBodyUnavailableReason::CaptureEndedBeforeBody,
            options.max_source_bytes,
            duration_micros(started.elapsed()),
        ));
    }
    let additional_loss_unknown = matches!(
        termination,
        NavigationCaptureTermination::DeadlineReached
            | NavigationCaptureTermination::EventLimitReached
            | NavigationCaptureTermination::ProviderDisconnected
    );
    NavigationCaptureReport {
        started_at_unix_ms,
        elapsed_micros: duration_micros(started.elapsed()),
        termination,
        requested_url: state.requested_url,
        final_url,
        redirects: state.redirects,
        main_document: state.main_document,
        resources: state.resources,
        events: state.events,
        events_admitted: state.events_admitted,
        events_retained: state.events_admitted,
        events_dropped: MeasuredCount::Known { value: 0 },
        resources_dropped: state.resources_dropped,
        additional_loss_unknown,
        network_extra_info: NetworkExtraInfoState::UnavailableInCurrentClient,
        cleanup_complete: true,
    }
}

async fn capture_main_document(
    page: &CdpPage,
    resource: &ResourceRecord,
    request_id: RequestId,
    max_source_bytes: usize,
    started: Instant,
) -> MainDocumentSource {
    match page.execute(GetResponseBodyParams::new(request_id)).await {
        Ok(response) => {
            let (mut decoded, complete_bytes) = match decode_cdp_body(
                response.result.body,
                response.result.base64_encoded,
                max_source_bytes,
            ) {
                Ok(body) => body,
                Err(reason) => {
                    return unavailable_main_document(
                        resource,
                        reason,
                        max_source_bytes,
                        duration_micros(started.elapsed()),
                    );
                }
            };
            let retained_bytes = decoded.len();
            let body_state = if retained_bytes == complete_bytes {
                ResponseBodyState::Available
            } else {
                ResponseBodyState::Truncated
            };
            MainDocumentSource {
                resource_id: resource.id,
                url: resource.url.clone(),
                status: resource.status,
                headers: resource.headers.clone(),
                mime_type: resource.mime_type.clone(),
                from_cache: resource.from_cache,
                from_service_worker: resource.from_service_worker,
                body_layer: Some(BrowserBodyLayer::DecodedRepresentation),
                body_state,
                body_unavailable: None,
                retained_bytes,
                complete_bytes: Some(complete_bytes),
                captured_at_micros: duration_micros(started.elapsed()),
                body: Arc::from(mem::take(&mut decoded)),
                max_source_bytes,
            }
        }
        Err(_) => unavailable_main_document(
            resource,
            SourceBodyUnavailableReason::CdpBodyUnavailable,
            max_source_bytes,
            duration_micros(started.elapsed()),
        ),
    }
}

fn decode_cdp_body(
    body: String,
    base64_encoded: bool,
    max_source_bytes: usize,
) -> StdResult<(Vec<u8>, usize), SourceBodyUnavailableReason> {
    if !base64_encoded {
        let complete_bytes = body.len();
        let mut retained = body.into_bytes();
        retained.truncate(max_source_bytes);
        return Ok((retained, complete_bytes));
    }

    let mut decoder = base64::read::DecoderReader::new(body.as_bytes(), &BASE64);
    let mut retained = Vec::with_capacity(max_source_bytes.min(8 * 1024));
    let mut complete_bytes = 0usize;
    let mut chunk = [0_u8; 8 * 1024];
    loop {
        let read = decoder
            .read(&mut chunk)
            .map_err(|_| SourceBodyUnavailableReason::InvalidBase64)?;
        if read == 0 {
            break;
        }
        complete_bytes = complete_bytes
            .checked_add(read)
            .ok_or(SourceBodyUnavailableReason::InvalidBase64)?;
        let available = max_source_bytes.saturating_sub(retained.len());
        let retained_len = read.min(available);
        retained.extend_from_slice(chunk.get(..retained_len).unwrap_or(&[]));
    }
    Ok((retained, complete_bytes))
}

fn unavailable_main_document(
    resource: &ResourceRecord,
    reason: SourceBodyUnavailableReason,
    max_source_bytes: usize,
    captured_at_micros: u64,
) -> MainDocumentSource {
    MainDocumentSource {
        resource_id: resource.id,
        url: resource.url.clone(),
        status: resource.status,
        headers: resource.headers.clone(),
        mime_type: resource.mime_type.clone(),
        from_cache: resource.from_cache,
        from_service_worker: resource.from_service_worker,
        body_layer: None,
        body_state: ResponseBodyState::Unavailable,
        body_unavailable: Some(reason),
        retained_bytes: 0,
        complete_bytes: None,
        captured_at_micros,
        body: Arc::from([]),
        max_source_bytes,
    }
}

fn forward_network(
    mut streams: RegisteredStreams,
    sender: mpsc::Sender<RawNetworkEvent>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        loop {
            let event = tokio::select! {
                biased;
                event = streams.requests.next() => event.map(|delivery| match delivery {
                    EventDelivery::Event(event) => RawNetworkEvent::Request(event),
                    EventDelivery::Lagged { .. } => RawNetworkEvent::StreamLagged,
                }),
                event = streams.responses.next() => event.map(|delivery| match delivery {
                    EventDelivery::Event(event) => RawNetworkEvent::Response(event),
                    EventDelivery::Lagged { .. } => RawNetworkEvent::StreamLagged,
                }),
                event = streams.finished.next() => event.map(|delivery| match delivery {
                    EventDelivery::Event(event) => RawNetworkEvent::Finished(event),
                    EventDelivery::Lagged { .. } => RawNetworkEvent::StreamLagged,
                }),
                event = streams.failed.next() => event.map(|delivery| match delivery {
                    EventDelivery::Event(event) => RawNetworkEvent::Failed(event),
                    EventDelivery::Lagged { .. } => RawNetworkEvent::StreamLagged,
                }),
            };
            let Some(event) = event else {
                let _ = sender.send(RawNetworkEvent::StreamClosed).await;
                return;
            };
            if sender.send(event).await.is_err() {
                return;
            }
        }
    })
}

fn flatten_headers(value: &serde_json::Value) -> Vec<(String, String)> {
    value
        .as_object()
        .map(|headers| {
            headers
                .iter()
                .filter_map(|(name, value)| {
                    value
                        .as_str()
                        .map(|value| (name.to_ascii_lowercase(), value.to_string()))
                })
                .collect()
        })
        .unwrap_or_default()
}

fn http_status(value: i64) -> Option<u16> {
    u16::try_from(value).ok()
}

fn whole_nonnegative(value: f64) -> Option<u64> {
    if !value.is_finite() || value < 0.0 || value.fract() != 0.0 {
        return None;
    }
    format!("{value:.0}").parse().ok()
}

fn nonempty(value: String) -> Option<String> {
    (!value.is_empty()).then_some(value)
}

mod timing;
use timing::{duration_micros, unix_millis};

#[cfg(test)]
#[path = "navigation_capture_options_tests.rs"]
mod options_tests;

#[cfg(test)]
#[allow(clippy::expect_used)]
mod tests {
    use std::future;

    use base64::Engine as _;

    use super::*;

    struct AbortSignal(Option<oneshot::Sender<()>>);

    impl Drop for AbortSignal {
        fn drop(&mut self) {
            if let Some(sender) = self.0.take() {
                let _ = sender.send(());
            }
        }
    }

    fn pending_capture() -> (
        NavigationCapture,
        oneshot::Receiver<()>,
        oneshot::Receiver<()>,
    ) {
        let (stop, _) = oneshot::channel();
        let (started_tx, started_rx) = oneshot::channel();
        let (aborted_tx, aborted_rx) = oneshot::channel();
        let worker = tokio::spawn(async move {
            let _signal = AbortSignal(Some(aborted_tx));
            let _ = started_tx.send(());
            future::pending::<NavigationCaptureReport>().await
        });
        (
            NavigationCapture {
                stop: Some(stop),
                worker: Some(worker),
            },
            started_rx,
            aborted_rx,
        )
    }

    #[tokio::test]
    async fn cancelling_terminal_joins_aborts_the_owned_body_capture_worker() {
        macro_rules! assert_terminal_join_aborts_worker {
            ($method:ident) => {{
                let (capture, started, aborted) = pending_capture();
                started.await.expect("worker started");
                let terminal = tokio::spawn(async move { capture.$method().await });
                tokio::task::yield_now().await;
                terminal.abort();
                let _ = terminal.await;
                tokio::time::timeout(Duration::from_secs(1), aborted)
                    .await
                    .expect("capture drop did not abort worker")
                    .expect("worker abort signal dropped");
            }};
        }

        assert_terminal_join_aborts_worker!(wait);
        assert_terminal_join_aborts_worker!(finish);
        assert_terminal_join_aborts_worker!(cancel);
    }

    #[test]
    fn protected_values_do_not_debug_raw_content() {
        let url = ProtectedUrl("https://user:secret@example.test/path?token=secret".into());
        let headers = ProtectedHeaders(vec![
            ("authorization".into(), "Bearer secret".into()),
            ("set-cookie".into(), "session=secret".into()),
        ]);
        let debug = format!("{url:?} {headers:?}");
        assert!(!debug.contains("example.test"));
        assert!(!debug.contains("Bearer"));
        assert!(!debug.contains("session="));
        assert!(!debug.contains("secret"));
    }

    #[test]
    fn bounded_base64_decode_counts_full_output_without_retaining_it_all() {
        let encoded = BASE64.encode(b"abcdefgh");
        let (retained, complete) = decode_cdp_body(encoded, true, 3).expect("valid base64");
        assert_eq!(retained, b"abc");
        assert_eq!(complete, 8);
        assert_eq!(
            decode_cdp_body("YWJj!!!!".into(), true, 2),
            Err(SourceBodyUnavailableReason::InvalidBase64),
        );
    }

    #[test]
    fn numeric_cdp_values_are_accepted_only_when_exact_nonnegative_integers() {
        assert_eq!(whole_nonnegative(200.0), Some(200));
        assert_eq!(whole_nonnegative(-1.0), None);
        assert_eq!(whole_nonnegative(1.5), None);
        assert_eq!(whole_nonnegative(f64::NAN), None);
    }
}
