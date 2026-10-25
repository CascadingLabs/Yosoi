//! Native BiDi events normalized into the shared resource/source report.

use super::{
    BASE64, BrowserBodyLayer, BrowserResourceId, BrowserResourceOutcome, MainDocumentSource,
    MeasuredCount, NavigationCapture, NavigationCaptureOptions, NavigationCaptureReport,
    NavigationCaptureTermination, NavigationEvent, NavigationEventKind, NavigationStop,
    NetworkExtraInfoState, ProtectedHeaders, ProtectedUrl, RedirectHop, ResourceFrameId,
    ResourceRecord, ResponseBodyState, Result, SourceBodyUnavailableReason, VoidCrawlError,
    duration_micros, unavailable_main_document, unix_millis,
};
use crate::browser::BrowserEngine;
use crate::internal::browser::bidi::{
    events::ScopedCapture,
    session::{Page, SessionError},
    transport::{BidiError, BidiEvent},
};
use crate::internal::browser::controller::map_bidi;
use serde_json::Value;
use std::{
    collections::HashMap,
    result::Result as StdResult,
    sync::Arc,
    time::{Duration, Instant, SystemTime},
};
use tokio::{sync::oneshot, time};
use tokio_util::sync::CancellationToken;

impl NavigationCapture {
    #[allow(
        clippy::significant_drop_tightening,
        reason = "The collector is moved into the worker and must remain owned until capture settles."
    )]
    pub(in crate::internal::browser) async fn arm_bidi(
        page: Page,
        options: NavigationCaptureOptions,
    ) -> Result<Self> {
        let options = options.validate()?;
        let deadline = time::Instant::now()
            .checked_add(options.max_duration)
            .ok_or(VoidCrawlError::InvalidInput {
                operation: "navigation_capture",
                reason: "deadline overflow",
            })?;
        let token = CancellationToken::new();
        let network = page.arm_network(&token, deadline).await.map_err(map_bidi)?;
        let (stop, stop_rx) = oneshot::channel();
        let worker = tokio::spawn(run(page, network, options, stop_rx, deadline));
        Ok(Self {
            stop: Some(stop),
            worker: Some(worker),
        })
    }
}

struct State {
    resources: Vec<ResourceRecord>,
    requests: HashMap<String, usize>,
    frames: HashMap<String, ResourceFrameId>,
    redirects: Vec<RedirectHop>,
    events: Vec<NavigationEvent>,
    main: Option<usize>,
    source: Option<MainDocumentSource>,
    requested_url: Option<ProtectedUrl>,
    dropped: u64,
}

impl State {
    fn new() -> Self {
        Self {
            resources: Vec::new(),
            requests: HashMap::new(),
            frames: HashMap::new(),
            redirects: Vec::new(),
            events: Vec::new(),
            main: None,
            source: None,
            requested_url: None,
            dropped: 0,
        }
    }

