//! Opt-in, passive CDP response-body capture.
//!
//! Capture scopes subscribe to Network events before the triggering action.
//! They never intercept requests or inject page-world JavaScript.

#[cfg(feature = "browser")]
#[cfg(test)]
use crate::internal::browser as void_crawl_core;

use std::{
    collections::{HashMap, HashSet},
    fmt,
    io::Read,
    num::NonZeroUsize,
    result::Result as StdResult,
    sync::Arc,
    time::Duration,
};

use crate::internal::types::{ByteCount, ByteLimit};
use base64::{engine::general_purpose::STANDARD as BASE64, read::DecoderReader};
use chromiumoxide::{
    Page as CdpPage,
    cdp::browser_protocol::network::{
        EventLoadingFailed, EventLoadingFinished, EventRequestWillBeSent, EventResponseReceived,
        GetResponseBodyParams, Headers,
    },
    listeners::{EventDelivery, EventListenerConfig, EventOverflowPolicy, EventStream},
};
use futures::StreamExt;
use globset::{Glob, GlobMatcher};
use tokio::{sync::oneshot, task::JoinHandle, time};

use crate::internal::browser::{
    BrowserBudgetScope, BrowserByteAccounting, BrowserByteDomain,
    BrowserByteMeasurementUnavailableReason, BrowserByteReport, BrowserByteReportError,
    BrowserByteSpec, BrowserLimitScope, BrowserPayloadUnavailableReason, MeasuredBrowserBytes,
    error::{Result, VoidCrawlError},
};

/// Default maximum retained body size for one captured response (2 MiB).
pub const DEFAULT_MAX_RESPONSE_BYTES: usize = 2 * 1024 * 1024;
/// Default maximum retained body size across one expectation (8 MiB).
pub const DEFAULT_MAX_TOTAL_RESPONSE_BYTES: usize = 8 * 1024 * 1024;

/// Whether a captured response body is complete, truncated, or unavailable.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResponseBodyState {
    Available,
    Truncated,
    Unavailable,
}

impl ResponseBodyState {
    #[must_use]
    pub const fn as_str(self) -> &'static str {
        match self {
            Self::Available => "available",
            Self::Truncated => "truncated",
            Self::Unavailable => "unavailable",
        }
    }
}

/// A complete response observation captured from CDP.
#[derive(Debug, Clone)]
pub struct CapturedResponse {
    pub url: String,
    pub status: u16,
    pub headers: Vec<(String, String)>,
    /// Headers the browser SENT for this request, sorted by name.
    ///
    /// This is the only place a request-side credential (`Authorization`,
    /// `Cookie`) is observable — `headers` above is response-side only. Callers
    /// that serialize this MUST treat the values as secret.
    ///
    /// Merged from `Network.requestWillBeSent`'s author-level headers and, as a
    /// lower-authority fallback, `Network.Response.requestHeaders` (which is
    /// absent in practice). An `Authorization` header set by page code — the
    /// common bearer-token case — IS captured here.
    ///
    /// KNOWN GAP: browser-managed `Cookie` is NOT captured. Chrome attaches it
    /// after `requestWillBeSent` and reports it only via
    /// `requestWillBeSentExtraInfo`; subscribing to that event was tried and
    /// measured as delivering zero events through the vendored chromiumoxide
    /// 0.9.1, whose network handler does not route it. Read cookie state from
    /// the cookie store instead. Raw `Set-Cookie` is likewise unavailable
    /// (`responseReceivedExtraInfo`, same limitation).
    pub request_headers: Vec<(String, String)>,
    pub mime_type: String,
    pub resource_type: String,
    pub from_cache: bool,
    pub from_service_worker: bool,
    pub body_state: ResponseBodyState,
    pub body_error: Option<String>,
    body: Arc<[u8]>,
    byte_spec: BrowserByteSpec,
    complete_bytes: Option<usize>,
}

impl CapturedResponse {
    #[must_use]
    pub fn body(&self) -> &[u8] {
        &self.body
    }

    pub fn byte_report(&self) -> StdResult<BrowserByteReport, BrowserByteReportError> {
        if self.body_state == ResponseBodyState::Unavailable {
            return BrowserByteReport::unavailable_with_spec(
                BrowserByteDomain::CdpDecodedBody,
                Some(self.byte_spec),
                BrowserPayloadUnavailableReason::ProviderDidNotReport,
            );
        }
        BrowserByteReport::from_known_extent(
            BrowserByteDomain::CdpDecodedBody,
            Some(self.byte_spec),
            ByteCount::try_from_usize(self.complete_bytes.unwrap_or(self.body.len()))?,
            ByteCount::try_from_usize(self.body.len())?,
        )
    }

    pub fn text(&self) -> Result<String> {
        String::from_utf8(self.body.to_vec()).map_err(|e| {
            VoidCrawlError::ResponseBody(format!("response body is not valid UTF-8: {e}"))
        })
    }

