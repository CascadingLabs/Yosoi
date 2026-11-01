//! Bounded event journal for one explicitly armed native Chrome subscription.

use crate::{
    internal::browser::{
        controller::NetworkObservationSubscription, page::NetworkObservationEvent as ProviderEvent,
    },
    surface::connection::Result,
    surface::{
        NetworkByteProvenance, NetworkCoverage, NetworkEvent, NetworkEventKind, NetworkGap,
        NetworkHeader, NetworkInFlight, NetworkObservationPolicy, NetworkPayloadKind,
        NetworkPayloadRef, NetworkPayloadState, NetworkProviderClock, NetworkWindow, SurfaceError,
    },
};
use serde_json::Value;
use sha2::Digest;
use std::{
    collections::{BTreeMap, BTreeSet, HashMap, HashSet, VecDeque},
    io,
    sync::{Arc, Mutex},
    time::{Duration, SystemTime, UNIX_EPOCH},
};
use tokio::sync::Notify;
use tokio::task::JoinHandle;
use tokio::time::Instant;
use tokio_util::sync::CancellationToken;
use url::Url;

const MAX_HEADER_NAME_BYTES: usize = 128;
const MAX_HEADER_VALUE_BYTES: usize = 2_048;
const MAX_RETAINED_URL_BYTES: usize = 4_096;

#[derive(Clone)]
struct RequestState {
    hop: u32,
    url: String,
    method: String,
    response_seen: bool,
}

#[derive(Clone, Copy)]
struct BodySizeState {
    decoded_bytes: Option<u64>,
    saw_chunk: bool,
}

#[derive(Clone)]
struct ResponseLink {
    request_id: String,
    hop: u32,
    payload_id: String,
    sequence: u64,
    window_id: Option<String>,
    request_start_observed: bool,
    declared_media_type: Option<String>,
    browser_effective_mime: Option<String>,
    browser_effective_charset: Option<String>,
    content_encoding: Option<String>,
    completed: bool,
    body_attempted: bool,
}

#[derive(Clone, Debug)]
pub(super) struct NetworkBodyCandidate {
    pub request_id: String,
    pub hop: u32,
    pub payload_id: String,
    pub response_sequence: u64,
    pub response_window_id: String,
    pub declared_media_type: Option<String>,
    pub browser_effective_mime: Option<String>,
    pub browser_effective_charset: Option<String>,
    pub content_encoding: Option<String>,
    pub provider_reported_body_bytes: Option<u64>,
}

pub(super) struct NetworkSnapshot {
    pub window: NetworkWindow,
    pub body_candidates: Vec<NetworkBodyCandidate>,
}

struct Journal {
    events: VecDeque<NetworkEvent>,
    event_bytes: usize,
    sequence: u64,
    total_retained_events: usize,
    overflow: bool,
    dropped_events: u64,
    filtered_events: u64,
    disconnected: bool,
    expired: bool,
    network_was_previously_enabled: bool,
    late_events: u64,
    last_provider_time_us: Option<u64>,
    start_boundary_unknown: bool,
    request_states: HashMap<String, RequestState>,
    body_sizes: HashMap<String, BodySizeState>,
    data_lengths_reliable: bool,
    ignored_request_ids: HashSet<String>,
    response_links: HashMap<(String, u32), ResponseLink>,
    completed: HashSet<(String, u32)>,
    retained_response_bodies: usize,
    attempted_response_bodies: usize,
    retained_body_bytes: usize,
    gaps: Vec<NetworkGap>,
}

impl Journal {
    fn new(network_was_previously_enabled: bool) -> Self {
        Self {
            events: VecDeque::new(),
            event_bytes: 0,
            sequence: 0,
            total_retained_events: 0,
            overflow: false,
            dropped_events: 0,
            filtered_events: 0,
            disconnected: false,
            expired: false,
            network_was_previously_enabled,
            late_events: 0,
            last_provider_time_us: None,
            start_boundary_unknown: true,
            request_states: HashMap::new(),
            body_sizes: HashMap::new(),
            data_lengths_reliable: true,
            ignored_request_ids: HashSet::new(),
            response_links: HashMap::new(),
            completed: HashSet::new(),
            retained_response_bodies: 0,
            attempted_response_bodies: 0,
            retained_body_bytes: 0,
            gaps: Vec::new(),
        }
    }
}

/// One owned event listener and bounded journal. A provider task never retains
/// raw URL or header values after applying the policy.
pub(super) struct NetworkCapture {
    session_id: String,
    tab_id: String,
    subscription_id: String,
    policy: NetworkObservationPolicy,
    journal: Arc<Mutex<Journal>>,
    stop: CancellationToken,
    signal: Arc<Notify>,
    task: Option<JoinHandle<()>>,
    next_window: u64,
    previous_in_flight: Vec<NetworkInFlight>,
    next_window_start_unix_us: u64,
}

