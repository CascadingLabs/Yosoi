use crate::{LocateFailure, ResourceLimit};

pub(super) const fn enforce_limit(
    kind: ResourceLimit,
    maximum: u64,
    observed: u64,
) -> Result<(), LocateFailure> {
    if observed > maximum {
        Err(limit_failure(kind, maximum, observed))
    } else {
        Ok(())
    }
}

pub(super) const fn limit_failure(
    limit: ResourceLimit,
    maximum: u64,
    observed: u64,
) -> LocateFailure {
    LocateFailure::LimitExhausted {
        limit,
        maximum,
        observed,
    }
}

pub(super) fn parse_failed(code: &str) -> LocateFailure {
    LocateFailure::ParseFailed {
        code: code.to_owned(),
    }
}

pub(super) fn invalid_plan(code: &str) -> LocateFailure {
    LocateFailure::InvalidPlan {
        code: code.to_owned(),
    }
}
