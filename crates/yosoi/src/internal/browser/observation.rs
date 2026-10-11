//! Pre-navigation, bounded browser observation scope.
//!
//! The scope records only secret-safe lifecycle markers. Artifact payloads
//! such as response bodies, console text, and exception details belong to
//! focused collectors layered on this lifecycle in later work.

#[cfg(feature = "browser")]
use crate::internal::browser as void_crawl_core;
use crate::internal::types as yosoi_types;

use std::{
    collections::HashSet,
    fmt, mem,
    num::NonZeroUsize,
    result::Result as StdResult,
    str,
    sync::Arc,
    time::{Duration, SystemTime, UNIX_EPOCH},
};

use crate::internal::browser::vendor::chromiumoxide::{
    Page as CdpPage,
    cdp::{
        IntoEventKind,
        browser_protocol::network::{
            EventLoadingFailed, EventLoadingFinished, EventRequestWillBeSent,
            EventResponseReceived, ResourceType,
        },
        js_protocol::runtime::{EventConsoleApiCalled, EventExceptionThrown},
    },
    listeners::{EventDelivery, EventListenerConfig, EventOverflowPolicy, EventStream},
};
use crate::internal::types::{ByteCount, ByteLimit, ByteLimitError};
use futures::StreamExt;
use serde::Serialize;
use tokio::{
    sync::{broadcast, mpsc, oneshot},
    task::JoinHandle,
    time::{self, Instant},
};

use crate::internal::browser::{
    BrowserBudgetScope, BrowserByteAccounting, BrowserByteBudget, BrowserByteDomain,
    BrowserByteMeasurementUnavailableReason, BrowserByteReport, BrowserByteReportError,
    BrowserByteSpec, BrowserLimitScope, MeasuredBrowserBytes, Result, VoidCrawlError,
};

/// Collectors and hard bounds for one observation scope.
///
/// A scope watches its owned page for a renderer crash when the controller is
/// in normal CDP mode, where target discovery is active. Minimal mode does not
/// receive stable target crash events; there, deadline and disconnect remain
/// the available terminal signals. Setting every collector flag to `false`
/// creates a crash-only scope without enabling CDP event domains in normal
/// mode.
#[derive(Debug, Clone, Copy)]
#[allow(
    clippy::struct_excessive_bools,
    reason = "each flag selects an independent concrete CDP collector"
)]
pub struct ObservationOptions {
    pub collect_network: bool,
    pub collect_console: bool,
    pub collect_exceptions: bool,
    pub max_events: usize,
    pub max_diagnostic_bytes: usize,
    pub max_duration: Duration,
}

impl Default for ObservationOptions {
    fn default() -> Self {
        Self {
            collect_network: true,
            collect_console: true,
            collect_exceptions: true,
            max_events: 2_048,
            max_diagnostic_bytes: 64 * 1024,
            max_duration: Duration::from_secs(30),
        }
    }
}

impl ObservationOptions {
    /// Set the diagnostic retention limit using the typed browser-byte API.
    pub fn with_diagnostic_limit(mut self, limit: ByteLimit) -> StdResult<Self, ByteLimitError> {
        self.max_diagnostic_bytes = limit.as_usize()?;
        Ok(self)
    }

    /// Return the configured diagnostic retention limit in typed form.
    pub fn diagnostic_limit(&self) -> StdResult<ByteLimit, ByteLimitError> {
        ByteLimit::try_from(self.max_diagnostic_bytes)
    }

    pub(in crate::internal::browser) const fn validate(self) -> Result<Self> {
        if self.max_events == 0 || self.max_diagnostic_bytes == 0 {
            return Err(VoidCrawlError::InvalidInput {
                operation: "observation_scope",
                reason: "event and diagnostic-byte limits must be positive",
            });
        }
        if self.max_duration.is_zero() {
            return Err(VoidCrawlError::InvalidInput {
                operation: "observation_scope",
                reason: "duration must be positive",
            });
        }
        Ok(self)
    }
}

/// Secret-safe marker for one observed CDP lifecycle event.
///
/// This provider receipt vocabulary intentionally remains distinct from Web
/// Capture's durable browser observation kind: its snake-case wire form and
/// event authority are part of the VoidCrawl report contract.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationEventKind {
    DocumentRequestStarted,
    ResourceRequestStarted,
    ResponseReceived,
    RequestFinished,
    RequestFailed,
    ConsoleApiCalled,
    RuntimeExceptionThrown,
}

/// Protected runtime text omitted from serialization and default formatting.
#[derive(Clone, PartialEq, Eq)]
pub struct ProtectedDiagnosticText(Arc<[u8]>);

impl ProtectedDiagnosticText {
    pub fn bytes(&self) -> &[u8] {
        &self.0
    }

    pub fn text(&self) -> Option<&str> {
        str::from_utf8(&self.0).ok()
    }
}

impl fmt::Debug for ProtectedDiagnosticText {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ProtectedDiagnosticText")
            .field("retained_bytes", &self.0.len())
            .finish_non_exhaustive()
    }
}

/// Kind of bounded runtime diagnostic payload.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
#[serde(tag = "kind", rename_all = "snake_case")]
pub enum RuntimeDiagnosticKind {
    Console { level: String },
    Exception,
}