impl NetworkCapture {
    pub(super) fn start(
        subscription: NetworkObservationSubscription,
        session_id: String,
        tab_id: String,
        policy: NetworkObservationPolicy,
        cancellation: CancellationToken,
        authority_cancellation: CancellationToken,
    ) -> Result<Self> {
        policy.validate()?;
        let started_at_unix_us = unix_micros()?;
        let subscription_id = uuid::Uuid::new_v4().to_string();
        let network_was_previously_enabled = subscription.network_was_previously_enabled();
        let journal = Arc::new(Mutex::new(Journal::new(network_was_previously_enabled)));
        let task_journal = Arc::clone(&journal);
        let signal = Arc::new(Notify::new());
        let task_signal = Arc::clone(&signal);
        let task_policy = policy.clone();
        let lifetime_ms = policy.max_duration_ms;
        let stop = CancellationToken::new();
        let task_stop = stop.clone();
        let task = tokio::spawn(async move {
            let mut subscription = subscription;
            let lifetime = tokio::time::sleep(Duration::from_millis(lifetime_ms));
            tokio::pin!(lifetime);
            loop {
                let event = tokio::select! {
                    biased;
                    () = task_stop.cancelled() => {
                        subscription.settle();
                        return;
                    }
                    () = cancellation.cancelled() => {
                        if let Ok(mut state) = task_journal.lock() {
                            state.disconnected = true;
                            state.data_lengths_reliable = false;
                            push_gap(&mut state, "owning_session_cancelled", None);
                        }
                        subscription.settle();
                        task_signal.notify_one();
                        return;
                    }
                    () = authority_cancellation.cancelled() => {
                        if let Ok(mut state) = task_journal.lock() {
                            state.disconnected = true;
                            state.data_lengths_reliable = false;
                            push_gap(&mut state, "native_work_authority_lost", None);
                        }
                        subscription.settle();
                        task_signal.notify_one();
                        return;
                    }
                    () = &mut lifetime => {
                        if let Ok(mut state) = task_journal.lock() {
                            state.expired = true;
                            state.data_lengths_reliable = false;
                            push_gap(&mut state, "subscription_lifetime_limit", None);
                        }
                        subscription.settle();
                        task_signal.notify_one();
                        return;
                    }
                    event = subscription.next() => event,
                };
                match event {
                    Ok(event) => {
                        let provider_gap = matches!(&event, ProviderEvent::ProviderGap { .. });
                        store_provider_event(&task_journal, &task_policy, event);
                        task_signal.notify_one();
                        if provider_gap {
                            subscription.settle();
                            return;
                        }
                    }
                    Err(_error) => {
                        if let Ok(mut state) = task_journal.lock() {
                            state.disconnected = true;
                            state.overflow = true;
                            state.data_lengths_reliable = false;
                            push_gap(&mut state, "provider_event_stream_lost", None);
                        }
                        subscription.settle();
                        task_signal.notify_one();
                        return;
                    }
                }
            }
        });
        Ok(Self {
            session_id,
            tab_id,
            subscription_id,
            policy,
            journal,
            stop,
            signal,
            task: Some(task),
            next_window: 1,
            previous_in_flight: Vec::new(),
            next_window_start_unix_us: started_at_unix_us,
        })
    }

    pub(super) fn subscription_id(&self) -> &str {
        &self.subscription_id
    }

    pub(super) async fn wait_for_event(
        &self,
        after_sequence: u64,
        timeout_ms: u64,
    ) -> Result<Option<u64>> {
        if timeout_ms == 0 || timeout_ms > 30_000 {
            return Err(
                io::Error::other("network event wait must be between 1 and 30000 ms").into(),
            );
        }
        let deadline = Instant::now()
            .checked_add(Duration::from_millis(timeout_ms))
            .ok_or_else(|| io::Error::other("network event wait deadline overflowed"))?;
        loop {
            let notified = self.signal.notified();
            tokio::pin!(notified);
            let (sequence, ended) = {
                let state = self
                    .journal
                    .lock()
                    .map_err(|_| io::Error::other("network journal lock poisoned"))?;
                (state.sequence, state.disconnected || state.expired)
            };
            if sequence > after_sequence {
                return Ok(Some(sequence));
            }
            if ended {
                return Err(io::Error::other(
                    "network event subscription ended before a new event",
                )
                .into());
            }
            if tokio::time::timeout_at(deadline, &mut notified)
                .await
                .is_err()
            {
                return Ok(None);
            }
        }
    }

