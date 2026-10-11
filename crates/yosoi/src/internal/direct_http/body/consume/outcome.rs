use crate::internal::direct_http as yosoi_web_capture_direct_http;
use crate::internal::types as yosoi_types;

use crate::internal::direct_http::body::{BodyTerminal, ResponseBodyError, ResponseBodyOutcome};
use crate::internal::direct_http::{ByteCount, MeasuredCount};

pub(in crate::internal::direct_http) fn publish(
    bytes: Vec<u8>,
    observed: u64,
    encoded: u64,
    terminal: BodyTerminal,
) -> Result<ResponseBodyOutcome, ResponseBodyError> {
    if bytes.is_empty() && terminal != BodyTerminal::Complete {
        return unavailable(encoded, terminal);
    }
    let payload = if terminal == BodyTerminal::Complete {
        yosoi_web_capture_direct_http::AcquiredPayloadOutcome::complete(bytes)
    } else {
        let reason = payload_reason(terminal)?;
        yosoi_web_capture_direct_http::AcquiredPayloadOutcome::truncated(
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

pub(super) fn unavailable(
    encoded: u64,
    terminal: BodyTerminal,
) -> Result<ResponseBodyOutcome, ResponseBodyError> {
    let payload = yosoi_web_capture_direct_http::AcquiredPayloadOutcome::unavailable(
        payload_reason(terminal)?,
    )
    .map_err(ResponseBodyError::Payload)?;
    Ok(ResponseBodyOutcome::new(payload, encoded, terminal))
}

fn payload_reason(terminal: BodyTerminal) -> Result<yosoi_types::ReasonCode, ResponseBodyError> {
    yosoi_types::ReasonCode::new(yosoi_web_capture_direct_http::body::terminal_reason(
        terminal,
    ))
    .map_err(ResponseBodyError::Reason)
}
