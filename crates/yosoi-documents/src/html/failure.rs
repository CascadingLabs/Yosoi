use crate::{LocateFailure, LocateOutcome, ResourceLimit};

pub const fn limit_failure(limit: ResourceLimit, maximum: u64, observed: u64) -> LocateFailure {
    LocateFailure::LimitExhausted {
        limit,
        maximum,
        observed,
    }
}

pub fn invalid_failure(code: &str) -> LocateFailure {
    LocateFailure::InvalidPlan {
        code: code.to_owned(),
    }
}

pub fn invalid_plan(code: &str) -> LocateOutcome {
    LocateOutcome::Failed {
        failure: invalid_failure(code),
    }
}