    pub(super) fn snapshot(&mut self, max_window_bytes: usize) -> Result<NetworkSnapshot> {
        if self.task.as_ref().is_none_or(JoinHandle::is_finished)
            && let Ok(mut state) = self.journal.lock()
            && !state.expired
            && !state.disconnected
        {
            state.disconnected = true;
            push_gap(&mut state, "subscription_task_stopped", None);
        }
        let window_id = format!("{}:{}", self.subscription_id, self.next_window);
        let next_window = self
            .next_window
            .checked_add(1)
            .ok_or_else(|| io::Error::other("network window sequence exhausted"))?;
        let mut state = self
            .journal
            .lock()
            .map_err(|_| io::Error::other("network journal lock poisoned"))?;
        let now = unix_micros()?;
        self.next_window = next_window;
        let first_sequence = state.events.front().map(|event| event.sequence);
        let last_sequence = state.events.back().map(|event| event.sequence);
        let events: Vec<_> = state.events.drain(..).collect();
        let mut payloads = Vec::new();
        for event in &events {
            let key = (event.request_id.clone(), event.hop);
            if matches!(&event.kind, NetworkEventKind::Finished { .. }) {
                state.completed.insert(key.clone());
                if let Some(response) = state.response_links.get_mut(&key) {
                    response.completed = true;
                }
            }
            if matches!(&event.kind, NetworkEventKind::ResponseReceived { .. }) {
                let completed = state.completed.contains(&key);
                if let Some(response) = state.response_links.get_mut(&key)
                    && response.sequence == event.sequence
                {
                    response.window_id = Some(window_id.clone());
                    response.completed |= completed;
                }
            }
        }
        for event in &events {
            if !matches!(&event.kind, NetworkEventKind::ResponseReceived { .. }) {
                continue;
            }
            if let Some(response) = state
                .response_links
                .get(&(event.request_id.clone(), event.hop))
                .filter(|response| response.sequence == event.sequence)
                .cloned()
            {
                let reason = if !self.policy.retain_bodies {
                    "body_retention_disabled"
                } else if !response.completed {
                    "response_not_finished_at_window_boundary"
                } else if response.body_attempted {
                    "response_body_already_attempted"
                } else if state.attempted_response_bodies >= self.policy.max_response_bodies {
                    "response_body_count_limit"
                } else {
                    "response_body_capture_pending"
                };
                payloads.push(not_requested_payload(&response, &window_id, reason));
            }
        }
        let mut body_candidates = if self.policy.retain_bodies {
            let available = self
                .policy
                .max_response_bodies
                .saturating_sub(state.attempted_response_bodies);
            let mut candidates = Vec::new();
            let mut eligible: Vec<_> = state
                .response_links
                .iter()
                .filter(|(_, response)| {
                    response.completed && !response.body_attempted && response.window_id.is_some()
                })
                .map(|(key, response)| (response.sequence, key.clone()))
                .collect();
            eligible.sort_by_key(|(sequence, _)| *sequence);
            for (_, key) in eligible.into_iter().take(available) {
                let Some(response) = state.response_links.get_mut(&key) else {
                    continue;
                };
                if let Some(response_window_id) = response.window_id.clone() {
                    response.body_attempted = true;
                    let provider_reported_body_bytes =
                        if state.data_lengths_reliable && response.request_start_observed {
                            state
                                .body_sizes
                                .get(&response.request_id)
                                .filter(|size| size.saw_chunk)
                                .and_then(|size| size.decoded_bytes)
                        } else {
                            None
                        };
                    candidates.push(NetworkBodyCandidate {
                        request_id: response.request_id.clone(),
                        hop: response.hop,
                        payload_id: response.payload_id.clone(),
                        response_sequence: response.sequence,
                        response_window_id,
                        declared_media_type: response.declared_media_type.clone(),
                        browser_effective_mime: response.browser_effective_mime.clone(),
                        browser_effective_charset: response.browser_effective_charset.clone(),
                        content_encoding: response.content_encoding.clone(),
                        provider_reported_body_bytes,
                    });
                }
            }
            state.attempted_response_bodies = state
                .attempted_response_bodies
                .saturating_add(candidates.len());
            candidates.sort_by_key(|candidate| candidate.response_sequence);
            candidates
        } else {
            Vec::new()
        };
        for candidate in &body_candidates {
            if payloads
                .iter()
                .any(|payload: &NetworkPayloadRef| payload.id == candidate.payload_id)
            {
                continue;
            }
            if let Some(response) = state
                .response_links
                .get(&(candidate.request_id.clone(), candidate.hop))
                .cloned()
            {
                payloads.push(not_requested_payload(
                    &response,
                    &window_id,
                    "response_body_capture_pending",
                ));
            }
        }
        let in_flight = in_flight_values(&state.request_states);
        let starts_not_observed = u64::try_from(
            events
                .iter()
                .filter(|event| !event.request_start_observed)
                .count(),
        )
        .map_err(|_| SurfaceError::Limit("network missing-start count"))?;
        let mut window = NetworkWindow {
            schema: crate::surface::NETWORK_OBSERVATION_SCHEMA.into(),
            schema_version: 1,
            session_id: self.session_id.clone(),
            tab_id: self.tab_id.clone(),
            subscription_id: self.subscription_id.clone(),
            window_id,
            first_sequence,
            last_sequence,
            started_at_unix_us: self.next_window_start_unix_us,
            ended_at_unix_us: now,
            events,
            in_flight_at_start: self.previous_in_flight.clone(),
            in_flight,
            gaps: std::mem::take(&mut state.gaps),
            coverage: NetworkCoverage {
                complete: false,
                reason: "page_target_cdp_window_is_not_browser_wide_or_atomic".into(),
                overflow: state.overflow,
                dropped_events: state.dropped_events,
                disconnected: state.disconnected,
                expired: state.expired,
                instrumentation_escalated: !state.network_was_previously_enabled,
                network_was_previously_enabled: state.network_was_previously_enabled,
                late_events: state.late_events,
                filtered_events: state.filtered_events,
                starts_not_observed,
                omitted_payload_links: 0,
                start_boundary_unknown: state.start_boundary_unknown,
                end_boundary_in_flight: !state.request_states.is_empty(),
            },
            retention: self.policy.retention(),
            payloads,
        };
        state.start_boundary_unknown = false;
        self.previous_in_flight.clone_from(&window.in_flight);
        self.next_window_start_unix_us = now;
        drop(state);
        trim_window(&mut window, max_window_bytes)?;
        body_candidates.retain(|candidate| {
            window
                .payloads
                .iter()
                .any(|payload| payload.id == candidate.payload_id)
                && (candidate.response_window_id != window.window_id
                    || window.events.iter().any(|event| {
                        event.sequence == candidate.response_sequence
                            && event.request_id == candidate.request_id
                            && event.hop == candidate.hop
                            && matches!(&event.kind, NetworkEventKind::ResponseReceived { .. })
                    }))
        });
        window.validate()?;
        Ok(NetworkSnapshot {
            window,
            body_candidates,
        })
    }

