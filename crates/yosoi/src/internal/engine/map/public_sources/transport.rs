//! Existing Requests execution with a reserved source-response extent.
use std::sync::Arc;

use crate::internal::direct_http::ObservedHeaderValue;
use crate::internal::policy::policy::{AddressableByteLimit, DirectHttpRedirects, MaximumElapsed};
use crate::internal::web_capture::CaptureTermination;
use tokio::time::{Instant, sleep_until};
use url::Url;

use super::super::{LimitReached, SourceFailure};
use super::budget::{AdmissionError, Budget};
use crate::internal::engine::{
    AttemptCaptureFacts, CancellationToken, Document, Policy, RequestExecutor, request,
};

pub(super) struct Transport {
    pub policy: Policy,
    pub executor: RequestExecutor,
    pub budget: Arc<Budget>,
    pub token: CancellationToken,
    pub deadline: Instant,
    pub provider: Option<super::super::PublicProvider>,
}

pub(super) enum Failure {
    Source(SourceFailure),
    Limit(LimitReached),
    Stopped,
    ParsingStopped,
}

struct ResponseData {
    status: u16,
    bytes: Vec<u8>,
    location: Option<String>,
}

impl Transport {
    pub async fn fetch(&self, start: &Url) -> Result<Vec<u8>, Failure> {
        let mut current = start.clone();
        let mut hops = 0_u32;
        loop {
            let response = self.once(&current).await?;
            if !matches!(response.status, 301 | 302 | 303 | 307 | 308) {
                if response.status != 200 {
                    return Err(Failure::Source(SourceFailure::HttpStatus(response.status)));
                }
                return Ok(response.bytes);
            }
            let redirects = self.policy.request.direct_http_redirects;
            let maximum = match redirects {
                DirectHttpRedirects::Disabled => {
                    return Err(Failure::Source(SourceFailure::RedirectRejected));
                }
                DirectHttpRedirects::Follow { max_hops, .. } => max_hops.get(),
            };
            if hops >= maximum {
                return Err(Failure::Source(SourceFailure::RedirectLimit));
            }
            let next = response
                .location
                .as_deref()
                .and_then(|value| current.join(value).ok())
                .ok_or(Failure::Source(SourceFailure::RedirectRejected))?;
            if next.origin() != start.origin()
                || !matches!(next.scheme(), "http" | "https")
                || !next.username().is_empty()
                || next.password().is_some()
                || next.as_str().len()
                    > usize::try_from(self.policy.map.limits.max_url_bytes.get())
                        .unwrap_or(usize::MAX)
            {
                return Err(Failure::Source(SourceFailure::RedirectRejected));
            }
            hops = hops.saturating_add(1);
            current = next;
        }
    }

    async fn once(&self, url: &Url) -> Result<ResponseData, Failure> {
        if url.as_str().len()
            > usize::try_from(self.policy.map.limits.max_url_bytes.get()).unwrap_or(usize::MAX)
        {
            return Err(Failure::Source(SourceFailure::RedirectRejected));
        }
        let reservation = self
            .budget
            .reserve_for(url, &self.token, self.deadline, self.provider)
            .await
            .map_err(|error| match error {
                AdmissionError::Limit(limit) => Failure::Limit(limit),
                AdmissionError::Stopped => Failure::Stopped,
                AdmissionError::Source(error) => Failure::Source(error),
            })?;
        let cap = reservation.cap;
        let result = self.execute(url, cap).await;
        let (status, charged) = match &result {
            Ok((response, charged)) => (Some(response.status), *charged),
            Err((_, status, charged)) => (*status, *charged),
        };
        self.budget.complete(reservation, status, charged).await;
        result
            .map(|(response, _)| response)
            .map_err(|(failure, _, _)| failure)
    }

