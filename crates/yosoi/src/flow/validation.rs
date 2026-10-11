//! Bounded recipe validation before acquisition or dispatch.

use super::{Condition, FailureCapturePolicy, Flow, FlowLimits, FlowValidationError, Step};
use crate::expect::{Expectation, MAX_EXPECTATIONS, MAX_RESPONSE_JSON_MATCHES};
use crate::timing;
use std::time::Duration;

const MAX_EXPECTATION_TEXT_BYTES: usize = 4_096;
const MAX_EXPECTATION_URL_BYTES: usize = 8_192;
const MAX_EXPECTATION_ROLE_BYTES: usize = 128;
const MAX_EXPECTATION_METHOD_BYTES: usize = 32;
const MAX_JSON_POINTER_BYTES: usize = 4_096;
const MAX_EXPECTATION_DEPTH: u32 = 8;
const MAX_EXPECTED_JSON_BYTES: usize = 16_384;

pub(super) fn validate_flow(
    flow: &Flow,
    limits: FlowLimits,
    depth: u32,
    step_count: &mut u128,
) -> Result<(), FlowValidationError> {
    if depth > limits.max_depth {
        return Err(FlowValidationError::TooDeep {
            actual: depth,
            maximum: limits.max_depth,
        });
    }
    if depth > 0 && flow.capture_on_failure != FailureCapturePolicy::Disabled {
        return Err(FlowValidationError::NestedFailureCaptureUnsupported);
    }
    if let Some(timeout) = flow.timeout {
        validate_timeout(timeout)?;
    }

    for (index, step) in flow.steps.iter().enumerate() {
        let increment = 1_u128.checked_add(u128::from(step.wrapper_count())).ok_or(
            FlowValidationError::TooManySteps {
                actual: u128::MAX,
                maximum: limits.max_steps,
            },
        )?;
        *step_count =
            step_count
                .checked_add(increment)
                .ok_or(FlowValidationError::TooManySteps {
                    actual: u128::MAX,
                    maximum: limits.max_steps,
                })?;
        if *step_count > u128::from(limits.max_steps) {
            return Err(FlowValidationError::TooManySteps {
                actual: *step_count,
                maximum: limits.max_steps,
            });
        }

        let step_index = u64::try_from(index).map_err(|_| FlowValidationError::TooManySteps {
            actual: u128::MAX,
            maximum: limits.max_steps,
        })?;
        if let Some(timeout) = step.timeout_duration() {
            validate_timeout(timeout)?;
        }
        if step.has_nested_timeout() {
            return Err(FlowValidationError::NestedTimeout);
        }
        if let Step::NestedFlow { flow } = step.operation() {
            let child_depth = depth.checked_add(1).ok_or(FlowValidationError::TooDeep {
                actual: u32::MAX,
                maximum: limits.max_depth,
            })?;
            validate_flow(flow, limits, child_depth, step_count)?;
            continue;
        }

        if let Step::Until {
            trigger,
            expectation,
        } = step.operation()
        {
            let mut expectation_count = 0_u128;
            validate_expectation(expectation, step_index, limits, 1, &mut expectation_count)?;
            if let Some(trigger) = trigger.as_deref() {
                *step_count =
                    step_count
                        .checked_add(1)
                        .ok_or(FlowValidationError::TooManySteps {
                            actual: u128::MAX,
                            maximum: limits.max_steps,
                        })?;
                if *step_count > u128::from(limits.max_steps) {
                    return Err(FlowValidationError::TooManySteps {
                        actual: *step_count,
                        maximum: limits.max_steps,
                    });
                }
                validate_until_trigger(trigger, step_index, limits)?;
            }
            continue;
        }

        let operation = step.operation();
        if let Step::AssertAll { assertion } = operation {
            assertion
                .validate(limits.max_source_bytes)
                .map_err(FlowValidationError::Assertion)?;
        }
        match operation {
            Step::Click { selector }
            | Step::EnterText { selector, .. }
            | Step::Assert {
                condition:
                    Condition::Exists { selector }
                    | Condition::Visible { selector }
                    | Condition::CountAtLeast { selector, .. },
            }
            | Step::WaitUntil {
                condition:
                    Condition::Exists { selector }
                    | Condition::Visible { selector }
                    | Condition::CountAtLeast { selector, .. },
                ..
            } => validate_selector(selector, step_index, limits.max_selector_bytes)?,
            _ => {}
        }

        if let Step::WaitUntil { timeout_ms, .. } = operation
            && *timeout_ms == 0
        {
            return Err(FlowValidationError::ZeroTimeout { step_index });
        }

        if let Step::Evaluate { source } = operation {
            validate_nonempty_and_bounded(
                source,
                limits.max_source_bytes,
                FlowValidationError::EmptySource { step_index },
                |actual, maximum| FlowValidationError::SourceTooLong {
                    step_index,
                    actual,
                    maximum,
                },
            )?;
        }
        match operation {
            Step::EvaluateFile { snapshot } => snapshot
                .validate(limits.max_source_bytes)
                .map_err(|error| FlowValidationError::JavaScript(error.to_string()))?,
            Step::EvaluateModule { bundle } => bundle
                .validate(limits.max_source_bytes)
                .map_err(|error| FlowValidationError::JavaScript(error.to_string()))?,
            _ => {}
        }
    }
    Ok(())
}