    fn event(
        &mut self,
        event: &BidiEvent,
        root: &str,
        options: NavigationCaptureOptions,
        offset: u64,
    ) -> Option<(String, ResourceRecord)> {
        let params = &event.params;
        let request = params.get("request")?;
        let id = request.get("request")?.as_str()?;
        let kind = match event.method.as_str() {
            "network.beforeRequestSent" => NavigationEventKind::Request,
            "network.responseStarted" => NavigationEventKind::Response,
            "network.responseCompleted" => NavigationEventKind::Finished,
            "network.fetchError" => NavigationEventKind::Failed,
            _ => return None,
        };
        if kind == NavigationEventKind::Request {
            let previous = self.requests.remove(id);
            let previous_id = previous
                .and_then(|index| self.resources.get_mut(index))
                .map(|resource| {
                    resource.outcome = BrowserResourceOutcome::Redirected;
                    resource.id
                });
            if self.resources.len() < options.max_resources {
                let resource_id =
                    BrowserResourceId(u64::try_from(self.resources.len()).unwrap_or(u64::MAX));
                let context = params.get("context").and_then(Value::as_str);
                let frame = context.map(|context| {
                    let next =
                        ResourceFrameId(u64::try_from(self.frames.len()).unwrap_or(u64::MAX));
                    *self.frames.entry(context.to_owned()).or_insert(next)
                });
                let navigation = params.get("navigation").and_then(Value::as_str).is_some();
                let index = self.resources.len();
                self.resources.push(ResourceRecord {
                    id: resource_id,
                    redirect_from: previous_id,
                    frame,
                    loader: None,
                    url: ProtectedUrl(
                        request
                            .get("url")
                            .and_then(Value::as_str)
                            .unwrap_or_default()
                            .to_owned(),
                    ),
                    resource_type: if request.get("initiatorType").and_then(Value::as_str)
                        == Some("fetch")
                    {
                        "fetch"
                    } else if request.get("initiatorType").and_then(Value::as_str)
                        == Some("xmlhttprequest")
                    {
                        "xhr"
                    } else if navigation {
                        "document"
                    } else {
                        request
                            .get("destination")
                            .and_then(Value::as_str)
                            .filter(|value| !value.is_empty())
                            .unwrap_or("other")
                    }
                    .to_owned(),
                    status: None,
                    mime_type: None,
                    headers: ProtectedHeaders(Vec::new()),
                    from_cache: None,
                    from_service_worker: None,
                    encoded_data_length: None,
                    outcome: BrowserResourceOutcome::Pending,
                });
                self.requests.insert(id.to_owned(), index);
                if let Some(from) = previous_id {
                    self.redirects.push(RedirectHop {
                        from,
                        to: resource_id,
                        status: previous
                            .and_then(|index| self.resources.get(index))
                            .and_then(|resource| resource.status),
                    });
                }
                if context == Some(root) && navigation {
                    if self.requested_url.is_none() {
                        self.requested_url = self
                            .resources
                            .get(index)
                            .map(|resource| resource.url.clone());
                    }
                    self.main = Some(index);
                    self.source = None;
                }
            } else {
                self.dropped = self.dropped.saturating_add(1);
                if self.main == previous
                    || (params.get("context").and_then(Value::as_str) == Some(root)
                        && params.get("navigation").and_then(Value::as_str).is_some())
                {
                    self.main = None;
                    self.source = None;
                }
            }
        }
        let index = self.requests.get(id).copied();
        let resource = index.and_then(|index| self.resources.get_mut(index));
        let mut body = None;
        let resource_id = if let Some(resource) = resource {
            if let Some(response) = params.get("response") {
                resource.status = response
                    .get("status")
                    .and_then(Value::as_u64)
                    .and_then(|status| u16::try_from(status).ok());
                resource.mime_type = response
                    .get("mimeType")
                    .and_then(Value::as_str)
                    .filter(|value| !value.is_empty())
                    .map(str::to_owned);
                resource.headers = headers(response);
                resource.from_cache = response.get("fromCache").and_then(Value::as_bool);
                resource.encoded_data_length =
                    response.get("bytesReceived").and_then(Value::as_u64);
            }
            match kind {
                NavigationEventKind::Request => {}
                NavigationEventKind::Response => {
                    resource.outcome = BrowserResourceOutcome::ResponseReceived;
                }
                NavigationEventKind::Finished => {
                    resource.outcome = BrowserResourceOutcome::Complete;
                    if self.main == index
                        && !resource
                            .status
                            .is_some_and(|status| (300..400).contains(&status))
                    {
                        body = Some((id.to_owned(), resource.clone()));
                    }
                }
                NavigationEventKind::Failed => {
                    // BiDi reports text, not CDP's cancelled/blocked flags.
                    resource.outcome = BrowserResourceOutcome::Failed {
                        cancelled: false,
                        blocked: false,
                    };
                    if self.main == index {
                        self.source = Some(unavailable_main_document(
                            resource,
                            SourceBodyUnavailableReason::RequestFailed,
                            options.max_source_bytes,
                            offset,
                        ));
                    }
                }
            }
            Some(resource.id)
        } else {
            None
        };
        self.events.push(NavigationEvent {
            sequence: u64::try_from(self.events.len()).unwrap_or(u64::MAX),
            offset_micros: offset,
            kind,
            resource_id,
        });
        body
    }
}