/// One protected console or exception payload associated with an event.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct RuntimeDiagnostic {
    pub event_sequence: u64,
    pub kind: RuntimeDiagnosticKind,
    pub retained_bytes: usize,
    pub complete_bytes: usize,
    pub truncated: bool,
    #[serde(skip)]
    text: ProtectedDiagnosticText,
}

impl RuntimeDiagnostic {
    pub const fn text(&self) -> &ProtectedDiagnosticText {
        &self.text
    }

    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::RuntimeDiagnosticUtf8,
            None,
            ByteCount::try_from_usize(self.complete_bytes)?,
            ByteCount::try_from_usize(self.retained_bytes)?,
        )
    }
}

/// One retained event in provider receipt order.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ObservationEvent {
    pub sequence: u64,
    pub offset_micros: u64,
    pub kind: ObservationEventKind,
}

/// Why an observation scope stopped.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum ObservationTermination {
    Finished,
    Cancelled,
    Interrupted,
    DeadlineReached,
    EventLimitReached,
    ProviderDisconnected,
}

/// Why a count could not be reported honestly.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum MeasurementUnavailableReason {
    NotCollected,
    ProviderDidNotReport,
}

/// A measured count or an explicit provider reason it cannot be known.
pub type MeasuredCount = yosoi_types::FlatMeasured<u64, MeasurementUnavailableReason>;

/// Admission, retention, and loss facts for one measurement class.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ObservationCountAccounting {
    pub admitted: MeasuredCount,
    pub retained: MeasuredCount,
    pub dropped: MeasuredCount,
}

/// Terminal accounting for one provider observation scope.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize)]
pub struct ObservationAccounting {
    /// All observation events, including network lifecycle events.
    pub events: ObservationCountAccounting,
    /// Runtime console and exception events only.
    pub runtime_events: ObservationCountAccounting,
    /// Runtime diagnostic UTF-8 bytes only.
    pub runtime_bytes: ObservationCountAccounting,
    pub in_flight_requests: MeasuredCount,
}

/// Owned, secret-safe terminal result of one observation scope.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct QuietSettlementProof {
    /// Start of the event-free interval, relative to observation arming.
    pub quiet_since_offset_micros: u64,
    /// Time at which the provider established settlement, relative to arming.
    pub satisfied_offset_micros: u64,
    /// Relevant requests still in flight when settlement was established.
    pub relevant_in_flight: u64,
    /// Accounting scoped to `(quiet_since_offset_micros,
    /// satisfied_offset_micros]`.
    pub event_accounting: ObservationCountAccounting,
}

/// A terminal, non-success outcome from live quiet settlement.
#[derive(Debug, Clone, Copy, PartialEq, Eq, thiserror::Error)]
pub enum QuietWaitError {
    #[error("quiet duration must be positive")]
    InvalidQuietDuration,
    #[error("relevant in-flight accounting requires network collection")]
    NetworkAccountingUnavailable,
    #[error("page renderer crashed during observation")]
    RendererCrashed,
    #[error("quiet-settlement deadline reached")]
    DeadlineReached,
    #[error("observation terminated before quiet settlement: {0:?}")]
    ObservationTerminated(ObservationTermination),
    #[error("quiet-settlement progress was lost")]
    ProgressLost,
}

/// Owned, secret-safe terminal result of one observation scope.
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct ObservationReport {
    pub started_at_unix_ms: Option<u64>,
    pub elapsed_micros: u64,
    pub termination: ObservationTermination,
    pub events: Vec<ObservationEvent>,
    pub diagnostics: Vec<RuntimeDiagnostic>,
    pub diagnostic_bytes_retained: usize,
    pub diagnostic_bytes_dropped: usize,
    /// Configured aggregate diagnostic retention bound, retained independently
    /// of how many bytes happened to be observed.
    pub diagnostic_byte_limit: ByteLimit,
    pub accounting: ObservationAccounting,
    pub cleanup_complete: bool,
}

/// An armed observation that owns all listener and collector tasks.
///
/// Dropping the scope, including by cancelling a future that owns it, aborts
/// the coordinator. Its task guard then aborts every collector so listeners
/// cannot outlive the scope.
/// Latest secret-safe progress visible without consuming the observation.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub struct ObservationCheckpoint {
    pub last_event_offset_micros: u64,
    pub termination: Option<ObservationTermination>,
    pub renderer_crashed: bool,
}

pub struct ObservationScope {
    stop: Option<oneshot::Sender<StopRequest>>,
    worker: Option<JoinHandle<Result<ObservationReport>>>,
    progress: broadcast::Receiver<ObservationProgress>,
    latest_progress: Option<ObservationProgress>,
    armed_at: Instant,
    collects_network: bool,
}

impl fmt::Debug for ObservationScope {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        formatter
            .debug_struct("ObservationScope")
            .finish_non_exhaustive()
    }
}