    pub fn json(&self) -> Result<serde_json::Value> {
        serde_json::from_slice(&self.body)
            .map_err(|e| VoidCrawlError::ResponseBody(format!("invalid JSON response body: {e}")))
    }
}

/// Memory limits for one response expectation.
#[derive(Debug, Clone, Copy)]
pub struct ResponseCaptureLimits {
    per_response: ByteLimit,
    aggregate: ByteLimit,
}

impl ResponseCaptureLimits {
    pub const fn new(per_response: ByteLimit, aggregate: ByteLimit) -> Self {
        Self {
            per_response,
            aggregate,
        }
    }

    pub const fn per_response(self) -> ByteLimit {
        self.per_response
    }

    pub const fn aggregate(self) -> ByteLimit {
        self.aggregate
    }
}

impl Default for ResponseCaptureLimits {
    fn default() -> Self {
        Self::new(
            ByteLimit::try_from(DEFAULT_MAX_RESPONSE_BYTES).unwrap_or(ByteLimit::one()),
            ByteLimit::try_from(DEFAULT_MAX_TOTAL_RESPONSE_BYTES).unwrap_or(ByteLimit::one()),
        )
    }
}

#[derive(Debug)]
struct Matcher {
    name: String,
    pattern: String,
    glob: GlobMatcher,
}

#[derive(Debug, Clone)]
struct PendingResponse {
    names: Vec<String>,
    url: String,
    status: u16,
    headers: Vec<(String, String)>,
    request_headers: Vec<(String, String)>,
    mime_type: String,
    resource_type: String,
    from_cache: bool,
    from_service_worker: bool,
}

/// Why a response capture stopped.
#[derive(Debug, Clone, Copy, PartialEq, Eq)]
pub enum ResponseCaptureTermination {
    Complete,
    DeadlineReached,
    Cancelled,
    ProviderDisconnected,
}

/// Owned terminal response-capture result, including partial matches and the
/// shared aggregate-budget accounting.
#[derive(Debug, Clone)]
pub struct ResponseCaptureReport {
    pub responses: HashMap<String, CapturedResponse>,
    pub termination: ResponseCaptureTermination,
    pub aggregate_bytes: BrowserByteReport,
}

/// An armed capture. Dropping it aborts its event worker and unregisters its
/// listeners as their streams are dropped.
pub struct ResponseCapture {
    cancel: Option<oneshot::Sender<()>>,
    worker: Option<JoinHandle<Result<ResponseCaptureReport>>>,
    patterns: Vec<String>,
    timeout: Duration,
}

impl fmt::Debug for ResponseCapture {
    fn fmt(&self, f: &mut fmt::Formatter<'_>) -> fmt::Result {
        f.debug_struct("ResponseCapture").finish_non_exhaustive()
    }
}

impl ResponseCapture {
    pub(in crate::internal::browser) async fn arm(
        page: CdpPage,
        patterns: Vec<(String, String)>,
        timeout: Duration,
        limits: ResponseCaptureLimits,
    ) -> Result<Self> {
        if patterns.is_empty() {
            return Err(VoidCrawlError::Other(
                "at least one response pattern is required".into(),
            ));
        }
        let mut names = HashSet::with_capacity(patterns.len());
        if let Some((duplicate, _)) = patterns
            .iter()
            .find(|(name, _)| !names.insert(name.clone()))
        {
            return Err(VoidCrawlError::Other(format!(
                "duplicate response expectation name {duplicate:?}"
            )));
        }

        let matchers = patterns
            .into_iter()
            .map(|(name, pattern)| {
                let matcher = Glob::new(&pattern)
                    .map_err(|e| {
                        VoidCrawlError::Other(format!("invalid URL glob {pattern:?}: {e}"))
                    })?
                    .compile_matcher();
                Ok(Matcher {
                    name,
                    pattern,
                    glob: matcher,
                })
            })
            .collect::<Result<Vec<_>>>()?;

        let listener_capacity = matchers.len().saturating_mul(16).clamp(16, 2_048);
        let listener_capacity = NonZeroUsize::new(listener_capacity).ok_or_else(|| {
            VoidCrawlError::Other("response capture listener capacity must be positive".into())
        })?;
        // Response lifecycle events must be complete to associate a body with
        // its request. Overflow closes the bounded stream and yields the
        // existing incomplete terminal report below.
        let listener_config =
            EventListenerConfig::new(listener_capacity, EventOverflowPolicy::Close);

        // Register every stream before returning the armed scope.
        let requests = page
            .event_listener::<EventRequestWillBeSent>(listener_config)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let responses = page
            .event_listener::<EventResponseReceived>(listener_config)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let finished = page
            .event_listener::<EventLoadingFinished>(listener_config)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;
        let failed = page
            .event_listener::<EventLoadingFailed>(listener_config)
            .await
            .map_err(|e| VoidCrawlError::PageError(e.to_string()))?;

        let pattern_names = matchers
            .iter()
            .map(|matcher| format!("{}={}", matcher.name, matcher.pattern))
            .collect();
        let (cancel, cancel_rx) = oneshot::channel();
        let worker = tokio::spawn(run_capture(
            page, matchers, requests, responses, finished, failed, cancel_rx, timeout, limits,
        ));
        Ok(Self {
            cancel: Some(cancel),
            worker: Some(worker),
            patterns: pattern_names,
            timeout,
        })
    }