    pub(super) fn retain_body(
        &mut self,
        candidate: &NetworkBodyCandidate,
        payload_id: String,
        bytes: &[u8],
        provider_base64_encoded: bool,
        text_utf8_normalized: bool,
        state: NetworkPayloadState,
        document_kind: Option<NetworkPayloadKind>,
        document_id: Option<String>,
        detected_media_type: Option<String>,
        projection_basis: Option<crate::surface::NetworkProjectionBasis>,
        reason: Option<String>,
    ) -> Result<NetworkPayloadRef> {
        let mut journal = self
            .journal
            .lock()
            .map_err(|_| io::Error::other("network journal lock poisoned"))?;
        let mut outcome_state = state;
        let mut outcome_reason = reason;
        let allowed = bytes.len() <= self.policy.max_body_bytes
            && journal.retained_body_bytes.saturating_add(bytes.len())
                <= self.policy.max_total_body_bytes;
        if !allowed
            && matches!(
                state,
                NetworkPayloadState::Retained | NetworkPayloadState::Truncated
            )
        {
            outcome_state = NetworkPayloadState::Unavailable;
            outcome_reason = Some("response_body_retention_limit".into());
        }
        if allowed
            && matches!(
                outcome_state,
                NetworkPayloadState::Retained | NetworkPayloadState::Truncated
            )
        {
            journal.retained_response_bodies = journal.retained_response_bodies.saturating_add(1);
            journal.retained_body_bytes = journal.retained_body_bytes.saturating_add(bytes.len());
        }
        let retained = if matches!(
            outcome_state,
            NetworkPayloadState::Retained | NetworkPayloadState::Truncated
        ) {
            bytes.len()
        } else {
            0
        };
        let has_payload = matches!(
            outcome_state,
            NetworkPayloadState::Retained | NetworkPayloadState::Truncated
        );
        let body_capture_at_unix_us = Some(unix_micros()?);
        Ok(NetworkPayloadRef {
            id: payload_id,
            request_id: candidate.request_id.clone(),
            hop: candidate.hop,
            response_sequence: candidate.response_sequence,
            response_window_id: candidate.response_window_id.clone(),
            body_capture_at_unix_us,
            state: outcome_state,
            document_kind: has_payload.then_some(document_kind).flatten(),
            projection_basis: if has_payload { projection_basis } else { None },
            declared_media_type: candidate.declared_media_type.clone(),
            browser_effective_mime: candidate.browser_effective_mime.clone(),
            browser_effective_charset: candidate.browser_effective_charset.clone(),
            detected_media_type: if has_payload {
                detected_media_type
            } else {
                None
            },
            content_encoding: candidate.content_encoding.clone(),
            byte_provenance: if has_payload {
                NetworkByteProvenance::CdpDecodedResponseBody
            } else {
                NetworkByteProvenance::None
            },
            provider_base64_encoded,
            provider_reported_body_bytes: candidate.provider_reported_body_bytes,
            text_utf8_normalized: has_payload && text_utf8_normalized,
            retained_bytes: u64::try_from(retained)
                .map_err(|_| SurfaceError::Limit("network body size"))?,
            sha256: has_payload.then(|| format!("{:x}", sha2::Sha256::digest(bytes))),
            document_id: if has_payload { document_id } else { None },
            reason: outcome_reason,
        })
    }

    pub(super) async fn close(&mut self) -> Result<()> {
        self.stop.cancel();
        if let Some(mut task) = self.task.take() {
            if tokio::time::timeout(Duration::from_secs(2), &mut task)
                .await
                .is_err()
            {
                task.abort();
                let _ = task.await;
            }
        }
        Ok(())
    }
}

impl Drop for NetworkCapture {
    fn drop(&mut self) {
        self.stop.cancel();
        if let Some(task) = self.task.take() {
            task.abort();
        }
    }
}

