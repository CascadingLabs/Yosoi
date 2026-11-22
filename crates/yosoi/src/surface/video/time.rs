//! Checked conversions from decoder decimal timestamps.
use super::VideoError;
use std::time::Duration;

pub(super) fn seconds_us(value: &str) -> Result<i64, VideoError> {
    let seconds = value
        .parse::<f64>()
        .map_err(|_| VideoError::Invalid("invalid media timestamp".into()))?;
    if !seconds.is_finite() {
        return Err(VideoError::Invalid("nonfinite media timestamp".into()));
    }
    let duration = Duration::try_from_secs_f64(seconds.abs())
        .map_err(|_| VideoError::Invalid("media timestamp out of range".into()))?;
    let microseconds = i64::try_from(duration.as_micros())
        .map_err(|_| VideoError::Invalid("media timestamp out of range".into()))?;
    if seconds < 0.0 {
        microseconds
            .checked_neg()
            .ok_or_else(|| VideoError::Invalid("media timestamp out of range".into()))
    } else {
        Ok(microseconds)
    }
}