    /// Wait for an owned report. Deadlines and provider disconnects are
    /// terminal report states rather than errors, preserving partial matches.
    pub async fn wait_report(mut self) -> Result<ResponseCaptureReport> {
        self.join_worker().await
    }

    /// Wait no longer than `budget`, then cooperatively stop the collector and
    /// return its partial report as `DeadlineReached`. Unlike wrapping
    /// [`Self::wait_report`] in `tokio::time::timeout`, this keeps ownership of
    /// the worker long enough to preserve already captured responses.
    pub async fn wait_report_for(mut self, budget: Duration) -> Result<ResponseCaptureReport> {
        if let Ok(result) = time::timeout(budget, self.join_worker()).await {
            result
        } else {
            if let Some(cancel) = self.cancel.take() {
                let _ = cancel.send(());
            }
            let mut report = self.join_worker().await?;
            report.termination = ResponseCaptureTermination::DeadlineReached;
            Ok(report)
        }
    }

    /// Cooperatively cancel and return all response/accounting facts captured
    /// before cancellation.
    pub async fn cancel_report(mut self) -> Result<ResponseCaptureReport> {
        if let Some(cancel) = self.cancel.take() {
            let _ = cancel.send(());
        }
        self.join_worker().await
    }

    /// Compatibility API: only a complete report is returned; terminal report
    /// states map back to the historical errors.
    pub async fn wait(mut self) -> Result<HashMap<String, CapturedResponse>> {
        let report = self.join_worker().await?;
        match report.termination {
            ResponseCaptureTermination::Complete => Ok(report.responses),
            ResponseCaptureTermination::DeadlineReached => Err(VoidCrawlError::ResponseTimeout {
                patterns: self.patterns.clone(),
                timeout_secs: self.timeout.as_secs_f64(),
            }),
            ResponseCaptureTermination::Cancelled => {
                Err(VoidCrawlError::Other("response capture cancelled".into()))
            }
            ResponseCaptureTermination::ProviderDisconnected => Err(VoidCrawlError::BrowserClosed),
        }
    }

    async fn join_worker(&mut self) -> Result<ResponseCaptureReport> {
        self.worker
            .as_mut()
            .ok_or_else(|| VoidCrawlError::Other("response capture already consumed".into()))?
            .await
            .map_err(|error| {
                VoidCrawlError::Other(format!("response capture worker failed: {error}"))
            })?
    }
}

impl Drop for ResponseCapture {
    fn drop(&mut self) {
        if let Some(worker) = &self.worker {
            worker.abort();
        }
    }
}