fn store_provider_event(
    journal: &Arc<Mutex<Journal>>,
    policy: &NetworkObservationPolicy,
    event: ProviderEvent,
) {
    let Ok(mut state) = journal.lock() else {
        return;
    };
    match event {
        ProviderEvent::ProviderGap {
            reason,
            dropped_events,
        } => {
            state.disconnected = true;
            state.data_lengths_reliable = false;
            if let Some(dropped) = dropped_events {
                state.overflow = true;
                state.dropped_events = state.dropped_events.saturating_add(dropped);
            }
            push_gap(&mut state, reason, dropped_events);
        }
        ProviderEvent::Request(event) => {
            let id = event.request_id.inner().clone();
            let method = event.request.method.clone();
            let Some((origin, url)) = retained_url(&event.request.url, policy) else {
                state.filtered_events = state.filtered_events.saturating_add(1);
                ignore_request(&mut state, &id, policy);
                return;
            };
            if !origin_allowed(&origin, policy) || !method_allowed(&method, policy) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                ignore_request(&mut state, &id, policy);
                return;
            }
            state.ignored_request_ids.remove(&id);
            if !state.body_sizes.contains_key(&id) {
                if state.body_sizes.len() < policy.max_events {
                    state.body_sizes.insert(
                        id.clone(),
                        BodySizeState {
                            decoded_bytes: Some(0),
                            saw_chunk: false,
                        },
                    );
                } else {
                    state.data_lengths_reliable = false;
                    push_gap(&mut state, "decoded_body_size_tracking_limit", None);
                }
            }
            let prior = state.request_states.get(&id).cloned();
            if prior.is_none() && state.request_states.len() >= policy.max_events {
                state.overflow = true;
                state.dropped_events = state.dropped_events.saturating_add(1);
                push_gap(&mut state, "in_flight_request_limit", Some(1));
                return;
            }
            let mut hop = prior.as_ref().map_or(0, |request| request.hop);
            if let Some(redirect) = event.redirect_response.as_ref()
                && let Some(prior) = prior.as_ref()
            {
                let status = u16::try_from(redirect.status).ok();
                if let Some(status) = status {
                    let _ = emit(
                        &mut state,
                        policy,
                        id.clone(),
                        hop,
                        provider_time(event.timestamp.inner()),
                        true,
                        NetworkEventKind::Redirect {
                            from_url: prior.url.clone(),
                            to_url: url.clone(),
                            status,
                            headers: retained_headers(redirect.headers.inner(), policy),
                        },
                        event.frame_id.as_ref().map(|frame| frame.inner().clone()),
                        nonempty(event.loader_id.inner()),
                    );
                }
                hop = match hop.checked_add(1) {
                    Some(next) => next,
                    None => {
                        state.overflow = true;
                        push_gap(&mut state, "redirect_hop_exhausted", None);
                        return;
                    }
                };
            } else if let Some(prior) = prior.as_ref() {
                hop = match prior.hop.checked_add(1) {
                    Some(next) => next,
                    None => {
                        state.overflow = true;
                        push_gap(&mut state, "redirect_hop_exhausted", None);
                        return;
                    }
                };
            }
            let response_seen = prior.is_some_and(|request| request.response_seen);
            let sequence = emit(
                &mut state,
                policy,
                id.clone(),
                hop,
                provider_time(event.timestamp.inner()),
                true,
                NetworkEventKind::RequestStarted {
                    url: url.clone(),
                    method: method.clone(),
                    resource_type: event.r#type.as_ref().map(|value| value.as_ref().to_owned()),
                    headers: retained_headers(event.request.headers.inner(), policy),
                },
                event.frame_id.as_ref().map(|frame| frame.inner().clone()),
                nonempty(event.loader_id.inner()),
            );
            if sequence.is_some() {
                state.request_states.insert(
                    id,
                    RequestState {
                        hop,
                        url: url.clone(),
                        method,
                        response_seen,
                    },
                );
            }
        }
        ProviderEvent::DataReceived(event) => {
            let id = event.request_id.inner().clone();
            if state.ignored_request_ids.contains(&id) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            }
            let length = u64::try_from(event.data_length).ok();
            if !state.body_sizes.contains_key(&id) {
                if state.body_sizes.len() >= policy.max_events {
                    state.data_lengths_reliable = false;
                    push_gap(&mut state, "decoded_body_size_tracking_limit", None);
                    return;
                }
                state.body_sizes.insert(
                    id.clone(),
                    BodySizeState {
                        decoded_bytes: length,
                        saw_chunk: true,
                    },
                );
            } else if let Some(size) = state.body_sizes.get_mut(&id) {
                size.saw_chunk = true;
                size.decoded_bytes = match (size.decoded_bytes, length) {
                    (Some(previous), Some(current)) => previous.checked_add(current),
                    _ => None,
                };
            }
            if length.is_none()
                || state
                    .body_sizes
                    .get(&id)
                    .is_some_and(|size| size.decoded_bytes.is_none())
            {
                state.data_lengths_reliable = false;
                push_gap(&mut state, "decoded_body_size_unavailable", None);
            }
        }
        ProviderEvent::Response(event) => {
            let id = event.request_id.inner().clone();
            if state.ignored_request_ids.contains(&id) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            }
            if !policy.allowed_methods.is_empty() && !state.request_states.contains_key(&id) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            }
            let Some((origin, url)) = retained_url(&event.response.url, policy) else {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            };
            if !origin_allowed(&origin, policy) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            }
            let existing = state.request_states.get(&id).cloned();
            if !state.body_sizes.contains_key(&id) {
                if state.body_sizes.len() < policy.max_events {
                    state.body_sizes.insert(
                        id.clone(),
                        BodySizeState {
                            decoded_bytes: None,
                            saw_chunk: false,
                        },
                    );
                } else {
                    state.data_lengths_reliable = false;
                    push_gap(&mut state, "decoded_body_size_tracking_limit", None);
                }
            }
            if existing.is_none() && state.request_states.len() >= policy.max_events {
                state.overflow = true;
                state.dropped_events = state.dropped_events.saturating_add(1);
                push_gap(&mut state, "in_flight_request_limit", Some(1));
                return;
            }
            let hop = existing.as_ref().map_or(0, |request| request.hop);
            let request_start_observed = existing.is_some();
            let status = u16::try_from(event.response.status).ok();
            let content_encoding = header_value(event.response.headers.inner(), "content-encoding");
            let declared_media_type = header_value(event.response.headers.inner(), "content-type");
            let browser_effective_mime = bounded_header_value(&event.response.mime_type);
            let browser_effective_charset = bounded_header_value(&event.response.charset);
            let response_url = url;
            let payload_id = uuid::Uuid::new_v4().to_string();
            let sequence = emit(
                &mut state,
                policy,
                id.clone(),
                hop,
                provider_time(event.timestamp.inner()),
                request_start_observed,
                NetworkEventKind::ResponseReceived {
                    url: response_url.clone(),
                    status,
                    declared_media_type: declared_media_type.clone(),
                    browser_effective_mime: browser_effective_mime.clone(),
                    browser_effective_charset: browser_effective_charset.clone(),
                    content_encoding: content_encoding.clone(),
                    headers: retained_headers(event.response.headers.inner(), policy),
                },
                event.frame_id.as_ref().map(|frame| frame.inner().clone()),
                nonempty(event.loader_id.inner()),
            );
            if let Some(sequence) = sequence {
                let key = (id.clone(), hop);
                let completed = state.completed.contains(&key);
                state.request_states.insert(
                    id.clone(),
                    RequestState {
                        hop,
                        url: response_url,
                        method: existing.map_or_else(|| "unknown".into(), |request| request.method),
                        response_seen: true,
                    },
                );
                state.response_links.insert(
                    key,
                    ResponseLink {
                        request_id: id,
                        hop,
                        payload_id,
                        sequence,
                        window_id: None,
                        request_start_observed,
                        declared_media_type,
                        browser_effective_mime,
                        browser_effective_charset,
                        content_encoding,
                        completed,
                        body_attempted: false,
                    },
                );
            }
        }
        ProviderEvent::Finished(event) => {
            let id = event.request_id.inner().clone();
            if state.ignored_request_ids.remove(&id) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            }
            let request = state.request_states.remove(&id);
            let hop = request.as_ref().map_or(0, |value| value.hop);
            let request_start_observed = request.is_some();
            let known = request.is_some() || state.response_links.contains_key(&(id.clone(), hop));
            if known {
                state.completed.insert((id.clone(), hop));
            }
            let _ = emit(
                &mut state,
                policy,
                id,
                hop,
                provider_time(event.timestamp.inner()),
                request_start_observed,
                NetworkEventKind::Finished {
                    encoded_data_length: finite_u64(event.encoded_data_length),
                },
                None,
                None,
            );
        }
        ProviderEvent::Failed(event) => {
            let id = event.request_id.inner().clone();
            if state.ignored_request_ids.remove(&id) {
                state.filtered_events = state.filtered_events.saturating_add(1);
                return;
            }
            let request = state.request_states.remove(&id);
            let hop = request.as_ref().map_or(0, |value| value.hop);
            let request_start_observed = request.is_some();
            let _ = emit(
                &mut state,
                policy,
                id,
                hop,
                provider_time(event.timestamp.inner()),
                request_start_observed,
                NetworkEventKind::Failed {
                    error: safe_error(&event.error_text),
                    canceled: event.canceled.as_ref().is_some_and(|canceled| *canceled),
                },
                None,
                None,
            );
        }
    }
}

