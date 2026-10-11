//! Reserved single-hop acquisition shared by serial support and concurrent page work.
use crate::internal::engine as yosoi_engine;

use super::{Fetch, LimitReached, MapTermination, RequestTrace, Response, Runner, SourceFailure};
use crate::internal::direct_http::ObservedHeaderValue;
use crate::internal::engine::{
    AttemptCaptureFacts, AttemptOutcome, CancellationToken, Policy, RequestExecutor,
    RequestSendError, request,
};
use crate::internal::map::admission::normalize;
use crate::internal::policy::policy::{AddressableByteLimit, DirectHttpRedirects, MaximumElapsed};
use crate::internal::web_capture::CaptureTermination;
use std::{future::Future, pin::Pin};
use tokio::time::{Instant, sleep_until};
use url::Url;

#[derive(Clone, Debug)]
pub(super) struct PreparedRequest {
    pub url: Url,
    pub policy: Policy,
    pub cap: u64,
    pub ordinal: usize,
    pub remaining: u64,
    pub map_deadline_limits_request: bool,
}

impl Runner<'_> {
    pub(super) async fn once(&mut self, url: &Url) -> Result<Fetch, SourceFailure> {
        let (work, result) = if let Some(ready) = self.ready_responses.remove(url) {
            ready
        } else {
            let work = self.prepare_request(url)?;
            let result = execute(
                &work,
                &self.executor,
                &self.cancellation.child_token(),
                self.deadline,
            )
            .await;
            self.account_request(&work, &result);
            (work, result)
        };
        self.finish_request(&work, result)
    }

    pub(super) fn prepare_request(&mut self, url: &Url) -> Result<PreparedRequest, SourceFailure> {
        normalize(
            url.as_str(),
            None,
            self.policy().map.limits.max_url_bytes.get(),
        )
        .map_err(|_| SourceFailure::RedirectRejected)?;
        if !self.active() {
            return Err(SourceFailure::Transport);
        }
        if self.summary.requests >= self.policy().map.limits.max_requests.get() {
            self.stop(LimitReached::Requests);
            return Err(SourceFailure::Transport);
        }
        let remaining = u64::from(self.policy().map.limits.max_total_response_bytes.get())
            .saturating_sub(self.summary.response_bytes)
            .saturating_sub(self.reserved_response_bytes);
        if remaining == 0 {
            self.stop(LimitReached::TotalResponseBytes);
            return Err(SourceFailure::IncompleteDocument);
        }
        let mut policy = self.policy().clone();
        policy.request.direct_http_redirects = DirectHttpRedirects::Disabled;
        let cap = remaining.min(u64::from(policy.map.limits.max_response_bytes.get()));
        policy.request.source.content_coded_bytes = AddressableByteLimit::try_from(
            cap.min(policy.request.source.content_coded_bytes.get()),
        )
        .map_err(|_| SourceFailure::Transport)?;
        policy.request.source.representation_bytes = AddressableByteLimit::try_from(
            cap.min(policy.request.source.representation_bytes.get()),
        )
        .map_err(|_| SourceFailure::Transport)?;
        policy.request.source.unicode_utf8_bytes =
            AddressableByteLimit::try_from(cap.min(policy.request.source.unicode_utf8_bytes.get()))
                .map_err(|_| SourceFailure::Transport)?;
        let micros = u64::try_from(
            self.deadline
                .saturating_duration_since(Instant::now())
                .as_micros(),
        )
        .unwrap_or(u64::MAX);
        if micros == 0 {
            self.termination = Some(MapTermination::Deadline);
            return Err(SourceFailure::Transport);
        }
        let map_deadline_limits_request =
            micros <= policy.request.maximum_elapsed.as_microseconds();
        policy.request.maximum_elapsed =
            MaximumElapsed::try_from(micros.min(policy.request.maximum_elapsed.as_microseconds()))
                .map_err(|_| SourceFailure::Transport)?;
        if !self.charge(url.as_str().len().saturating_add(96)) {
            return Err(SourceFailure::Transport);
        }
        let ordinal = self.request_trace.len();
        self.request_trace.push(RequestTrace {
            target: url.clone(),
            status: None,
            charged_response_bytes: 0,
        });
        self.summary.requests = self.summary.requests.saturating_add(1);
        self.reserved_response_bytes = self.reserved_response_bytes.saturating_add(cap);
        Ok(PreparedRequest {
            url: url.clone(),
            policy,
            cap,
            ordinal,
            remaining,
            map_deadline_limits_request,
        })
    }

    pub(super) fn account_request(
        &mut self,
        work: &PreparedRequest,
        result: &Result<Response, SourceFailure>,
    ) {
        self.reserved_response_bytes = self.reserved_response_bytes.saturating_sub(work.cap);
        let attempt = result
            .as_ref()
            .ok()
            .and_then(|response| response.attempts().first());
        let source_bytes = attempt
            .and_then(|attempt| attempt.capture_facts())
            .and_then(AttemptCaptureFacts::source_bytes)
            .or_else(|| {
                attempt
                    .and_then(|attempt| attempt.capture_facts())
                    .map(|facts| {
                        facts
                            .observation()
                            .terminal_state()
                            .bytes()
                            .admitted()
                            .get()
                    })
            })
            .unwrap_or_else(|| {
                if self.cancellation.is_cancelled() || Instant::now() >= self.deadline {
                    0
                } else {
                    work.cap
                }
            });
        let document_bytes = attempt
            .and_then(|attempt| attempt.result())
            .and_then(|result| result.documents().first())
            .map_or(0, |outcome| match outcome.outcome() {
                yosoi_engine::DocumentOutcome::Produced { document, .. } => document.byte_len(),
                _ => 0,
            });
        let bytes = source_bytes.max(document_bytes).min(work.cap);
        self.summary.response_bytes = self.summary.response_bytes.saturating_add(bytes);
        if attempt.and_then(AttemptOutcome::status).is_some()
            && let Some(host) = work
                .url
                .host_str()
                .and_then(|host| self.hosts.get_mut(host))
        {
            host.verification = super::HostVerification::HttpObserved;
        }
        if let Some(trace) = self.request_trace.get_mut(work.ordinal) {
            trace.status = attempt.and_then(AttemptOutcome::status);
            trace.charged_response_bytes = bytes;
        }
    }

    fn finish_request(
        &mut self,
        work: &PreparedRequest,
        result: Result<Response, SourceFailure>,
    ) -> Result<Fetch, SourceFailure> {
        let url = &work.url;
        let remaining = work.remaining;
        let map_deadline_limits_request = work.map_deadline_limits_request;
        if self.cancellation.is_cancelled() {
            self.termination.get_or_insert(MapTermination::Cancelled);
        } else if Instant::now() >= self.deadline {
            self.termination.get_or_insert(MapTermination::Deadline);
        }
        let response = result?;
        let attempt = response
            .attempts()
            .first()
            .ok_or(SourceFailure::Transport)?;
        if attempt
            .failure()
            .and_then(|failure| failure.capture_failure_facts())
            .and_then(|facts| facts.termination())
            .is_some_and(|termination| {
                matches!(termination, CaptureTermination::DeadlineReached { .. })
            })
        {
            if map_deadline_limits_request {
                self.termination.get_or_insert(MapTermination::Deadline);
            }
            return Err(SourceFailure::IncompleteDocument);
        }
        let status = attempt.status().ok_or(SourceFailure::Transport)?;
        let document = attempt
            .result()
            .and_then(|result| result.documents().first())
            .and_then(|outcome| match outcome.outcome() {
                yosoi_engine::DocumentOutcome::Produced { document, .. } => Some(document.clone()),
                _ => None,
            });
        let location = attempt
            .result()
            .and_then(|result| result.response_facts())
            .and_then(|facts| match facts.location() {
                ObservedHeaderValue::Value(value) => Some(value.as_str().to_owned()),
                _ => None,
            });
        if attempt.capture_facts().is_some_and(|facts| {
            matches!(
                facts.observation().termination(),
                CaptureTermination::DeadlineReached { .. }
            )
        }) {
            if map_deadline_limits_request {
                self.termination.get_or_insert(MapTermination::Deadline);
            }
            return Err(SourceFailure::IncompleteDocument);
        }
        if self.termination.is_some() {
            return Err(SourceFailure::Transport);
        }
        let raw_response = attempt
            .result()
            .and_then(|result| result.raw_response())
            .map(<[u8]>::to_vec);
        if attempt.capture_facts().is_some_and(|facts| {
            matches!(
                facts.observation().termination(),
                CaptureTermination::ByteLimitReached { .. }
            )
        }) || attempt.result().is_some_and(|result| {
            result
                .documents()
                .iter()
                .any(|doc| !doc.outcome().partial_reasons().is_empty())
        }) {
            self.stop(
                if remaining <= u64::from(self.policy().map.limits.max_response_bytes.get()) {
                    LimitReached::TotalResponseBytes
                } else {
                    LimitReached::ResponseBytes
                },
            );
        }
        Ok(Fetch {
            url: url.clone(),
            status,
            document,
            raw_response,
            location,
            response,
            aliases: Vec::new(),
        })
    }
}

pub(super) async fn execute(
    work: &PreparedRequest,
    executor: &RequestExecutor,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<Response, SourceFailure> {
    let request = request::new(work.url.as_str()).bind(&work.policy);
    // Keep the HTTP client's deeply nested future behind this acquisition boundary.
    // Public SDK callers should not need a larger trait-evaluation recursion limit.
    let mut future: Pin<Box<dyn Future<Output = Result<Response, RequestSendError>> + Send + '_>> =
        Box::pin(request.send_with(executor, cancellation));
    tokio::select! {
        result = &mut future => result.map_err(|_| SourceFailure::Transport),
        () = sleep_until(deadline) => {
            cancellation.cancel();
            future.await.map_err(|_| SourceFailure::Transport)
        }
    }
}