#[allow(clippy::too_many_arguments, clippy::cognitive_complexity)]
async fn run_capture(
    page: CdpPage,
    matchers: Vec<Matcher>,
    mut requests: EventStream<EventRequestWillBeSent>,
    mut responses: EventStream<EventResponseReceived>,
    mut finished: EventStream<EventLoadingFinished>,
    mut failed: EventStream<EventLoadingFailed>,
    mut cancel: oneshot::Receiver<()>,
    timeout: Duration,
    limits: ResponseCaptureLimits,
) -> Result<ResponseCaptureReport> {
    let wanted = matchers.len();
    let mut pending: HashMap<String, PendingResponse> = HashMap::new();
    let mut captured: HashMap<String, CapturedResponse> = HashMap::new();
    // Request headers arrive on their own events, before the response they
    // belong to, so they are accumulated by request id and attached later.
    let mut sent_headers: HashMap<String, HashMap<String, String>> = HashMap::new();
    let mut retained = 0usize;
    let mut observed = 0usize;
    let deadline_at = time::Instant::now()
        .checked_add(timeout)
        .unwrap_or_else(time::Instant::now);
    let deadline = time::sleep_until(deadline_at);
    tokio::pin!(deadline);

    loop {
        if captured.len() == wanted {
            return capture_report(
                captured,
                observed,
                retained,
                limits,
                ResponseCaptureTermination::Complete,
            );
        }
        tokio::select! {
            maybe_request = requests.next() => {
                let Some(EventDelivery::Event(event)) = maybe_request else {
                    return capture_report(captured, observed, retained, limits, ResponseCaptureTermination::ProviderDisconnected);
                };
                // Author-level headers (what the page asked to send). Recorded
                // for every request, not just matching ones — the glob is
                // checked against the response, which arrives later.
                merge_sent_headers(
                    &mut sent_headers,
                    event.request_id.inner(),
                    flatten_headers(event.request.headers.inner()),
                    false,
                );
                let Some(response) = event.redirect_response.as_ref() else { continue };
                let names = matchers.iter()
                    .filter(|m| !captured.contains_key(&m.name) && m.glob.is_match(&response.url))
                    .map(|m| m.name.clone())
                    .collect::<Vec<_>>();
                if names.is_empty() {
                    continue;
                }
                let meta = PendingResponse {
                    names,
                    url: response.url.clone(),
                    status: u16::try_from(response.status).unwrap_or_default(),
                    headers: flatten_headers(response.headers.inner()),
                    request_headers: take_sent_headers(
                        &mut sent_headers,
                        event.request_id.inner(),
                    ),
                    mime_type: response.mime_type.clone(),
                    resource_type: event.r#type.as_ref().map_or_else(
                        || "other".to_string(),
                        |kind| format!("{kind:?}").to_lowercase(),
                    ),
                    from_cache: response.from_disk_cache.unwrap_or(false)
                        || response.from_prefetch_cache.unwrap_or(false),
                    from_service_worker: response.from_service_worker.unwrap_or(false),
                };
                let response = unavailable_response(
                    meta.clone(),
                    "redirect response bodies are unavailable through CDP".into(),
                    limits,
                );
                for name in meta.names {
                    captured.entry(name).or_insert_with(|| response.clone());
                }
            }
            maybe_response = responses.next() => {
                let Some(EventDelivery::Event(event)) = maybe_response else {
                    return capture_report(captured, observed, retained, limits, ResponseCaptureTermination::ProviderDisconnected);
                };
                let names = matchers.iter()
                    .filter(|m| !captured.contains_key(&m.name) && m.glob.is_match(&event.response.url))
                    .map(|m| m.name.clone())
                    .collect::<Vec<_>>();
                if names.is_empty() {
                    continue;
                }
                let request_id = event.request_id.inner().clone();
                // Lowest-authority source; usually absent in practice, so it
                // only fills gaps the request events did not already cover.
                merge_sent_headers(
                    &mut sent_headers,
                    &request_id,
                    optional_headers(event.response.request_headers.as_ref()),
                    false,
                );
                pending.insert(request_id, PendingResponse {
                    names,
                    url: event.response.url.clone(),
                    status: u16::try_from(event.response.status).unwrap_or_default(),
                    headers: flatten_headers(event.response.headers.inner()),
                    // Resolved at finalize, not here: requestWillBeSentExtraInfo
                    // may still be in flight and is the only source of `Cookie`.
                    request_headers: Vec::new(),
                    mime_type: event.response.mime_type.clone(),
                    resource_type: format!("{:?}", event.r#type).to_lowercase(),
                    from_cache: event.response.from_disk_cache.unwrap_or(false)
                        || event.response.from_prefetch_cache.unwrap_or(false),
                    from_service_worker: event.response.from_service_worker.unwrap_or(false),
                });
            }
            maybe_finished = finished.next() => {
                let Some(EventDelivery::Event(event)) = maybe_finished else {
                    return capture_report(captured, observed, retained, limits, ResponseCaptureTermination::ProviderDisconnected);
                };
                let request_id = event.request_id.inner().clone();
                let Some(mut meta) = pending.remove(&request_id) else { continue };
                meta.request_headers = take_sent_headers(&mut sent_headers, &request_id);
                let body_result = page.execute(GetResponseBodyParams::new(event.request_id.clone())).await;
                let response = match body_result {
                    Ok(result) => match bounded_response(
                        meta.clone(),
                        result.result.body,
                        result.result.base64_encoded,
                        &mut observed,
                        &mut retained,
                        limits,
                    ) {
                        Ok(response) => response,
                        Err(error) => unavailable_response(meta.clone(), error.to_string(), limits),
                    },
                    Err(error) => unavailable_response(meta.clone(), error.to_string(), limits),
                };
                for name in meta.names {
                    captured.entry(name).or_insert_with(|| response.clone());
                }
            }
            maybe_failed = failed.next() => {
                let Some(EventDelivery::Event(event)) = maybe_failed else {
                    return capture_report(captured, observed, retained, limits, ResponseCaptureTermination::ProviderDisconnected);
                };
                let request_id = event.request_id.inner().clone();
                let Some(mut meta) = pending.remove(&request_id) else { continue };
                meta.request_headers = take_sent_headers(&mut sent_headers, &request_id);
                let response = unavailable_response(meta.clone(), event.error_text.clone(), limits);
                for name in meta.names {
                    captured.entry(name).or_insert_with(|| response.clone());
                }
            }
            _ = &mut cancel => {
                return capture_report(captured, observed, retained, limits, ResponseCaptureTermination::Cancelled);
            }
            () = &mut deadline => {
                return capture_report(captured, observed, retained, limits, ResponseCaptureTermination::DeadlineReached);
            }
        }
    }
}