fn emit(
    state: &mut Journal,
    policy: &NetworkObservationPolicy,
    request_id: String,
    hop: u32,
    provider_time_us: Option<u64>,
    request_start_observed: bool,
    kind: NetworkEventKind,
    frame_id: Option<String>,
    loader_id: Option<String>,
) -> Option<u64> {
    let sequence = match state.sequence.checked_add(1) {
        Some(sequence) => sequence,
        None => {
            state.overflow = true;
            push_gap(state, "event_sequence_exhausted", None);
            return None;
        }
    };
    state.sequence = sequence;
    let observed_at_unix_us = match unix_micros() {
        Ok(value) => value,
        Err(_) => {
            state.overflow = true;
            state.dropped_events = state.dropped_events.saturating_add(1);
            push_gap(state, "local_event_clock_unavailable", Some(1));
            return None;
        }
    };
    if provider_time_us.is_some_and(|time| {
        state
            .last_provider_time_us
            .is_some_and(|prior| time < prior)
    }) {
        state.late_events = state.late_events.saturating_add(1);
    }
    if let Some(time) = provider_time_us {
        state.last_provider_time_us = Some(
            state
                .last_provider_time_us
                .map_or(time, |prior| prior.max(time)),
        );
    }
    let event = NetworkEvent {
        sequence,
        request_id,
        request_start_observed,
        hop,
        observed_at_unix_us,
        provider_time_us,
        provider_clock: provider_time_us.map(|_| NetworkProviderClock::CdpMonotonic),
        frame_id,
        loader_id,
        kind,
    };
    let bytes = match serde_json::to_vec(&event) {
        Ok(bytes) => bytes.len(),
        Err(_) => {
            state.overflow = true;
            state.dropped_events = state.dropped_events.saturating_add(1);
            push_gap(state, "event_serialization_failed", Some(1));
            return None;
        }
    };
    let Some(next_event_bytes) = state.event_bytes.checked_add(bytes) else {
        state.overflow = true;
        state.dropped_events = state.dropped_events.saturating_add(1);
        push_gap(state, "event_byte_count_overflow", Some(1));
        return None;
    };
    let Some(next_event_count) = state.total_retained_events.checked_add(1) else {
        state.overflow = true;
        state.dropped_events = state.dropped_events.saturating_add(1);
        push_gap(state, "event_count_overflow", Some(1));
        return None;
    };
    if next_event_count > policy.max_events || next_event_bytes > policy.max_event_bytes {
        state.overflow = true;
        state.dropped_events = state.dropped_events.saturating_add(1);
        push_gap(state, "event_retention_limit", Some(1));
        return None;
    }
    state.event_bytes = next_event_bytes;
    state.total_retained_events = next_event_count;
    state.events.push_back(event);
    Some(sequence)
}