impl ObservationScope {
    pub(in crate::internal::browser) async fn arm(
        page: CdpPage,
        options: ObservationOptions,
    ) -> Result<Self> {
        let options = options.validate()?;
        let started = Instant::now();
        let started_at_unix_ms = unix_millis(SystemTime::now());
        let capacity = options.max_events.clamp(1, 1_024);
        let listener_capacity =
            NonZeroUsize::new(capacity).ok_or(VoidCrawlError::InvalidInput {
                operation: "observation_scope",
                reason: "event listener capacity must be positive",
            })?;
        let listener_config =
            EventListenerConfig::new(listener_capacity, EventOverflowPolicy::DropNewest);
        let (event_tx, event_rx) = mpsc::channel(capacity);
        let mut streams = RegisteredStreams::new();

        if options.collect_network {
            streams.requests = Some(
                page.event_listener::<EventRequestWillBeSent>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            );
            streams.responses = Some(
                page.event_listener::<EventResponseReceived>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            );
            streams.finished = Some(
                page.event_listener::<EventLoadingFinished>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            );
            streams.failed = Some(
                page.event_listener::<EventLoadingFailed>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            );
        }
        if options.collect_console {
            streams.console = Some(
                page.event_listener::<EventConsoleApiCalled>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            );
        }
        if options.collect_exceptions {
            streams.exceptions = Some(
                page.event_listener::<EventExceptionThrown>(listener_config)
                    .await
                    .map_err(|error| VoidCrawlError::PageError(error.to_string()))?,
            );
        }

        let collectors = streams.spawn(event_tx);
        let collect_events =
            options.collect_network || options.collect_console || options.collect_exceptions;
        let (stop, stop_rx) = oneshot::channel();
        let progress_capacity = options.max_events.clamp(1, 1_024).saturating_add(1);
        let (progress_tx, progress) = broadcast::channel(progress_capacity);
        let worker = tokio::spawn(run_scope(ScopeWorkerInputs {
            page: page.clone(),
            collect_events,
            events_rx: event_rx,
            stop_rx,
            collectors,
            options,
            started,
            started_at_unix_ms,
            progress: progress_tx,
        }));
        Ok(Self {
            stop: Some(stop),
            worker: Some(worker),
            progress,
            latest_progress: None,
            armed_at: started,
            collects_network: options.collect_network,
        })
    }

    /// Wait until every admitted relevant event has been followed by `quiet`
    /// and the relevant in-flight count is at most `maximum_in_flight`.
    ///
    /// The absolute deadline is caller-owned. This method borrows the scope so
    /// cancellation of this future leaves [`Self::cancel`] and [`Self::finish`]
    /// available for obtaining the partial owned report.
    /// Return the newest available event/terminal checkpoint without waiting.
    /// This drains stale progress messages so callers never act on an older
    /// non-terminal update after the terminal update was already delivered.
    pub fn checkpoint(&mut self) -> Option<ObservationCheckpoint> {
        let mut latest = self.latest_progress;
        loop {
            match self.progress.try_recv() {
                Ok(progress) => latest = Some(progress),
                Err(
                    broadcast::error::TryRecvError::Empty | broadcast::error::TryRecvError::Closed,
                ) => break,
                Err(broadcast::error::TryRecvError::Lagged(_)) => {}
            }
        }
        self.latest_progress = latest;
        latest.map(|progress| ObservationCheckpoint {
            last_event_offset_micros: progress.last_event_offset_micros,
            termination: progress.termination,
            renderer_crashed: progress.renderer_crashed,
        })
    }

    pub async fn wait_for_quiet(
        &mut self,
        quiet: Duration,
        maximum_in_flight: usize,
        deadline: Instant,
    ) -> StdResult<QuietSettlementProof, QuietWaitError> {
        if quiet.is_zero() {
            return Err(QuietWaitError::InvalidQuietDuration);
        }
        if !self.collects_network {
            return Err(QuietWaitError::NetworkAccountingUnavailable);
        }
        let initial = self.latest_progress.take();
        let result = wait_for_quiet_progress(
            &mut self.progress,
            initial,
            quiet,
            maximum_in_flight,
            deadline,
        )
        .await;
        if let Ok(proof) = &result {
            let last_event_at = self
                .armed_at
                .checked_add(Duration::from_micros(proof.quiet_since_offset_micros))
                .unwrap_or(self.armed_at);
            self.latest_progress = Some(ObservationProgress {
                armed_at: self.armed_at,
                last_event_offset_micros: proof.quiet_since_offset_micros,
                last_event_at,
                relevant_in_flight: usize::try_from(proof.relevant_in_flight).unwrap_or(usize::MAX),
                has_admitted_event: true,
                has_lost_events: false,
                renderer_crashed: false,
                termination: None,
            });
        }
        result
    }

    /// Stop normally and return every event retained before the stop won.
    pub async fn finish(self) -> Result<ObservationReport> {
        self.stop_with(StopRequest::Finished).await
    }

    /// Stop because the caller cancelled the operation explicitly.
    pub async fn cancel(self) -> Result<ObservationReport> {
        self.stop_with(StopRequest::Cancelled).await
    }

    /// Stop because an explicit interruption parked the page.
    pub async fn interrupt(self) -> Result<ObservationReport> {
        self.stop_with(StopRequest::Interrupted).await
    }

    /// Wait for a renderer crash in normal CDP mode, deadline, event limit, or
    /// provider disconnect.
    pub async fn wait(mut self) -> Result<ObservationReport> {
        self.join_worker().await
    }

    async fn stop_with(mut self, stop: StopRequest) -> Result<ObservationReport> {
        if let Some(sender) = self.stop.take() {
            let _ = sender.send(stop);
        }
        self.join_worker().await
    }