pub(super) fn validate_until_trigger(
    trigger: &Step,
    step_index: u64,
    limits: FlowLimits,
) -> Result<(), FlowValidationError> {
    let operation = trigger.operation();
    if trigger.timeout_duration().is_some()
        || trigger.has_local_continuation_settings()
        || trigger.requires_cancellation_binding()
    {
        return Err(FlowValidationError::InvalidUntilTrigger {
            step_index,
            kind: "configured wrapper".into(),
        });
    }
    match operation {
        Step::Click { selector } => {
            validate_selector(selector, step_index, limits.max_selector_bytes)?;
        }
        Step::EnterText { selector, text } => {
            validate_selector(selector, step_index, limits.max_selector_bytes)?;
            validate_text(text, "trigger text", step_index, MAX_EXPECTATION_TEXT_BYTES)?;
        }
        Step::Evaluate { source } => {
            validate_nonempty_and_bounded(
                source,
                limits.max_source_bytes,
                FlowValidationError::EmptySource { step_index },
                |actual, maximum| FlowValidationError::SourceTooLong {
                    step_index,
                    actual,
                    maximum,
                },
            )?;
        }
        Step::EvaluateFile { snapshot } => snapshot
            .validate(limits.max_source_bytes)
            .map_err(|error| FlowValidationError::JavaScript(error.to_string()))?,
        Step::EvaluateModule { bundle } => bundle
            .validate(limits.max_source_bytes)
            .map_err(|error| FlowValidationError::JavaScript(error.to_string()))?,
        _ => {
            return Err(FlowValidationError::InvalidUntilTrigger {
                step_index,
                kind: operation.kind().into(),
            });
        }
    }
    Ok(())
}

pub(super) fn validate_expectation(
    expectation: &Expectation,
    step_index: u64,
    limits: FlowLimits,
    depth: u32,
    count: &mut u128,
) -> Result<(), FlowValidationError> {
    if depth > MAX_EXPECTATION_DEPTH {
        return Err(FlowValidationError::ExpectationTooDeep {
            actual: depth,
            maximum: MAX_EXPECTATION_DEPTH,
        });
    }
    *count = count
        .checked_add(1)
        .ok_or(FlowValidationError::TooManyExpectations {
            actual: u128::MAX,
            maximum: MAX_EXPECTATIONS,
        })?;
    let maximum_count =
        u128::try_from(MAX_EXPECTATIONS).map_err(|_| FlowValidationError::TooManyExpectations {
            actual: u128::MAX,
            maximum: MAX_EXPECTATIONS,
        })?;
    if *count > maximum_count {
        return Err(FlowValidationError::TooManyExpectations {
            actual: *count,
            maximum: MAX_EXPECTATIONS,
        });
    }

    match expectation {
        Expectation::Condition { condition } => match condition {
            Condition::Exists { selector }
            | Condition::Visible { selector }
            | Condition::CountAtLeast { selector, .. } => {
                validate_selector(selector, step_index, limits.max_selector_bytes)?;
            }
        },
        Expectation::Contract { assertion } => assertion
            .validate(limits.max_source_bytes)
            .map_err(FlowValidationError::Assertion)?,
        Expectation::Accessibility { name, role } => {
            validate_text(
                name,
                "accessible name",
                step_index,
                MAX_EXPECTATION_TEXT_BYTES,
            )?;
            if let Some(role) = role {
                validate_text(
                    role,
                    "accessibility role",
                    step_index,
                    MAX_EXPECTATION_ROLE_BYTES,
                )?;
            }
        }
        Expectation::Response {
            url,
            method,
            status,
            json,
        } => {
            validate_text(url, "response URL", step_index, MAX_EXPECTATION_URL_BYTES)?;
            if let Some(method) = method {
                validate_text(
                    method,
                    "response method",
                    step_index,
                    MAX_EXPECTATION_METHOD_BYTES,
                )?;
            }
            if status.is_some_and(|status| !(100..=599).contains(&status)) {
                return Err(FlowValidationError::InvalidExpectation {
                    step_index,
                    reason: "response status must be between 100 and 599".into(),
                });
            }
            if json.len() > MAX_RESPONSE_JSON_MATCHES {
                return Err(FlowValidationError::InvalidExpectation {
                    step_index,
                    reason: format!(
                        "response has {} JSON matches; maximum is {MAX_RESPONSE_JSON_MATCHES}",
                        json.len()
                    ),
                });
            }
            for item in json {
                validate_json_pointer(&item.pointer, step_index)?;
                let encoded = serde_json::to_vec(&item.value).map_err(|error| {
                    FlowValidationError::InvalidExpectation {
                        step_index,
                        reason: format!("response JSON value could not be encoded: {error}"),
                    }
                })?;
                if encoded.len() > MAX_EXPECTED_JSON_BYTES {
                    return Err(FlowValidationError::ExpectationValueTooLong {
                        step_index,
                        field: "JSON value",
                        actual: encoded.len(),
                        maximum: MAX_EXPECTED_JSON_BYTES,
                    });
                }
            }
        }
        Expectation::All { expectations } => {
            if expectations.is_empty() {
                return Err(FlowValidationError::EmptyExpectation {
                    step_index,
                    field: "group",
                });
            }
            if expectations.len() > MAX_EXPECTATIONS {
                return Err(FlowValidationError::TooManyExpectations {
                    actual: u128::try_from(expectations.len()).map_err(|_| {
                        FlowValidationError::TooManyExpectations {
                            actual: u128::MAX,
                            maximum: MAX_EXPECTATIONS,
                        }
                    })?,
                    maximum: MAX_EXPECTATIONS,
                });
            }
            let child_depth =
                depth
                    .checked_add(1)
                    .ok_or(FlowValidationError::ExpectationTooDeep {
                        actual: u32::MAX,
                        maximum: MAX_EXPECTATION_DEPTH,
                    })?;
            for child in expectations {
                validate_expectation(child, step_index, limits, child_depth, count)?;
            }
        }
    }
    Ok(())
}