fn push_gap(state: &mut Journal, reason: &str, dropped_events: Option<u64>) {
    if state.gaps.len() >= 128 {
        return;
    }
    state.gaps.push(NetworkGap {
        after_sequence: state.sequence,
        reason: reason.chars().take(160).collect(),
        dropped_events,
    });
}

fn ignore_request(state: &mut Journal, request_id: &str, policy: &NetworkObservationPolicy) {
    if state.ignored_request_ids.len() < policy.max_events {
        state.ignored_request_ids.insert(request_id.to_owned());
    } else {
        state.overflow = true;
        state.dropped_events = state.dropped_events.saturating_add(1);
        push_gap(state, "filtered_request_tracking_limit", Some(1));
    }
}

fn retained_url(raw_url: &str, policy: &NetworkObservationPolicy) -> Option<(String, String)> {
    let mut url = Url::parse(raw_url).ok()?;
    if !matches!(url.scheme(), "http" | "https") {
        return None;
    }
    let username = url.set_username("");
    let password = url.set_password(None);
    if username.is_err() || password.is_err() {
        return None;
    }
    url.set_fragment(None);
    if !policy.retain_url_path {
        url.set_path("/");
    }
    if !policy.retain_url_query {
        url.set_query(None);
    }
    let origin = url.origin().ascii_serialization();
    let retained = url.to_string();
    if retained.len() > MAX_RETAINED_URL_BYTES {
        return Some((
            origin,
            format!("{}://{}/:redacted", url.scheme(), url.host_str()?),
        ));
    }
    Some((origin, retained))
}

fn origin_allowed(origin: &str, policy: &NetworkObservationPolicy) -> bool {
    policy.allowed_origins.is_empty()
        || policy
            .allowed_origins
            .iter()
            .any(|allowed| allowed == origin)
}

fn method_allowed(method: &str, policy: &NetworkObservationPolicy) -> bool {
    policy.allowed_methods.is_empty()
        || policy
            .allowed_methods
            .iter()
            .any(|allowed| allowed == method)
}

fn retained_headers(headers: &Value, policy: &NetworkObservationPolicy) -> Vec<NetworkHeader> {
    let allowed: BTreeSet<_> = policy
        .header_allowlist
        .iter()
        .map(|name| name.to_ascii_lowercase())
        .filter(|name| !is_sensitive_header(name))
        .collect();
    let Some(headers) = headers.as_object() else {
        return Vec::new();
    };
    let mut retained = BTreeMap::new();
    for (name, value) in headers {
        let name = name.to_ascii_lowercase();
        if !allowed.contains(&name) || name.len() > MAX_HEADER_NAME_BYTES {
            continue;
        }
        let Some(value) = value.as_str() else {
            continue;
        };
        if value.len() > MAX_HEADER_VALUE_BYTES {
            continue;
        }
        retained.insert(name, value.to_owned());
    }
    retained
        .into_iter()
        .map(|(name, value)| NetworkHeader { name, value })
        .collect()
}

fn header_value(headers: &Value, name: &str) -> Option<String> {
    headers
        .as_object()?
        .iter()
        .find(|(key, _)| key.eq_ignore_ascii_case(name))
        .and_then(|(_, value)| value.as_str())
        .filter(|value| value.len() <= MAX_HEADER_VALUE_BYTES)
        .map(str::to_owned)
}