    async fn join_worker(&mut self) -> Result<ObservationReport> {
        // Keep the handle in `self` across the await: if this outer future is
        // cancelled, `Drop` still owns and aborts the coordinator.
        self.worker
            .as_mut()
            .ok_or_else(|| VoidCrawlError::Other("observation scope already consumed".into()))?
            .await
            .map_err(|error| VoidCrawlError::Other(format!("observation worker failed: {error}")))?
    }
}

impl ObservationReport {
    /// Canonical aggregate accounting for all runtime diagnostic bytes.
    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        let spec = BrowserByteSpec::new(
            BrowserByteDomain::RuntimeDiagnosticUtf8,
            self.diagnostic_byte_limit,
            BrowserLimitScope::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::CaptureAggregate,
        );
        let observed = ByteCount::try_from_usize(
            self.diagnostic_bytes_retained
                .checked_add(self.diagnostic_bytes_dropped)
                .ok_or(void_crawl_core::BrowserByteAccountingError::Overflow)?,
        )?;
        let retained = ByteCount::try_from_usize(self.diagnostic_bytes_retained)?;
        let discarded = ByteCount::try_from_usize(self.diagnostic_bytes_dropped)?;
        let accounting = BrowserByteAccounting::new(
            observed,
            retained,
            MeasuredBrowserBytes::Known { value: discarded },
        )?;
        if self.termination == ObservationTermination::Finished {
            return BrowserByteReport::from_known_extent(
                BrowserByteDomain::RuntimeDiagnosticUtf8,
                Some(spec),
                observed,
                retained,
            );
        }

        let unknown_loss = MeasuredBrowserBytes::Unavailable {
            reason: BrowserByteMeasurementUnavailableReason::CaptureEndedEarly,
        };
        BrowserByteReport::truncated(
            BrowserByteDomain::RuntimeDiagnosticUtf8,
            Some(spec),
            accounting,
            unknown_loss,
            unknown_loss,
        )
    }
}

impl Drop for ObservationScope {
    fn drop(&mut self) {
        if let Some(worker) = self.worker.take() {
            worker.abort();
        }
    }
}

#[derive(Debug, Clone, Copy)]
enum StopRequest {
    Finished,
    Cancelled,
    Interrupted,
}

struct RegisteredStreams {
    requests: Option<EventStream<EventRequestWillBeSent>>,
    responses: Option<EventStream<EventResponseReceived>>,
    finished: Option<EventStream<EventLoadingFinished>>,
    failed: Option<EventStream<EventLoadingFailed>>,
    console: Option<EventStream<EventConsoleApiCalled>>,
    exceptions: Option<EventStream<EventExceptionThrown>>,
}

impl RegisteredStreams {
    const fn new() -> Self {
        Self {
            requests: None,
            responses: None,
            finished: None,
            failed: None,
            console: None,
            exceptions: None,
        }
    }