fn bounded_response(
    meta: PendingResponse,
    body: String,
    base64_encoded: bool,
    observed_total: &mut usize,
    retained_total: &mut usize,
    limits: ResponseCaptureLimits,
) -> Result<CapturedResponse> {
    let aggregate = limits
        .aggregate()
        .as_usize()
        .map_err(|error| VoidCrawlError::Other(error.to_string()))?;
    let per_response = limits
        .per_response()
        .as_usize()
        .map_err(|error| VoidCrawlError::Other(error.to_string()))?;
    let remaining = aggregate.saturating_sub(*retained_total);
    let retention_limit = per_response.min(remaining);

    // Chromium has already materialized `body` as a String. For plain bodies,
    // `into_bytes` reuses that allocation. Base64 is decoded incrementally so
    // only the effective retained prefix plus a small decode buffer is held.
    let (retained_body, complete_bytes) = if base64_encoded {
        let mut decoder = DecoderReader::new(body.as_bytes(), &BASE64);
        let mut retained_body = Vec::with_capacity(retention_limit.min(8192));
        let mut decoded = 0usize;
        let mut chunk = [0_u8; 8192];
        loop {
            let read = decoder.read(&mut chunk).map_err(|error| {
                VoidCrawlError::ResponseBody(format!("invalid base64 response body: {error}"))
            })?;
            if read == 0 {
                break;
            }
            decoded = decoded.checked_add(read).ok_or_else(|| {
                VoidCrawlError::Other("decoded response byte count overflowed".into())
            })?;
            let admit = retention_limit
                .saturating_sub(retained_body.len())
                .min(read);
            retained_body.extend_from_slice(chunk.get(..admit).unwrap_or(&[]));
        }
        (retained_body, decoded)
    } else {
        let mut bytes = body.into_bytes();
        let complete = bytes.len();
        bytes.truncate(retention_limit);
        (bytes, complete)
    };
    *observed_total = observed_total.checked_add(complete_bytes).ok_or_else(|| {
        VoidCrawlError::Other("response observation byte count overflowed".into())
    })?;
    *retained_total = retained_total
        .checked_add(retained_body.len())
        .ok_or_else(|| VoidCrawlError::Other("response retained byte count overflowed".into()))?;

    let aggregate_bound = remaining < per_response && retained_body.len() < complete_bytes;
    let byte_spec = BrowserByteSpec::new(
        BrowserByteDomain::CdpDecodedBody,
        if aggregate_bound {
            limits.aggregate()
        } else {
            limits.per_response()
        },
        BrowserLimitScope::RetentionAfterProviderMaterialization,
        if aggregate_bound {
            BrowserBudgetScope::CaptureAggregate
        } else {
            BrowserBudgetScope::PerPayload
        },
    );
    Ok(CapturedResponse {
        url: meta.url,
        status: meta.status,
        headers: meta.headers,
        request_headers: meta.request_headers,
        mime_type: meta.mime_type,
        resource_type: meta.resource_type,
        from_cache: meta.from_cache,
        from_service_worker: meta.from_service_worker,
        body_state: if retained_body.len() < complete_bytes {
            ResponseBodyState::Truncated
        } else {
            ResponseBodyState::Available
        },
        body_error: None,
        body: Arc::from(retained_body),
        byte_spec,
        complete_bytes: Some(complete_bytes),
    })
}

fn unavailable_response(
    meta: PendingResponse,
    error: String,
    limits: ResponseCaptureLimits,
) -> CapturedResponse {
    CapturedResponse {
        url: meta.url,
        status: meta.status,
        headers: meta.headers,
        request_headers: meta.request_headers,
        mime_type: meta.mime_type,
        resource_type: meta.resource_type,
        from_cache: meta.from_cache,
        from_service_worker: meta.from_service_worker,
        body_state: ResponseBodyState::Unavailable,
        body_error: Some(error),
        body: Arc::from([]),
        byte_spec: BrowserByteSpec::new(
            BrowserByteDomain::CdpDecodedBody,
            limits.per_response(),
            BrowserLimitScope::RetentionAfterProviderMaterialization,
            BrowserBudgetScope::PerPayload,
        ),
        complete_bytes: None,
    }
}