fn in_flight_values(states: &HashMap<String, RequestState>) -> Vec<NetworkInFlight> {
    let mut values: Vec<_> = states
        .iter()
        .map(|(request_id, state)| NetworkInFlight {
            request_id: request_id.clone(),
            hop: state.hop,
            url: state.url.clone(),
            method: state.method.clone(),
            response_seen: state.response_seen,
        })
        .collect();
    values.sort_by(|left, right| left.request_id.cmp(&right.request_id));
    values
}

fn not_requested_payload(
    response: &ResponseLink,
    window_id: &str,
    reason: &str,
) -> NetworkPayloadRef {
    NetworkPayloadRef {
        id: response.payload_id.clone(),
        request_id: response.request_id.clone(),
        hop: response.hop,
        response_sequence: response.sequence,
        response_window_id: response
            .window_id
            .as_deref()
            .map_or_else(|| window_id.to_owned(), str::to_owned),
        body_capture_at_unix_us: None,
        state: NetworkPayloadState::NotRequested,
        document_kind: None,
        projection_basis: None,
        declared_media_type: response.declared_media_type.clone(),
        browser_effective_mime: response.browser_effective_mime.clone(),
        browser_effective_charset: response.browser_effective_charset.clone(),
        detected_media_type: None,
        content_encoding: response.content_encoding.clone(),
        byte_provenance: NetworkByteProvenance::None,
        provider_base64_encoded: false,
        provider_reported_body_bytes: None,
        text_utf8_normalized: false,
        retained_bytes: 0,
        sha256: None,
        document_id: None,
        reason: Some(reason.into()),
    }
}

fn trim_window(window: &mut NetworkWindow, maximum: usize) -> Result<()> {
    if maximum == 0 {
        return Err(SurfaceError::Invalid("network document budget is zero".into()).into());
    }
    loop {
        let bytes = serde_json::to_vec(window)?.len();
        if bytes <= maximum {
            return Ok(());
        }
        if let Some(event) = window.events.pop() {
            if matches!(&event.kind, NetworkEventKind::ResponseReceived { .. }) {
                window.payloads.retain(|payload| {
                    payload.response_window_id != window.window_id
                        || payload.response_sequence != event.sequence
                });
            }
            window.coverage.overflow = true;
            window.coverage.dropped_events = window.coverage.dropped_events.saturating_add(1);
            if let Some(gap) = window
                .gaps
                .iter_mut()
                .find(|gap| gap.reason == "network_document_byte_limit")
            {
                gap.dropped_events = Some(
                    gap.dropped_events
                        .map_or(0, |count| count)
                        .saturating_add(1),
                );
            } else {
                window.gaps.push(NetworkGap {
                    after_sequence: window.last_sequence.map_or(0, |sequence| sequence),
                    reason: "network_document_byte_limit".into(),
                    dropped_events: Some(1),
                });
            }
            window.first_sequence = window.events.first().map(|event| event.sequence);
            window.last_sequence = window.events.last().map(|event| event.sequence);
            continue;
        }
        if window.payloads.pop().is_some() {
            window.coverage.overflow = true;
            window.coverage.omitted_payload_links =
                window.coverage.omitted_payload_links.saturating_add(1);
            continue;
        }
        if window.in_flight_at_start.pop().is_some() || window.in_flight.pop().is_some() {
            window.coverage.complete = false;
            continue;
        }
        return Err(SurfaceError::Limit("network document bytes").into());
    }
}

fn provider_time(seconds: &f64) -> Option<u64> {
    if !seconds.is_finite() || *seconds < 0.0 {
        return None;
    }
    let micros = (*seconds * 1_000_000.0).round();
    if micros > u64::MAX as f64 {
        None
    } else {
        Some(micros as u64)
    }
}

fn finite_u64(value: f64) -> Option<u64> {
    if !value.is_finite() || value < 0.0 || value > u64::MAX as f64 {
        None
    } else {
        Some(value.round() as u64)
    }
}

fn unix_micros() -> Result<u64> {
    let elapsed = SystemTime::now()
        .duration_since(UNIX_EPOCH)
        .map_err(|_| io::Error::other("system clock precedes Unix epoch"))?;
    u64::try_from(elapsed.as_micros()).map_err(Into::into)
}

fn nonempty(value: &str) -> Option<String> {
    (!value.is_empty()).then(|| value.to_owned())
}

fn bounded_header_value(value: &str) -> Option<String> {
    (!value.is_empty() && value.len() <= MAX_HEADER_VALUE_BYTES).then(|| value.to_owned())
}

fn safe_error(value: &str) -> String {
    let value = value.trim();
    if value.starts_with("net::ERR_") && value.len() <= 128 && value.is_ascii() {
        value.to_owned()
    } else {
        "provider_request_failed".into()
    }
}

fn is_sensitive_header(name: &str) -> bool {
    matches!(
        name,
        "authorization"
            | "proxy-authorization"
            | "cookie"
            | "set-cookie"
            | "cookie2"
            | "x-api-key"
            | "x-auth-token"
    )
}