    fn spawn(mut self, sender: mpsc::Sender<RawSignal>) -> CollectorTasks {
        let mut tasks = Vec::new();
        if let Some(stream) = self.requests.take() {
            tasks.push(spawn_requests(stream, sender.clone()));
        }
        if let Some(stream) = self.responses.take() {
            tasks.push(spawn_simple(
                stream,
                sender.clone(),
                ObservationEventKind::ResponseReceived,
                |_| None,
            ));
        }
        if let Some(stream) = self.finished.take() {
            tasks.push(spawn_simple(
                stream,
                sender.clone(),
                ObservationEventKind::RequestFinished,
                |event: &EventLoadingFinished| {
                    Some(RequestTransition::Finished(
                        event.request_id.inner().clone(),
                    ))
                },
            ));
        }
        if let Some(stream) = self.failed.take() {
            tasks.push(spawn_simple(
                stream,
                sender.clone(),
                ObservationEventKind::RequestFailed,
                |event: &EventLoadingFailed| {
                    Some(RequestTransition::Finished(
                        event.request_id.inner().clone(),
                    ))
                },
            ));
        }
        if let Some(stream) = self.console.take() {
            tasks.push(spawn_console(stream, sender.clone()));
        }
        if let Some(stream) = self.exceptions.take() {
            tasks.push(spawn_exceptions(stream, sender));
        }
        CollectorTasks(tasks)
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

#[derive(Debug)]
enum RawSignal {
    Event {
        kind: ObservationEventKind,
        request: Option<RequestTransition>,
        diagnostic: Option<RawDiagnostic>,
    },
    Lagged {
        dropped: u64,
        runtime: bool,
    },
    StreamClosed,
}

#[derive(Debug)]
enum RequestTransition {
    Started(String),
    Finished(String),
}

#[derive(Debug)]
struct RawDiagnostic {
    kind: RuntimeDiagnosticKind,
    text: String,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq)]
enum RetainOutcome {
    Continue,
    EventLimitReached,
    StreamClosed,
}

#[derive(Debug, Clone, Copy)]
struct ObservationProgress {
    armed_at: Instant,
    last_event_offset_micros: u64,
    last_event_at: Instant,
    relevant_in_flight: usize,
    has_admitted_event: bool,
    has_lost_events: bool,
    renderer_crashed: bool,
    termination: Option<ObservationTermination>,
}

async fn wait_for_quiet_progress(
    progress: &mut broadcast::Receiver<ObservationProgress>,
    initial: Option<ObservationProgress>,
    quiet: Duration,
    maximum_in_flight: usize,
    deadline: Instant,
) -> StdResult<QuietSettlementProof, QuietWaitError> {
    let mut current = match initial {
        Some(progress) => progress,
        None => progress
            .recv()
            .await
            .map_err(|_| QuietWaitError::ProgressLost)?,
    };
    let settlement_started = Instant::now();
    if current.last_event_at < settlement_started {
        current.last_event_at = settlement_started;
        current.last_event_offset_micros =
            duration_micros(settlement_started.saturating_duration_since(current.armed_at));
    }
    loop {
        if current.renderer_crashed {
            return Err(QuietWaitError::RendererCrashed);
        }
        if let Some(termination) = current.termination {
            return Err(QuietWaitError::ObservationTerminated(termination));
        }
        if current.has_lost_events {
            return Err(QuietWaitError::ProgressLost);
        }
        let quiet_since = current.last_event_offset_micros;
        let quiet_at = current
            .last_event_at
            .checked_add(quiet)
            .ok_or(QuietWaitError::DeadlineReached)?;
        tokio::select! {
            biased;
            () = time::sleep_until(deadline) => return Err(QuietWaitError::DeadlineReached),
            update = progress.recv() => {
                current = match update {
                    Ok(update) => update,
                    Err(
                        broadcast::error::RecvError::Lagged(_)
                        | broadcast::error::RecvError::Closed,
                    ) => {
                        return Err(QuietWaitError::ProgressLost);
                    }
                };
            }
            () = time::sleep_until(quiet_at), if current.has_admitted_event && current.relevant_in_flight <= maximum_in_flight => {
                let satisfied = duration_micros(
                    Instant::now().saturating_duration_since(current.armed_at),
                );
                let zero = MeasuredCount::Known { value: 0 };
                return Ok(QuietSettlementProof {
                    quiet_since_offset_micros: quiet_since,
                    satisfied_offset_micros: satisfied,
                    relevant_in_flight: u64::try_from(current.relevant_in_flight)
                        .map_err(|_| QuietWaitError::ProgressLost)?,
                    event_accounting: ObservationCountAccounting {
                        admitted: zero,
                        retained: zero,
                        dropped: zero,
                    },
                });
            }
        }
    }
}

#[expect(
    clippy::too_many_arguments,
    reason = "bounded collector accounting is kept explicit"
)]
fn retain_signal(
    signal: RawSignal,
    events: &mut Vec<ObservationEvent>,
    in_flight: &mut HashSet<String>,
    max_events: usize,
    offset_micros: u64,
    diagnostics: &mut Vec<RuntimeDiagnostic>,
    diagnostic_bytes_retained: &mut usize,
    diagnostic_bytes_dropped: &mut usize,
    _max_diagnostic_bytes: usize,
    diagnostic_budget: &mut BrowserByteBudget,
) -> RetainOutcome {
    let RawSignal::Event {
        kind,
        request,
        diagnostic,
    } = signal
    else {
        return RetainOutcome::StreamClosed;
    };
    if let Some(request) = request {
        match request {
            RequestTransition::Started(id) => {
                in_flight.insert(id);
            }
            RequestTransition::Finished(id) => {
                in_flight.remove(&id);
            }
        }
    }
    let Ok(sequence) = u64::try_from(events.len()) else {
        return RetainOutcome::EventLimitReached;
    };
    events.push(ObservationEvent {
        sequence,
        offset_micros,
        kind,
    });
    if let Some(diagnostic) = diagnostic {
        let complete_bytes = diagnostic.text.len();
        let Ok(complete_count) = u64::try_from(complete_bytes) else {
            return RetainOutcome::EventLimitReached;
        };
        let Ok(admission) = diagnostic_budget.observe_chunk(ByteCount::new(complete_count)) else {
            return RetainOutcome::EventLimitReached;
        };
        let Ok(admitted_prefix_bytes) = usize::try_from(admission.retain_prefix.get()) else {
            return RetainOutcome::EventLimitReached;
        };
        // A byte budget can split a Unicode scalar. Retain only a valid UTF-8
        // prefix; the boundary backoff is loss and must be included below.
        let retained_bytes = utf8_prefix_boundary(&diagnostic.text, admitted_prefix_bytes);
        let Some(dropped_bytes) = complete_bytes.checked_sub(retained_bytes) else {
            return RetainOutcome::EventLimitReached;
        };
        let Some(new_retained) = diagnostic_bytes_retained.checked_add(retained_bytes) else {
            return RetainOutcome::EventLimitReached;
        };
        let Some(new_dropped) = diagnostic_bytes_dropped.checked_add(dropped_bytes) else {
            return RetainOutcome::EventLimitReached;
        };
        let Some(retained_text) = diagnostic.text.get(..retained_bytes) else {
            return RetainOutcome::EventLimitReached;
        };
        *diagnostic_bytes_retained = new_retained;
        *diagnostic_bytes_dropped = new_dropped;
        diagnostics.push(RuntimeDiagnostic {
            event_sequence: sequence,
            kind: diagnostic.kind,
            retained_bytes,
            complete_bytes,
            truncated: retained_bytes < complete_bytes,
            text: ProtectedDiagnosticText(Arc::from(retained_text.as_bytes())),
        });
    }
    if events.len() >= max_events {
        RetainOutcome::EventLimitReached
    } else {
        RetainOutcome::Continue
    }
}