fn capture_report(
    responses: HashMap<String, CapturedResponse>,
    observed: usize,
    retained: usize,
    limits: ResponseCaptureLimits,
    termination: ResponseCaptureTermination,
) -> Result<ResponseCaptureReport> {
    let spec = BrowserByteSpec::new(
        BrowserByteDomain::CdpDecodedBody,
        limits.aggregate(),
        BrowserLimitScope::RetentionAfterProviderMaterialization,
        BrowserBudgetScope::CaptureAggregate,
    );
    // `termination` describes collection completeness independently. This
    // report accounts exactly for response bodies that did become observable.
    let count = |value| {
        ByteCount::try_from_usize(value).map_err(|error| VoidCrawlError::Other(error.to_string()))
    };
    let observed = count(observed)?;
    let retained = count(retained)?;
    let discarded = observed
        .get()
        .checked_sub(retained.get())
        .ok_or_else(|| VoidCrawlError::Other("response byte accounting underflowed".into()))?;
    let has_unavailable_body = responses
        .values()
        .any(|response| response.body_state == ResponseBodyState::Unavailable);
    let aggregate_bytes =
        if termination == ResponseCaptureTermination::Complete && !has_unavailable_body {
            BrowserByteReport::from_known_extent(
                BrowserByteDomain::CdpDecodedBody,
                Some(spec),
                observed,
                retained,
            )
        } else {
            let accounting = BrowserByteAccounting::new(
                observed,
                retained,
                MeasuredBrowserBytes::Known {
                    value: ByteCount::new(discarded),
                },
            )
            .map_err(|error| VoidCrawlError::Other(error.to_string()))?;
            let unknown_loss = MeasuredBrowserBytes::Unavailable {
                reason: BrowserByteMeasurementUnavailableReason::CaptureEndedEarly,
            };
            BrowserByteReport::truncated(
                BrowserByteDomain::CdpDecodedBody,
                Some(spec),
                accounting,
                unknown_loss,
                unknown_loss,
            )
        }
        .map_err(|error| VoidCrawlError::Other(error.to_string()))?;
    Ok(ResponseCaptureReport {
        responses,
        termination,
        aggregate_bytes,
    })
}

/// Upper bound on in-flight request ids whose headers are held. A page can
/// issue far more requests than a capture cares about, and the capture may be
/// armed for minutes, so the accumulator is bounded rather than unbounded.
const MAX_TRACKED_REQUESTS: usize = 2048;

/// Fold one event's headers into the per-request accumulator. `authoritative`
/// entries overwrite; non-authoritative ones only fill absent keys, so the raw
/// wire value always wins over an author-level or response-echoed duplicate.
fn merge_sent_headers(
    store: &mut HashMap<String, HashMap<String, String>>,
    request_id: &str,
    incoming: Vec<(String, String)>,
    authoritative: bool,
) {
    if incoming.is_empty() {
        return;
    }
    // Don't let an unmatched flood of requests grow the map without limit;
    // ids already tracked keep updating.
    if store.len() >= MAX_TRACKED_REQUESTS && !store.contains_key(request_id) {
        return;
    }
    let entry = store.entry(request_id.to_string()).or_default();
    for (name, value) in incoming {
        if authoritative {
            entry.insert(name, value);
        } else {
            entry.entry(name).or_insert(value);
        }
    }
}

/// Remove and return one request's accumulated headers, sorted by name for a
/// deterministic order.
fn take_sent_headers(
    store: &mut HashMap<String, HashMap<String, String>>,
    request_id: &str,
) -> Vec<(String, String)> {
    let mut headers: Vec<(String, String)> = store
        .remove(request_id)
        .map(|m| m.into_iter().collect())
        .unwrap_or_default();
    headers.sort_by(|a, b| a.0.cmp(&b.0));
    headers
}

/// Flatten CDP's optional `requestHeaders`. Chrome omits the field for some
/// requests (notably cache hits and certain service-worker paths), which is
/// reported as an empty vec rather than an error — absence of observed request
/// headers is normal, not a failure.
fn optional_headers(headers: Option<&Headers>) -> Vec<(String, String)> {
    headers
        .map(|h| flatten_headers(h.inner()))
        .unwrap_or_default()
}

fn flatten_headers(value: &serde_json::Value) -> Vec<(String, String)> {
    value
        .as_object()
        .map(|map| {
            map.iter()
                .filter_map(|(key, value)| {
                    value
                        .as_str()
                        .map(|value| (key.to_lowercase(), value.to_string()))
                })
                .collect()
        })
        .unwrap_or_default()
}

#[cfg(test)]
#[path = "response_wait_tests.rs"]
mod wait_tests;

#[cfg(test)]
#[allow(clippy::expect_used)]
mod tests {
    use super::*;

    fn pending() -> PendingResponse {
        PendingResponse {
            names: vec!["response".into()],
            url: "https://example.test/api".into(),
            status: 200,
            headers: vec![],
            request_headers: vec![],
            mime_type: "application/json".into(),
            resource_type: "xhr".into(),
            from_cache: false,
            from_service_worker: false,
        }
    }