    async fn execute(
        &self,
        url: &Url,
        cap: u64,
    ) -> Result<(ResponseData, u64), (Failure, Option<u16>, u64)> {
        let mut policy = self.policy.clone();
        policy.request.direct_http_redirects = DirectHttpRedirects::Disabled;
        for value in [
            &mut policy.request.source.content_coded_bytes,
            &mut policy.request.source.representation_bytes,
            &mut policy.request.source.unicode_utf8_bytes,
        ] {
            *value = AddressableByteLimit::try_from(cap.min(value.get()))
                .map_err(|_| (Failure::Source(SourceFailure::Transport), None, 0))?;
        }
        let remaining = u64::try_from(
            self.deadline
                .saturating_duration_since(Instant::now())
                .as_micros(),
        )
        .unwrap_or(u64::MAX);
        if remaining == 0 || self.token.is_cancelled() {
            return Err((Failure::Stopped, None, 0));
        }
        policy.request.maximum_elapsed = MaximumElapsed::try_from(
            remaining.min(policy.request.maximum_elapsed.as_microseconds()),
        )
        .map_err(|_| (Failure::Source(SourceFailure::Transport), None, 0))?;
        let request = request::new(url.as_str()).bind(&policy);
        let token = self.token.child_token();
        let send = request.send_with(&self.executor, &token);
        tokio::pin!(send);
        let response = tokio::select! {
            result = &mut send => result,
            () = sleep_until(self.deadline) => { token.cancel(); send.await },
        }
        .map_err(|_| (Failure::Source(SourceFailure::Transport), None, cap))?;
        let attempt = response.attempts().first().ok_or((
            Failure::Source(SourceFailure::Transport),
            None,
            cap,
        ))?;
        let status = attempt.status();
        let charged = attempt
            .capture_facts()
            .and_then(AttemptCaptureFacts::source_bytes)
            .or_else(|| {
                attempt.capture_facts().map(|facts| {
                    facts
                        .observation()
                        .terminal_state()
                        .bytes()
                        .admitted()
                        .get()
                })
            })
            .unwrap_or(0);
        if self.token.is_cancelled() || Instant::now() >= self.deadline {
            return Err((Failure::Stopped, status, charged));
        }
        let deadline = attempt.capture_facts().is_some_and(|facts| {
            matches!(
                facts.observation().termination(),
                CaptureTermination::DeadlineReached { .. }
            )
        }) || attempt
            .failure()
            .and_then(|failure| failure.capture_failure_facts())
            .and_then(|facts| facts.termination())
            .is_some_and(|termination| {
                matches!(termination, CaptureTermination::DeadlineReached { .. })
            });
        if deadline {
            return Err((
                Failure::Source(SourceFailure::RequestDeadline),
                status,
                charged,
            ));
        }
        let status = status.ok_or((Failure::Source(SourceFailure::Transport), None, charged))?;
        let result = attempt.result().ok_or((
            Failure::Source(SourceFailure::Transport),
            Some(status),
            charged,
        ))?;
        let document = result
            .documents()
            .iter()
            .find_map(|outcome| outcome.outcome().document());
        let bytes = document
            .map(Document::bytes)
            .or_else(|| result.raw_response())
            .unwrap_or(&[]);
        let charged = charged.max(u64::try_from(bytes.len()).unwrap_or(cap));
        if attempt.capture_facts().is_some_and(|facts| {
            matches!(
                facts.observation().termination(),
                CaptureTermination::ByteLimitReached { .. }
            )
        }) || result
            .documents()
            .iter()
            .any(|outcome| !outcome.outcome().partial_reasons().is_empty())
        {
            return Err((
                Failure::Source(SourceFailure::IncompleteDocument),
                Some(status),
                charged,
            ));
        }
        let location = result
            .response_facts()
            .and_then(|facts| match facts.location() {
                ObservedHeaderValue::Value(value) => Some(value.as_str().to_owned()),
                _ => None,
            });
        Ok((
            ResponseData {
                status,
                bytes: bytes.to_vec(),
                location,
            },
            charged,
        ))
    }
}