fn utf8_prefix_boundary(text: &str, maximum_bytes: usize) -> usize {
    let mut boundary = maximum_bytes.min(text.len());
    while boundary > 0 && !text.is_char_boundary(boundary) {
        boundary = boundary.saturating_sub(1);
    }
    boundary
}

fn add_dropped_count(total: &mut Option<u64>, dropped: u64) {
    *total = total.and_then(|current| current.checked_add(dropped));
}

fn combined_count(retained: Option<u64>, dropped: Option<u64>) -> Option<u64> {
    retained.and_then(|retained| dropped.and_then(|dropped| retained.checked_add(dropped)))
}

struct ScopeWorkerInputs {
    page: CdpPage,
    collect_events: bool,
    events_rx: mpsc::Receiver<RawSignal>,
    stop_rx: oneshot::Receiver<StopRequest>,
    collectors: CollectorTasks,
    options: ObservationOptions,
    started: Instant,
    started_at_unix_ms: Option<u64>,
    progress: broadcast::Sender<ObservationProgress>,
}

async fn run_scope(inputs: ScopeWorkerInputs) -> Result<ObservationReport> {
    let ScopeWorkerInputs {
        page,
        collect_events,
        mut events_rx,
        mut stop_rx,
        mut collectors,
        options,
        started,
        started_at_unix_ms,
        progress,
    } = inputs;
    let deadline_at = time::Instant::now()
        .checked_add(options.max_duration)
        .unwrap_or_else(time::Instant::now);
    let deadline = time::sleep_until(deadline_at);
    tokio::pin!(deadline);
    let mut events: Vec<ObservationEvent> = Vec::with_capacity(options.max_events.min(1_024));
    let mut diagnostics = Vec::new();
    let mut diagnostic_bytes_retained = 0usize;
    let mut diagnostic_bytes_dropped = 0usize;
    let diagnostic_spec = BrowserByteSpec::new(
        BrowserByteDomain::RuntimeDiagnosticUtf8,
        options.diagnostic_limit().unwrap_or(ByteLimit::one()),
        BrowserLimitScope::RetentionAfterProviderMaterialization,
        BrowserBudgetScope::CaptureAggregate,
    );
    let mut diagnostic_budget = BrowserByteBudget::new(diagnostic_spec);
    let mut in_flight = HashSet::new();
    let mut listener_events_dropped = Some(0_u64);
    let mut listener_runtime_events_dropped = Some(0_u64);
    let _ = progress.send(ObservationProgress {
        armed_at: started,
        last_event_offset_micros: 0,
        last_event_at: started,
        relevant_in_flight: 0,
        has_admitted_event: false,
        has_lost_events: false,
        renderer_crashed: false,
        termination: None,
    });

    let termination = loop {
        tokio::select! {
            biased;
            stop = &mut stop_rx => {
                if page.is_renderer_crashed() {
                    break None;
                }
                break match stop {
                    Ok(StopRequest::Finished) => Some(ObservationTermination::Finished),
                    Ok(StopRequest::Cancelled) | Err(_) => Some(ObservationTermination::Cancelled),
                    Ok(StopRequest::Interrupted) => Some(ObservationTermination::Interrupted),
                };
            }
            () = page.wait_for_renderer_crash() => {
                break None;
            }
            () = &mut deadline => {
                if page.is_renderer_crashed() {
                    break None;
                }
                break Some(ObservationTermination::DeadlineReached);
            }
            signal = events_rx.recv(), if collect_events => {
                match signal {
                    Some(RawSignal::Lagged { dropped, runtime }) => {
                        add_dropped_count(&mut listener_events_dropped, dropped);
                        if runtime {
                            add_dropped_count(&mut listener_runtime_events_dropped, dropped);
                        }
                        let last_event_offset_micros =
                            events.last().map_or(0, |event| event.offset_micros);
                        let last_event_at = instant_at_offset(started, last_event_offset_micros);
                        let _ = progress.send(ObservationProgress {
                            armed_at: started,
                            last_event_offset_micros,
                            last_event_at,
                            relevant_in_flight: in_flight.len(),
                            has_admitted_event: !events.is_empty(),
                            has_lost_events: true,
                            renderer_crashed: false,
                            termination: None,
                        });
                    }
                    Some(signal) => match retain_signal(
                        signal,
                        &mut events,
                        &mut in_flight,
                        options.max_events,
                        duration_micros(started.elapsed()),
                        &mut diagnostics,
                        &mut diagnostic_bytes_retained,
                        &mut diagnostic_bytes_dropped,
                        options.max_diagnostic_bytes,
                        &mut diagnostic_budget,
                    ) {
                        RetainOutcome::Continue => {
                            let last_event_offset_micros =
                                events.last().map_or(0, |event| event.offset_micros);
                            let last_event_at = instant_at_offset(started, last_event_offset_micros);
                            let _ = progress.send(ObservationProgress {
                                armed_at: started,
                                last_event_offset_micros,
                                last_event_at,
                                relevant_in_flight: in_flight.len(),
                                has_admitted_event: true,
                                has_lost_events: listener_events_dropped != Some(0),
                                renderer_crashed: false,
                                termination: None,
                            });
                        }
                        RetainOutcome::EventLimitReached => {
                            break Some(ObservationTermination::EventLimitReached);
                        }
                        RetainOutcome::StreamClosed => {
                            if page.is_renderer_crashed() {
                                break None;
                            }
                            break Some(ObservationTermination::ProviderDisconnected);
                        }
                    },
                    None => {
                        if page.is_renderer_crashed() {
                            break None;
                        }
                        break Some(ObservationTermination::ProviderDisconnected);
                    }
                }
            }
        }
    };

    let Some(mut termination) = termination else {
        let _ = progress.send(ObservationProgress {
            armed_at: started,
            last_event_offset_micros: events.last().map_or(0, |event| event.offset_micros),
            last_event_at: Instant::now(),
            relevant_in_flight: in_flight.len(),
            has_admitted_event: !events.is_empty(),
            has_lost_events: listener_events_dropped != Some(0),
            renderer_crashed: true,
            termination: None,
        });
        collectors.shutdown().await;
        return Err(VoidCrawlError::RendererCrashed);
    };

    let last_event_offset_micros = events.last().map_or(0, |event| event.offset_micros);
    let last_event_at = instant_at_offset(started, last_event_offset_micros);
    let _ = progress.send(ObservationProgress {
        armed_at: started,
        last_event_offset_micros,
        last_event_at,
        relevant_in_flight: in_flight.len(),
        has_admitted_event: !events.is_empty(),
        has_lost_events: listener_events_dropped != Some(0),
        renderer_crashed: false,
        termination: Some(termination),
    });
    collectors.shutdown().await;
    while events.len() < options.max_events {
        let Ok(signal) = events_rx.try_recv() else {
            break;
        };
        if let RawSignal::Lagged { dropped, runtime } = signal {
            add_dropped_count(&mut listener_events_dropped, dropped);
            if runtime {
                add_dropped_count(&mut listener_runtime_events_dropped, dropped);
            }
            continue;
        }
        match retain_signal(
            signal,
            &mut events,
            &mut in_flight,
            options.max_events,
            duration_micros(started.elapsed()),
            &mut diagnostics,
            &mut diagnostic_bytes_retained,
            &mut diagnostic_bytes_dropped,
            options.max_diagnostic_bytes,
            &mut diagnostic_budget,
        ) {
            RetainOutcome::Continue | RetainOutcome::StreamClosed => {}
            RetainOutcome::EventLimitReached => {
                if termination == ObservationTermination::Finished {
                    termination = ObservationTermination::EventLimitReached;
                }
                break;
            }
        }
    }
    let event_count = u64::try_from(events.len()).ok();
    let runtime_event_count = u64::try_from(diagnostics.len()).ok();
    let retained_byte_count = u64::try_from(diagnostic_bytes_retained).ok();
    let dropped_byte_count = u64::try_from(diagnostic_bytes_dropped).ok();
    let observed_byte_count = diagnostic_bytes_retained
        .checked_add(diagnostic_bytes_dropped)
        .and_then(|value| u64::try_from(value).ok());
    let known = |value: Option<u64>| {
        value.map_or(
            MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::ProviderDidNotReport,
            },
            |value| MeasuredCount::Known { value },
        )
    };
    let measured = |value: Option<u64>| {
        value.map_or(
            MeasuredCount::Unavailable {
                reason: MeasurementUnavailableReason::ProviderDidNotReport,
            },
            |value| MeasuredCount::Known { value },
        )
    };
    let unknown = MeasuredCount::Unavailable {
        reason: MeasurementUnavailableReason::ProviderDidNotReport,
    };
    // The provider does not expose an upstream completeness count. The new
    // bounded listener gives an exact local lower bound, but zero local loss
    // cannot prove that Chromium emitted every relevant event.
    let events_dropped = unknown;
    let runtime_events_dropped = if termination == ObservationTermination::Finished {
        measured(listener_runtime_events_dropped)
    } else {
        unknown
    };
    Ok(ObservationReport {
        started_at_unix_ms,
        elapsed_micros: duration_micros(started.elapsed()),
        termination,
        accounting: ObservationAccounting {
            events: ObservationCountAccounting {
                admitted: known(combined_count(event_count, listener_events_dropped)),
                retained: known(event_count),
                dropped: events_dropped,
            },
            runtime_events: ObservationCountAccounting {
                admitted: known(combined_count(
                    runtime_event_count,
                    listener_runtime_events_dropped,
                )),
                retained: known(runtime_event_count),
                dropped: runtime_events_dropped,
            },
            runtime_bytes: ObservationCountAccounting {
                admitted: known(observed_byte_count),
                retained: known(retained_byte_count),
                dropped: known(dropped_byte_count),
            },
            in_flight_requests: if options.collect_network && listener_events_dropped == Some(0) {
                known(u64::try_from(in_flight.len()).ok())
            } else {
                MeasuredCount::Unavailable {
                    reason: MeasurementUnavailableReason::NotCollected,
                }
            },
        },
        events,
        diagnostics,
        diagnostic_bytes_retained,
        diagnostic_bytes_dropped,
        diagnostic_byte_limit: diagnostic_budget.spec().limit(),
        cleanup_complete: true,
    })
}

