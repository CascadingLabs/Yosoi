use std::{io, pin::Pin, sync::atomic::Ordering};

use super::termination::{current_offset, maximum_offset, stop};
use super::{
    BodyTerminal, ContentEncodingError, HttpContentCoding, ResponseBodyError, ResponseBodyFailure,
    ResponseBodyOutcome,
    counted::CountedStream,
    parse_content_encoding,
    sink::{BoundedMemorySink, PayloadSink, SinkError},
};
use crate::{
    ByteCount, CaptureOffset, EventAdmission, LifecycleEvent, MeasuredCount,
    PendingDirectHttpResponse, RetentionCheckpoint,
};
use async_compression::tokio::bufread::{BrotliDecoder, GzipDecoder, ZlibDecoder};
use futures_util::TryStreamExt;
use tokio::io::{AsyncRead, AsyncReadExt, BufReader};
use tokio::time::{Instant, sleep_until};
use tokio_util::{io::StreamReader, sync::CancellationToken};
pub(super) const READ_BUFFER_BYTES: usize = 8 * 1024;
pub async fn consume_response_body(
    pending: PendingDirectHttpResponse,
    cancellation: &CancellationToken,
) -> Result<
    (
        ResponseBodyOutcome,
        crate::BoundedAcquisitionLifecycle,
        crate::DirectHttpResponseFacts,
        crate::CaptureResolution,
        crate::DirectHttpExecutionIdentity,
    ),
    Box<ResponseBodyFailure>,
> {
    let limit = pending.spec().content_limits().representation_bytes().get();
    consume_with_sink(
        pending,
        cancellation,
        Box::new(BoundedMemorySink::new(limit)),
    )
    .await
}

pub(crate) async fn consume_with_sink(
    pending: PendingDirectHttpResponse,
    cancellation: &CancellationToken,
    sink: Box<dyn PayloadSink>,
) -> Result<
    (
        ResponseBodyOutcome,
        crate::BoundedAcquisitionLifecycle,
        crate::DirectHttpResponseFacts,
        crate::CaptureResolution,
        crate::DirectHttpExecutionIdentity,
    ),
    Box<ResponseBodyFailure>,
> {
    consume_with_sink_inner(pending, cancellation, sink, false).await
}

#[cfg(test)]
pub(crate) async fn consume_with_sink_forced_invariant_failure(
    pending: PendingDirectHttpResponse,
    cancellation: &CancellationToken,
    sink: Box<dyn PayloadSink>,
) -> Result<
    (
        ResponseBodyOutcome,
        crate::BoundedAcquisitionLifecycle,
        crate::DirectHttpResponseFacts,
        crate::CaptureResolution,
        crate::DirectHttpExecutionIdentity,
    ),
    Box<ResponseBodyFailure>,
> {
    consume_with_sink_inner(pending, cancellation, sink, true).await
}

async fn consume_with_sink_inner(
    pending: PendingDirectHttpResponse,
    cancellation: &CancellationToken,
    sink: Box<dyn PayloadSink>,
    force_invariant_failure: bool,
) -> Result<
    (
        ResponseBodyOutcome,
        crate::BoundedAcquisitionLifecycle,
        crate::DirectHttpResponseFacts,
        crate::CaptureResolution,
        crate::DirectHttpExecutionIdentity,
    ),
    Box<ResponseBodyFailure>,