    #[test]
    fn per_response_limit_is_explicit() {
        let mut observed = 0;
        let mut retained = 0;
        let response = bounded_response(
            pending(),
            "\x01\x02\x03\x04".into(),
            false,
            &mut observed,
            &mut retained,
            ResponseCaptureLimits::new(
                ByteLimit::try_from(2_u64).expect("positive"),
                ByteLimit::try_from(8_u64).expect("positive"),
            ),
        )
        .expect("limits originate from usize values");
        assert_eq!(response.body(), &[1, 2]);
        assert_eq!(response.body_state, ResponseBodyState::Truncated);
    }

    #[test]
    fn absent_request_headers_are_empty_not_an_error() {
        // Chrome omits `Network.Response.requestHeaders` for some requests
        // (cache hits, certain service-worker paths). That must degrade to an
        // empty vec, never a panic or a spurious failure.
        assert_eq!(optional_headers(None), Vec::<(String, String)>::new());
    }

    #[test]
    fn request_headers_are_lowercased_and_carried_onto_the_capture() {
        // Case-normalization matters: the MCP layer's redaction matches on
        // lowercase names, so a `Authorization` header from the wire must
        // arrive here as `authorization` or redaction silently misses it.
        let headers = Headers::new(serde_json::json!({
            "Authorization": "Bearer secret-token",
            "Accept": "application/json",
        }));
        let flattened = optional_headers(Some(&headers));
        assert!(flattened.contains(&("authorization".into(), "Bearer secret-token".into())));

        let mut meta = pending();
        meta.request_headers = flattened;
        let mut observed = 0;
        let mut retained = 0;
        let captured = bounded_response(
            meta,
            String::new(),
            false,
            &mut observed,
            &mut retained,
            ResponseCaptureLimits::default(),
        )
        .expect("default limits are representable");
        assert!(
            captured
                .request_headers
                .iter()
                .any(|(k, v)| k == "authorization" && v == "Bearer secret-token")
        );
    }

    #[test]
    fn raw_wire_headers_win_over_author_level_ones() {
        // requestWillBeSent may report an author-level value that the network
        // stack then rewrites; the ExtraInfo (wire) value is the truth.
        let mut store = HashMap::new();
        merge_sent_headers(
            &mut store,
            "req-1",
            vec![
                ("accept".into(), "*/*".into()),
                ("cookie".into(), "stale=1".into()),
            ],
            false,
        );
        merge_sent_headers(
            &mut store,
            "req-1",
            vec![("cookie".into(), "real=2".into())],
            true,
        );
        let headers = take_sent_headers(&mut store, "req-1");
        assert_eq!(
            headers,
            vec![
                ("accept".to_string(), "*/*".to_string()),
                ("cookie".into(), "real=2".into())
            ]
        );
    }

    #[test]
    fn a_non_authoritative_source_never_clobbers_a_wire_value() {
        // Response.requestHeaders is merged last but must not overwrite.
        let mut store = HashMap::new();
        merge_sent_headers(
            &mut store,
            "req-1",
            vec![("cookie".into(), "real=2".into())],
            true,
        );
        merge_sent_headers(
            &mut store,
            "req-1",
            vec![("cookie".into(), "echo=3".into())],
            false,
        );
        assert_eq!(take_sent_headers(&mut store, "req-1")[0].1, "real=2");
    }

    #[test]
    fn taking_headers_frees_the_slot() {
        // The accumulator is bounded, so a captured response must release its
        // entry rather than retain it for the capture's lifetime.
        let mut store = HashMap::new();
        merge_sent_headers(
            &mut store,
            "req-1",
            vec![("accept".into(), "*/*".into())],
            true,
        );
        assert_eq!(take_sent_headers(&mut store, "req-1").len(), 1);
        assert_eq!(store.len(), 0);
        // A second take is empty, not a panic.
        assert_eq!(
            take_sent_headers(&mut store, "req-1"),
            Vec::<(String, String)>::new()
        );
    }

    #[test]
    fn tracking_is_bounded_but_keeps_updating_known_ids() {
        let mut store = HashMap::new();
        for i in 0..MAX_TRACKED_REQUESTS {
            merge_sent_headers(
                &mut store,
                &format!("req-{i}"),
                vec![("a".into(), "1".into())],
                true,
            );
        }
        assert_eq!(store.len(), MAX_TRACKED_REQUESTS);
        // A brand-new id past the cap is dropped…
        merge_sent_headers(&mut store, "overflow", vec![("a".into(), "1".into())], true);
        assert_eq!(store.len(), MAX_TRACKED_REQUESTS);
        assert_eq!(
            take_sent_headers(&mut store, "overflow"),
            Vec::<(String, String)>::new()
        );
        // …but an already-tracked id still accepts its wire headers.
        merge_sent_headers(
            &mut store,
            "req-0",
            vec![("cookie".into(), "real=1".into())],
            true,
        );
        assert!(
            take_sent_headers(&mut store, "req-0")
                .iter()
                .any(|(k, _)| k == "cookie")
        );
    }