fn spawn_requests(
    mut stream: EventStream<EventRequestWillBeSent>,
    sender: mpsc::Sender<RawSignal>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(delivery) = stream.next().await {
            let signal = match delivery {
                EventDelivery::Event(event) => {
                    let kind = if matches!(event.r#type, Some(ResourceType::Document)) {
                        ObservationEventKind::DocumentRequestStarted
                    } else {
                        ObservationEventKind::ResourceRequestStarted
                    };
                    RawSignal::Event {
                        kind,
                        request: Some(RequestTransition::Started(event.request_id.inner().clone())),
                        diagnostic: None,
                    }
                }
                EventDelivery::Lagged { dropped } => RawSignal::Lagged {
                    dropped: dropped.get(),
                    runtime: false,
                },
            };
            if sender.send(signal).await.is_err() {
                return;
            }
        }
        let _ = sender.send(RawSignal::StreamClosed).await;
    })
}

fn spawn_simple<T, F>(
    mut stream: EventStream<T>,
    sender: mpsc::Sender<RawSignal>,
    kind: ObservationEventKind,
    transition: F,
) -> JoinHandle<()>
where
    T: IntoEventKind + Send + Sync + Unpin + 'static,
    F: Fn(&T) -> Option<RequestTransition> + Send + 'static,
{
    tokio::spawn(async move {
        while let Some(delivery) = stream.next().await {
            let signal = match delivery {
                EventDelivery::Event(event) => RawSignal::Event {
                    kind,
                    request: transition(&event),
                    diagnostic: None,
                },
                EventDelivery::Lagged { dropped } => RawSignal::Lagged {
                    dropped: dropped.get(),
                    runtime: false,
                },
            };
            if sender.send(signal).await.is_err() {
                return;
            }
        }
        let _ = sender.send(RawSignal::StreamClosed).await;
    })
}

