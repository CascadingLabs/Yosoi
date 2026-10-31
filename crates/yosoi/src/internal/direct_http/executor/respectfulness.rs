use std::time::Duration;

use tokio::time::{Instant, timeout_at};
use tokio_util::sync::CancellationToken;
use wreq::{
    Client, Response,
    header::{RETRY_AFTER, USER_AGENT},
};

use crate::internal::{
    direct_http::{
        DirectHttpTransportError, DirectHttpTransportErrorKind, ResolvedDirectHttpCaptureSpec,
    },
    respectfulness::{RespectfulnessError, now_ms, retry_after_at},
};

/// Every send (including same-URL retry) obtains its own reservation. The
/// enclosing request loop applies cancellation and its absolute deadline.
pub(super) async fn send(
    client: &Client,
    spec: &ResolvedDirectHttpCaptureSpec,
    target: &str,
    cancellation: &CancellationToken,
    deadline: Instant,
) -> Result<Response, DirectHttpTransportError> {
    let mut attempts = 0_u8;
    let mut reschedules = 0_u8;
    loop {
        if let Some(operation) = &spec.respectfulness {
            operation
                .finish()
                .await
                .map_err(DirectHttpTransportError::respectfulness)?;
            let admitted = operation
                .acquire(
                    target.to_owned(),
                    deadline.saturating_duration_since(Instant::now()),
                )
                .await;
            if let Err(error) = admitted {
                if attempts > 0
                    && reschedules < 8
                    && let RespectfulnessError::Limited {
                        next_eligible_at_ms: Some(next),
                        ..
                    } = &error
                {
                    let now = now_ms().map_err(DirectHttpTransportError::respectfulness)?;
                    if *next > now {
                        reschedules = reschedules.saturating_add(1);
                        wait(next.saturating_sub(now), cancellation).await?;
                        continue;
                    }
                }
                return Err(DirectHttpTransportError::respectfulness(error));
            }
        }
        if cancellation.is_cancelled() {
            return Err(DirectHttpTransportError::cancelled());
        }
        if Instant::now() >= deadline {
            return Err(DirectHttpTransportError::timeout());
        }
        attempts = attempts.saturating_add(1);
        let request = client.get(target);
        let request = match spec.strategy().user_agent() {
            Some(user_agent) => request.header(USER_AGENT, user_agent.as_str()),
            None => request,
        };
        let result = request
            .send()
            .await
            .map_err(DirectHttpTransportError::from_wreq);
        let Some(operation) = &spec.respectfulness else {
            return result;
        };
        let status = result
            .as_ref()
            .ok()
            .map(|response| response.status().as_u16());
        let retry_after = result
            .as_ref()
            .ok()
            .and_then(|response| response.headers().get(RETRY_AFTER))
            .and_then(|value| value.to_str().ok())
            .map(str::to_owned);
        let transport_error = result.as_ref().err().is_some_and(|error| {
            !matches!(
                error.kind(),
                DirectHttpTransportErrorKind::Cancelled | DirectHttpTransportErrorKind::Timeout
            )
        });
        operation
            .observe(status, retry_after.clone(), transport_error)
            .await
            .map_err(DirectHttpTransportError::respectfulness)?;
        let retry = operation.retry();
        let eligible = status.is_some_and(|status| retry.statuses.contains(&status))
            || (transport_error && retry.transport_errors);
        if !eligible || attempts >= retry.max_attempts {
            return result;
        }
        let now = now_ms().map_err(DirectHttpTransportError::respectfulness)?;
        let delay = retry_after
            .as_deref()
            .and_then(|value| retry_after_at(value, now))
            .map_or(retry.backoff_ms, |until| {
                until.saturating_sub(now).max(retry.backoff_ms)
            });
        drop(result);
        operation
            .finish()
            .await
            .map_err(DirectHttpTransportError::respectfulness)?;
        operation
            .record_retry(status)
            .map_err(DirectHttpTransportError::respectfulness)?;
        wait(delay, cancellation).await?;
    }
}

async fn wait(
    delay_ms: u64,
    cancellation: &CancellationToken,
) -> Result<(), DirectHttpTransportError> {
    let at = Instant::now()
        .checked_add(Duration::from_millis(delay_ms))
        .ok_or_else(|| {
            DirectHttpTransportError::respectfulness(RespectfulnessError::Setup {
                message: "retry time exceeds runtime range".to_owned(),
            })
        })?;
    match timeout_at(at, cancellation.cancelled()).await {
        Ok(()) => Err(DirectHttpTransportError::cancelled()),
        Err(_) => Ok(()),
    }
}