> {
    let codings = match parse_content_encoding(pending.facts().content_encoding()) {
        Ok(value) => value,
        Err(error) => {
            let terminal = match error {
                ContentEncodingError::Malformed => BodyTerminal::MalformedHeader,
                ContentEncodingError::Unsupported => BodyTerminal::UnsupportedCoding,
            };
            let (_, spec, facts, resolution, mut lifecycle, identity, boundary) =
                pending.into_parts();
            let offset = match current_offset(boundary) {
                Ok(offset) => offset,
                Err(primary) => {
                    return Err(Box::new(ResponseBodyFailure {
                        primary,
                        spec,
                        facts,
                        resolution,
                        lifecycle,
                        identity,
                        content_coded_bytes: 0,
                    }));
                }
            };
            if let Err(primary) = stop(&mut lifecycle, terminal, offset) {
                return Err(Box::new(ResponseBodyFailure {
                    primary,
                    spec,
                    facts,
                    resolution,
                    lifecycle,
                    identity,
                    content_coded_bytes: 0,
                }));
            }
            let outcome = match unavailable(0, terminal) {
                Ok(outcome) => outcome,
                Err(primary) => {
                    return Err(Box::new(ResponseBodyFailure {
                        primary,
                        spec,
                        facts,
                        resolution,
                        lifecycle,
                        identity,
                        content_coded_bytes: 0,
                    }));
                }
            };
            return Ok((outcome, lifecycle, facts, resolution, identity));
        }
    };
    let (response, spec, facts, resolution, mut lifecycle, identity, boundary) =
        pending.into_parts();
    let encoded_limit = spec.content_limits().content_coded_bytes().get();
    let output_limit = spec.content_limits().representation_bytes().get();
    let retention_checkpoint = lifecycle.retention_checkpoint();
    let counted = CountedStream::new(response.bytes_stream(), encoded_limit);
    let count = counted.count.clone();
    let exceeded = counted.exceeded.clone();
    let transport_failed = counted.transport_failed.clone();
    let stream = counted.map_err(io::Error::other);
    let mut reader: Pin<Box<dyn AsyncRead + Send>> =
        Box::pin(BufReader::new(StreamReader::new(stream)));
    for coding in codings.iter().rev() {
        reader = match coding {
            HttpContentCoding::Identity => reader,
            HttpContentCoding::Gzip => Box::pin(GzipDecoder::new(BufReader::new(reader))),
            HttpContentCoding::Brotli => Box::pin(BrotliDecoder::new(BufReader::new(reader))),
            HttpContentCoding::Deflate => Box::pin(ZlibDecoder::new(BufReader::new(reader))),
        };
    }
    let read_result = read_representation(
        reader,
        sink,
        output_limit,
        cancellation,
        &mut lifecycle,
        Instant::from_std(boundary.deadline()),
        boundary,
    )
    .await;
    let ReadResult {
        sink,
        mut terminal,
        offset,
    } = match read_result {
        Ok(value) => value,
        Err(primary) => {
            return Err(Box::new(ResponseBodyFailure {
                primary,
                spec,
                facts,
                resolution,
                lifecycle,
                identity,
                content_coded_bytes: count.load(Ordering::Relaxed),
            }));
        }
    };
    if terminal == BodyTerminal::MalformedCoding && transport_failed.load(Ordering::Relaxed) {
        terminal = BodyTerminal::Disconnect;
    }
    if exceeded.load(Ordering::Relaxed)
        && matches!(
            terminal,
            BodyTerminal::Complete
                | BodyTerminal::RepresentationLimit
                | BodyTerminal::MalformedCoding
        )
    {
        terminal = BodyTerminal::ContentCodedLimit;
    }
    let encoded = count.load(Ordering::Relaxed);
    let outcome = match sink {
        None => {
            discard_staged_retention(&mut lifecycle, retention_checkpoint);
            unavailable(encoded, terminal)
        }
        Some(sink) => {
            if let Ok(bytes) = sink.commit() {
                publish(bytes, lifecycle.admitted_bytes(), encoded, terminal)
            } else {
                if lifecycle.termination().is_none() {
                    terminal = BodyTerminal::SinkFailure;
                }
                discard_staged_retention(&mut lifecycle, retention_checkpoint);
                unavailable(encoded, terminal)
            }
        }
    };
    let outcome = match outcome {
        Ok(outcome) => outcome,
        Err(primary) => {
            return Err(Box::new(ResponseBodyFailure {
                primary,
                spec,
                facts,
                resolution,
                lifecycle,
                identity,
                content_coded_bytes: encoded,
            }));
        }
    };
    let stop_offset = if force_invariant_failure {
        CaptureOffset::from_microseconds(0)
    } else {
        offset
    };
    if let Err(primary) = stop(&mut lifecycle, terminal, stop_offset) {
        return Err(Box::new(ResponseBodyFailure {
            primary,
            spec,
            facts,
            resolution,
            lifecycle,
            identity,
            content_coded_bytes: encoded,
        }));
    }
    Ok((outcome, lifecycle, facts, resolution, identity))
}

const fn discard_staged_retention(
    lifecycle: &mut crate::BoundedAcquisitionLifecycle,
    checkpoint: RetentionCheckpoint,
) {
    lifecycle.restore_retention(checkpoint);
}

struct ReadResult {
    sink: Option<Box<dyn PayloadSink>>,
    terminal: BodyTerminal,
    offset: CaptureOffset,
}