fn spawn_console(
    mut stream: EventStream<EventConsoleApiCalled>,
    sender: mpsc::Sender<RawSignal>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(delivery) = stream.next().await {
            let signal = match delivery {
                EventDelivery::Event(event) => {
                    let text = event
                        .args
                        .iter()
                        .filter_map(|argument| {
                            argument.value.as_ref().map_or_else(
                                || argument.description.clone(),
                                |value| {
                                    value
                                        .as_str()
                                        .map(str::to_string)
                                        .or_else(|| Some(value.to_string()))
                                },
                            )
                        })
                        .collect::<Vec<_>>()
                        .join(" ");
                    RawSignal::Event {
                        kind: ObservationEventKind::ConsoleApiCalled,
                        request: None,
                        diagnostic: Some(RawDiagnostic {
                            kind: RuntimeDiagnosticKind::Console {
                                level: event.r#type.as_ref().to_string(),
                            },
                            text,
                        }),
                    }
                }
                EventDelivery::Lagged { dropped } => RawSignal::Lagged {
                    dropped: dropped.get(),
                    runtime: true,
                },
            };
            if sender.send(signal).await.is_err() {
                return;
            }
        }
        let _ = sender.send(RawSignal::StreamClosed).await;
    })
}

fn spawn_exceptions(
    mut stream: EventStream<EventExceptionThrown>,
    sender: mpsc::Sender<RawSignal>,
) -> JoinHandle<()> {
    tokio::spawn(async move {
        while let Some(delivery) = stream.next().await {
            let signal = match delivery {
                EventDelivery::Event(event) => {
                    let mut text = event.exception_details.text.clone();
                    if let Some(description) = event
                        .exception_details
                        .exception
                        .as_ref()
                        .and_then(|exception| exception.description.as_ref())
                        && description != &text
                    {
                        if !text.is_empty() {
                            text.push_str(": ");
                        }
                        text.push_str(description);
                    }
                    RawSignal::Event {
                        kind: ObservationEventKind::RuntimeExceptionThrown,
                        request: None,
                        diagnostic: Some(RawDiagnostic {
                            kind: RuntimeDiagnosticKind::Exception,
                            text,
                        }),
                    }
                }
                EventDelivery::Lagged { dropped } => RawSignal::Lagged {
                    dropped: dropped.get(),
                    runtime: true,
                },
            };
            if sender.send(signal).await.is_err() {
                return;
            }
        }
        let _ = sender.send(RawSignal::StreamClosed).await;
    })
}

fn instant_at_offset(started: Instant, offset_micros: u64) -> Instant {
    started
        .checked_add(Duration::from_micros(offset_micros))
        .unwrap_or_else(Instant::now)
}

fn unix_millis(now: SystemTime) -> Option<u64> {
    now.duration_since(UNIX_EPOCH)
        .ok()
        .and_then(|duration| u64::try_from(duration.as_millis()).ok())
}

fn duration_micros(duration: Duration) -> u64 {
    u64::try_from(duration.as_micros()).unwrap_or(u64::MAX)
}

#[cfg(test)]
#[allow(clippy::expect_used)]
#[path = "observation_lifecycle_tests.rs"]
mod lifecycle_tests;

#[cfg(test)]
#[allow(clippy::expect_used)]
#[path = "observation_progress_tests.rs"]
mod tests;