    #[test]
    fn empty_incoming_headers_do_not_create_an_entry() {
        let mut store = HashMap::new();
        merge_sent_headers(&mut store, "req-1", vec![], true);
        assert_eq!(store.len(), 0);
    }

    #[test]
    fn total_limit_is_shared() {
        let mut observed = 0;
        let mut retained = 3;
        let response = bounded_response(
            pending(),
            "\x01\x02\x03\x04".into(),
            false,
            &mut observed,
            &mut retained,
            ResponseCaptureLimits::new(
                ByteLimit::try_from(8_u64).expect("positive"),
                ByteLimit::try_from(5_u64).expect("positive"),
            ),
        )
        .expect("limits originate from usize values");
        assert_eq!(response.body(), &[1, 2]);
        assert_eq!(retained, 5);
        assert_eq!(observed, 4);
        assert_eq!(
            response
                .byte_report()
                .expect("valid report")
                .spec()
                .expect("configured spec")
                .budget_scope(),
            BrowserBudgetScope::CaptureAggregate
        );
    }

    #[test]
    fn base64_counts_full_decoded_extent_but_keeps_only_prefix() {
        let mut observed = 0;
        let mut retained = 0;
        let response = bounded_response(
            pending(),
            "AAECAwQFBgcICQ==".into(),
            true,
            &mut observed,
            &mut retained,
            ResponseCaptureLimits::new(
                ByteLimit::try_from(3_u64).expect("positive"),
                ByteLimit::try_from(20_u64).expect("positive"),
            ),
        )
        .expect("valid base64");
        assert_eq!(response.body(), &[0, 1, 2]);
        assert_eq!(observed, 10);
        assert_eq!(retained, 3);
    }

    #[test]
    fn unavailable_response_preserves_caller_limit_spec() {
        let limits = ResponseCaptureLimits::new(
            ByteLimit::try_from(17_u64).expect("positive"),
            ByteLimit::try_from(31_u64).expect("positive"),
        );
        let response = unavailable_response(pending(), "not reported".into(), limits);
        let spec = response
            .byte_report()
            .expect("valid report")
            .spec()
            .expect("configured spec");
        assert_eq!(spec.limit(), limits.per_response());
        assert_eq!(spec.budget_scope(), BrowserBudgetScope::PerPayload);
    }

    #[test]
    fn unavailable_body_prevents_complete_aggregate_byte_report() {
        let limits = ResponseCaptureLimits::new(
            ByteLimit::try_from(8_u64).expect("positive"),
            ByteLimit::try_from(8_u64).expect("positive"),
        );
        let response = unavailable_response(pending(), "not reported".into(), limits);
        let report = capture_report(
            HashMap::from([("response".into(), response)]),
            0,
            0,
            limits,
            ResponseCaptureTermination::Complete,
        )
        .expect("report");
        assert!(matches!(
            report.aggregate_bytes.extent(),
            void_crawl_core::BrowserPayloadExtent::Truncated {
                complete_bytes: MeasuredBrowserBytes::Unavailable { .. },
            }
        ));
        assert!(matches!(
            report.aggregate_bytes.additional_loss(),
            MeasuredBrowserBytes::Unavailable { .. }
        ));
    }

    #[test]
    fn partial_terminal_report_preserves_responses_and_aggregate_facts() {
        let limits = ResponseCaptureLimits::new(
            ByteLimit::try_from(8_u64).expect("positive"),
            ByteLimit::try_from(8_u64).expect("positive"),
        );
        let mut observed = 0;
        let mut retained = 0;
        let response = bounded_response(
            pending(),
            "first".into(),
            false,
            &mut observed,
            &mut retained,
            limits,
        )
        .expect("bounded response");
        let report = capture_report(
            HashMap::from([("response".into(), response)]),
            observed,
            retained,
            limits,
            ResponseCaptureTermination::DeadlineReached,
        )
        .expect("report");
        assert_eq!(
            report.termination,
            ResponseCaptureTermination::DeadlineReached
        );
        assert_eq!(report.responses["response"].body(), b"first");
        assert_eq!(report.aggregate_bytes.accounting().observed().get(), 5);
        assert_eq!(report.aggregate_bytes.accounting().retained().get(), 5);
        assert!(matches!(
            report.aggregate_bytes.extent(),
            void_crawl_core::BrowserPayloadExtent::Truncated {
                complete_bytes: MeasuredBrowserBytes::Unavailable { .. },
            }
        ));
        assert!(matches!(
            report.aggregate_bytes.additional_loss(),
            MeasuredBrowserBytes::Unavailable { .. }
        ));
    }
}