async fn read_representation(
    mut reader: Pin<Box<dyn AsyncRead + Send>>,
    mut sink: Box<dyn PayloadSink>,
    limit: u64,
    cancellation: &CancellationToken,
    lifecycle: &mut crate::BoundedAcquisitionLifecycle,
    deadline_at: Instant,
    boundary: crate::AttemptBoundary,
) -> Result<ReadResult, ResponseBodyError> {
    let mut retained = 0_u64;
    let mut buffer = [0_u8; READ_BUFFER_BYTES];
    loop {
        let deadline = sleep_until(deadline_at);
        tokio::pin!(deadline);
        let read_capacity = if retained == limit { 1 } else { buffer.len() };
        let read_buffer = buffer.get_mut(..read_capacity).unwrap_or_default();
        let read = tokio::select! { biased;
            () = &mut deadline => {
                let offset = maximum_offset(boundary);
                lifecycle.observe_through(offset).map_err(|error| ResponseBodyError::Lifecycle(error.into()))?;
                return Ok(ReadResult { sink: Some(sink), terminal: BodyTerminal::Deadline, offset });
            }
            () = cancellation.cancelled() => return Ok(ReadResult { sink: Some(sink), terminal: BodyTerminal::Cancelled, offset: current_offset(boundary)? }),
            result = reader.read(read_buffer) => result,
        };
        let offset = current_offset(boundary)?;
        let amount = match read {
            Ok(0) => {
                return Ok(ReadResult {
                    sink: Some(sink),
                    terminal: BodyTerminal::Complete,
                    offset,
                });
            }
            Ok(amount) => amount,
            Err(_) => {
                return Ok(ReadResult {
                    sink: Some(sink),
                    terminal: BodyTerminal::MalformedCoding,
                    offset,
                });
            }
        };
        let amount_u64 = u64::try_from(amount).unwrap_or(u64::MAX);
        let representation_available = limit.saturating_sub(retained);
        let wanted = representation_available.min(amount_u64);
        let event = LifecycleEvent::new(
            offset,
            ByteCount::new(amount_u64),
            ByteCount::new(wanted),
            wanted != 0,
        )
        .map_err(ResponseBodyError::LifecycleEvent)?;
        let admission = lifecycle
            .admit(event)
            .map_err(|error| ResponseBodyError::Lifecycle(error.into()))?;
        let admitted = match &admission {
            EventAdmission::Admitted(facts) => facts.retained_bytes().get(),
            EventAdmission::AdmittedAndStopped { admitted, .. } => admitted.retained_bytes().get(),
            EventAdmission::NotAdmittedAndStopped(_) => 0,
        };
        let accepted = usize::try_from(admitted).unwrap_or(usize::MAX).min(amount);
        let prefix = buffer.get(..accepted).ok_or(SinkError::Operation);
        if prefix.and_then(|bytes| sink.write(bytes)).is_err() {
            let terminal = if matches!(admission, EventAdmission::Admitted(_)) {
                BodyTerminal::SinkFailure
            } else {
                BodyTerminal::LifecycleLimit
            };
            return Ok(ReadResult {
                sink: None,
                terminal,
                offset,
            });
        }
        retained = retained.saturating_add(admitted);
        if !matches!(admission, EventAdmission::Admitted(_)) {
            return Ok(ReadResult {
                sink: Some(sink),
                terminal: BodyTerminal::LifecycleLimit,
                offset,
            });
        }
        if wanted < amount_u64 {
            return Ok(ReadResult {
                sink: Some(sink),
                terminal: BodyTerminal::RepresentationLimit,
                offset,
            });
        }
    }
}

pub(crate) fn publish(
    bytes: Vec<u8>,
    observed: u64,
    encoded: u64,
    terminal: BodyTerminal,
) -> Result<ResponseBodyOutcome, ResponseBodyError> {
    if bytes.is_empty() && terminal != BodyTerminal::Complete {
        return unavailable(encoded, terminal);
    }
    let payload = if terminal == BodyTerminal::Complete {
        crate::AcquiredPayloadOutcome::complete(bytes)
    } else {
        let reason = payload_reason(terminal)?;
        crate::AcquiredPayloadOutcome::truncated(
            bytes,
            ByteCount::new(observed),
            MeasuredCount::Unavailable {
                reason: reason.clone(),
            },
            reason,
        )
    }
    .map_err(ResponseBodyError::Payload)?;
    Ok(ResponseBodyOutcome::new(payload, encoded, terminal))
}

fn unavailable(
    encoded: u64,
    terminal: BodyTerminal,
) -> Result<ResponseBodyOutcome, ResponseBodyError> {
    let payload = crate::AcquiredPayloadOutcome::unavailable(payload_reason(terminal)?)
        .map_err(ResponseBodyError::Payload)?;
    Ok(ResponseBodyOutcome::new(payload, encoded, terminal))
}

fn payload_reason(terminal: BodyTerminal) -> Result<yosoi_types::ReasonCode, ResponseBodyError> {
    yosoi_types::ReasonCode::new(super::terminal_reason(terminal))
        .map_err(ResponseBodyError::Reason)
}