fn validate_json_pointer(pointer: &str, step_index: u64) -> Result<(), FlowValidationError> {
    if pointer.len() > MAX_JSON_POINTER_BYTES {
        return Err(FlowValidationError::ExpectationValueTooLong {
            step_index,
            field: "JSON Pointer",
            actual: pointer.len(),
            maximum: MAX_JSON_POINTER_BYTES,
        });
    }
    if pointer.is_empty() {
        return Ok(());
    }
    if !pointer.starts_with('/') {
        return Err(FlowValidationError::InvalidExpectation {
            step_index,
            reason: "JSON match path must be an RFC 6901 JSON Pointer".into(),
        });
    }
    let mut bytes = pointer.bytes();
    while let Some(byte) = bytes.next() {
        if byte == b'~' {
            let escaped = bytes.next();
            if !matches!(escaped, Some(b'0' | b'1')) {
                return Err(FlowValidationError::InvalidExpectation {
                    step_index,
                    reason: "JSON Pointer contains an invalid escape".into(),
                });
            }
        }
    }
    Ok(())
}

fn validate_text(
    value: &str,
    field: &'static str,
    step_index: u64,
    maximum: usize,
) -> Result<(), FlowValidationError> {
    if value.trim().is_empty() {
        return Err(FlowValidationError::EmptyExpectation { step_index, field });
    }
    if value.len() > maximum {
        return Err(FlowValidationError::ExpectationValueTooLong {
            step_index,
            field,
            actual: value.len(),
            maximum,
        });
    }
    Ok(())
}

fn validate_timeout(duration: Duration) -> Result<(), FlowValidationError> {
    if duration.is_zero() || timing::checked_deadline(duration).is_none() {
        return Err(FlowValidationError::InvalidTimeout);
    }
    Ok(())
}

fn validate_selector(
    selector: &str,
    step_index: u64,
    maximum: usize,
) -> Result<(), FlowValidationError> {
    validate_nonempty_and_bounded(
        selector,
        maximum,
        FlowValidationError::EmptySelector { step_index },
        |actual, maximum| FlowValidationError::SelectorTooLong {
            step_index,
            actual,
            maximum,
        },
    )
}

fn validate_nonempty_and_bounded(
    value: &str,
    maximum: usize,
    empty: FlowValidationError,
    too_long: impl FnOnce(usize, usize) -> FlowValidationError,
) -> Result<(), FlowValidationError> {
    if value.trim().is_empty() {
        return Err(empty);
    }
    if value.len() > maximum {
        return Err(too_long(value.len(), maximum));
    }
    Ok(())
}

#[cfg(test)]
#[path = "validation_until_tests.rs"]
mod until_tests;
