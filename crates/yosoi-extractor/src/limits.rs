use crate::{ExtractionFailure, ExtractionLimit};

pub fn check_next_len(
    current: usize,
    limit: ExtractionLimit,
    maximum: u64,
) -> Result<(), ExtractionFailure> {
    let current = u64::try_from(current).map_err(|_| ExtractionFailure::CountOverflow { limit })?;
    let observed = current
        .checked_add(1)
        .ok_or(ExtractionFailure::CountOverflow { limit })?;
    check_observed(observed, limit, maximum)
}

pub fn check_len(
    observed: usize,
    limit: ExtractionLimit,
    maximum: u64,
) -> Result<(), ExtractionFailure> {
    let observed =
        u64::try_from(observed).map_err(|_| ExtractionFailure::CountOverflow { limit })?;
    check_observed(observed, limit, maximum)
}

pub fn increment(
    current: &mut u64,
    limit: ExtractionLimit,
    maximum: u64,
) -> Result<(), ExtractionFailure> {
    let observed = current
        .checked_add(1)
        .ok_or(ExtractionFailure::CountOverflow { limit })?;
    check_observed(observed, limit, maximum)?;
    *current = observed;
    Ok(())
}

const fn check_observed(
    observed: u64,
    limit: ExtractionLimit,
    maximum: u64,
) -> Result<(), ExtractionFailure> {
    if observed > maximum {
        Err(ExtractionFailure::LimitExceeded {
            limit,
            maximum,
            observed,
        })
    } else {
        Ok(())
    }
}