async fn run(
    page: Page,
    mut network: ScopedCapture,
    options: NavigationCaptureOptions,
    mut stop: oneshot::Receiver<NavigationStop>,
    deadline: time::Instant,
) -> NavigationCaptureReport {
    let started = Instant::now();
    let started_at_unix_ms = unix_millis(SystemTime::now());
    let token = CancellationToken::new();
    let mut state = State::new();
    let mut finishing = false;
    let termination = 'capture: loop {
        let event = tokio::select! {
            biased;
            result = network.next(&token, deadline) => match result {
                Ok(event) => event,
                Err(SessionError::Transport(BidiError::Deadline)) => break NavigationCaptureTermination::DeadlineReached,
                Err(_) => break NavigationCaptureTermination::ProviderDisconnected,
            },
            stop = &mut stop => break stopped(&stop),
        };
        if let Some((request, resource)) = state.event(
            &event,
            &page.context,
            options,
            duration_micros(started.elapsed()),
        ) {
            let body = network.response_body(&request, options.max_source_bytes, &token, deadline);
            tokio::pin!(body);
            let result = tokio::select! {
                biased;
                stop = &mut stop => {
                    if matches!(stop, Ok(NavigationStop::Finished)) {
                        finishing = true;
                        body.await
                    } else { break 'capture stopped(&stop); }
                },
                result = &mut body => result,
            };
            let mut source = unavailable_main_document(
                &resource,
                SourceBodyUnavailableReason::BidiBodyUnavailable,
                options.max_source_bytes,
                duration_micros(started.elapsed()),
            );
            if let Ok(body) = result {
                source.body_layer = Some(BrowserBodyLayer::DecodedRepresentation);
                source.body_state = if body.bytes.len() == body.complete_bytes {
                    ResponseBodyState::Available
                } else {
                    ResponseBodyState::Truncated
                };
                source.body_unavailable = None;
                source.retained_bytes = body.bytes.len();
                source.complete_bytes = Some(body.complete_bytes);
                source.body = Arc::from(body.bytes);
            }
            state.source = Some(source);
        }
        if state.events.len() >= options.max_events {
            break NavigationCaptureTermination::EventLimitReached;
        }
        if finishing {
            break NavigationCaptureTermination::Finished;
        }
    };
    let cleanup_complete = match time::Instant::now().checked_add(Duration::from_secs(5)) {
        Some(deadline) => network.close(&token, deadline).await.is_ok(),
        None => false,
    };
    let main = state.main.and_then(|index| state.resources.get(index));
    let final_url = main.map(|resource| resource.url.clone());
    if state.source.is_none()
        && let Some(resource) = main
    {
        state.source = Some(unavailable_main_document(
            resource,
            SourceBodyUnavailableReason::CaptureEndedBeforeBody,
            options.max_source_bytes,
            duration_micros(started.elapsed()),
        ));
    }
    let count = u64::try_from(state.events.len()).unwrap_or(u64::MAX);
    NavigationCaptureReport {
        started_at_unix_ms,
        elapsed_micros: duration_micros(started.elapsed()),
        termination,
        requested_url: state.requested_url,
        final_url,
        redirects: state.redirects,
        main_document: state.source,
        resources: state.resources,
        events: state.events,
        events_admitted: count,
        events_retained: count,
        events_dropped: MeasuredCount::Known { value: 0 },
        resources_dropped: state.dropped,
        additional_loss_unknown: page.session.config.engine == BrowserEngine::Moli
            || !cleanup_complete
            || !matches!(
                termination,
                NavigationCaptureTermination::Finished | NavigationCaptureTermination::Cancelled
            ),
        network_extra_info: NetworkExtraInfoState::UnavailableInCurrentClient,
        cleanup_complete,
    }
}

const fn stopped(
    stop: &StdResult<NavigationStop, oneshot::error::RecvError>,
) -> NavigationCaptureTermination {
    match stop {
        Ok(NavigationStop::Finished) => NavigationCaptureTermination::Finished,
        Ok(NavigationStop::Cancelled) | Err(_) => NavigationCaptureTermination::Cancelled,
    }
}

fn headers(response: &Value) -> ProtectedHeaders {
    ProtectedHeaders(
        response
            .get("headers")
            .and_then(Value::as_array)
            .into_iter()
            .flatten()
            .filter_map(|header| {
                let name = header.get("name")?.as_str()?.to_ascii_lowercase();
                let value = header.get("value")?;
                let text = value.get("value")?.as_str()?;
                let text = match value.get("type")?.as_str()? {
                    "string" => text.to_owned(),
                    "base64" => {
                        String::from_utf8(base64::Engine::decode(&BASE64, text).ok()?).ok()?
                    }
                    _ => return None,
                };
                Some((name, text))
            })
            .collect(),
    )
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn dropping_a_new_main_resource_cannot_retain_the_previous_document() {
        let options = NavigationCaptureOptions {
            max_resources: 1,
            ..NavigationCaptureOptions::default()
        };
        let mut state = State::new();
        let request = |id: &str| BidiEvent {
            sequence: 1,
            method: "network.beforeRequestSent".to_owned(),
            params: json!({"context":"root","navigation":id,"request":{"request":id,"url":format!("https://example.test/{id}")}}),
        };
        state.event(&request("old"), "root", options, 0);
        assert_eq!(state.main, Some(0));
        if let Some(resource) = state.resources.first() {
            state.source = Some(unavailable_main_document(
                resource,
                SourceBodyUnavailableReason::CaptureEndedBeforeBody,
                options.max_source_bytes,
                0,
            ));
        }
        state.event(&request("new"), "root", options, 1);
        assert_eq!(state.dropped, 1);
        assert!(state.main.is_none());
        assert!(state.source.is_none());
    }
}
