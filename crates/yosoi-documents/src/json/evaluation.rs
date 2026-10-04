use std::io::{self, Write};

use serde_json::Value;

use crate::{
    Completeness, DocumentId, Finding, JsonCoordinate, LocateFailure, LocateOutcome,
    NativeCoordinate, OutputId, ProjectedValue, ResourceBudget, ResourceLimit,
};

use super::query::{JsonPathSelector, JsonVisitBudget, canonical_pointer};

#[allow(clippy::too_many_arguments)] // Explicit recursion state preserves bounded traversal.
pub(super) fn walk_json_path(
    current: &Value,
    selectors: &[JsonPathSelector],
    selector_index: usize,
    path: &mut Vec<String>,
    document_id: &DocumentId,
    output_id: &OutputId,
    limits: ResourceBudget,
    visit_budget: &mut JsonVisitBudget,
    findings: &mut Vec<Finding>,
    match_count: &mut u64,
    output_bytes: &mut u64,
) -> Result<(), LocateFailure> {
    visit_budget.charge()?;
    let Some(selector) = selectors.get(selector_index) else {
        let pointer = canonical_pointer(path);
        return emit_finding(
            document_id,
            output_id,
            &pointer,
            current,
            limits,
            findings,
            match_count,
            output_bytes,
        );
    };
    let next_selector = selector_index
        .checked_add(1)
        .ok_or_else(|| invalid_plan_failure("json_path_step_overflow"))?;

    match selector {
        JsonPathSelector::Child(name) => {
            if let Value::Object(object) = current
                && let Some(value) = object.get(name)
            {
                path.push(name.clone());
                let result = walk_json_path(
                    value,
                    selectors,
                    next_selector,
                    path,
                    document_id,
                    output_id,
                    limits,
                    visit_budget,
                    findings,
                    match_count,
                    output_bytes,
                );
                let _ = path.pop();
                result?;
            }
        }
        JsonPathSelector::Index(index) => {
            if let Value::Array(array) = current
                && let Some(value) = array.get(*index)
            {
                path.push(index.to_string());
                let result = walk_json_path(
                    value,
                    selectors,
                    next_selector,
                    path,
                    document_id,
                    output_id,
                    limits,
                    visit_budget,
                    findings,
                    match_count,
                    output_bytes,
                );
                let _ = path.pop();
                result?;
            }
        }
        JsonPathSelector::ArrayWildcard => {
            if let Value::Array(array) = current {
                for (index, value) in array.iter().enumerate() {
                    path.push(index.to_string());
                    let result = walk_json_path(
                        value,
                        selectors,
                        next_selector,
                        path,
                        document_id,
                        output_id,
                        limits,
                        visit_budget,
                        findings,
                        match_count,
                        output_bytes,
                    );
                    let _ = path.pop();
                    result?;
                }
            }
        }
    }
    Ok(())
}

#[allow(clippy::too_many_arguments)] // Explicit counters share one plan-wide budget.
pub(super) fn emit_finding(
    document_id: &DocumentId,
    output_id: &OutputId,
    pointer: &str,
    value: &Value,
    limits: ResourceBudget,
    findings: &mut Vec<Finding>,
    match_count: &mut u64,
    output_bytes: &mut u64,
) -> Result<(), LocateFailure> {
    let next_match_count = match_count
        .checked_add(1)
        .ok_or_else(|| limit_failure(ResourceLimit::Matches, limits.max_matches(), u64::MAX))?;
    if next_match_count > limits.max_matches() {
        return Err(limit_failure(
            ResourceLimit::Matches,
            limits.max_matches(),
            next_match_count,
        ));
    }

    let pointer_bytes = u64::try_from(pointer.len()).map_err(|_| {
        limit_failure(
            ResourceLimit::OutputBytes,
            limits.max_output_bytes(),
            u64::MAX,
        )
    })?;
    let maximum_output_bytes = limits.max_output_bytes();
    let value_bytes = match serialized_json_size(value) {
        Ok(value_bytes) => value_bytes,
        Err(SerializedJsonSizeError::Overflow) => {
            return Err(limit_failure(
                ResourceLimit::OutputBytes,
                maximum_output_bytes,
                u64::MAX,
            ));
        }
        Err(SerializedJsonSizeError::SerializationFailed) => {
            return Err(invalid_plan_failure("json_value_serialization_failed"));
        }
    };
    let added_bytes = pointer_bytes
        .checked_add(value_bytes)
        .ok_or_else(|| limit_failure(ResourceLimit::OutputBytes, maximum_output_bytes, u64::MAX))?;
    let next_output_bytes = output_bytes
        .checked_add(added_bytes)
        .ok_or_else(|| limit_failure(ResourceLimit::OutputBytes, maximum_output_bytes, u64::MAX))?;
    if next_output_bytes > maximum_output_bytes {
        return Err(limit_failure(
            ResourceLimit::OutputBytes,
            maximum_output_bytes,
            next_output_bytes,
        ));
    }

    let coordinate = JsonCoordinate::try_new(pointer.to_owned())
        .map_err(|_| invalid_plan_failure("generated_json_pointer_is_invalid"))?;
    let finding = Finding::try_new(
        document_id.clone(),
        output_id.clone(),
        *match_count,
        NativeCoordinate::Json(coordinate),
        ProjectedValue::Json(value.clone()),
        Completeness::Complete,
        None,
    )
    .map_err(|_| invalid_plan_failure("invalid_json_finding"))?;
    findings.push(finding);
    *match_count = next_match_count;
    *output_bytes = next_output_bytes;
    Ok(())
}

enum SerializedJsonSizeError {
    Overflow,
    SerializationFailed,
}

fn serialized_json_size(value: &Value) -> Result<u64, SerializedJsonSizeError> {
    let mut writer = JsonByteCounter {
        written: 0,
        overflowed: false,
    };
    match serde_json::to_writer(&mut writer, value) {
        Ok(()) => Ok(writer.written),
        Err(_) => {
            if writer.overflowed {
                Err(SerializedJsonSizeError::Overflow)
            } else {
                Err(SerializedJsonSizeError::SerializationFailed)
            }
        }
    }
}

struct JsonByteCounter {
    written: u64,
    overflowed: bool,
}

impl Write for JsonByteCounter {
    fn write(&mut self, bytes: &[u8]) -> io::Result<usize> {
        let Ok(chunk_bytes) = u64::try_from(bytes.len()) else {
            self.overflowed = true;
            return Err(io::Error::other("serialized output byte count overflow"));
        };
        let Some(next) = self.written.checked_add(chunk_bytes) else {
            self.overflowed = true;
            return Err(io::Error::other("serialized output byte count overflow"));
        };
        self.written = next;
        Ok(bytes.len())
    }

    fn flush(&mut self) -> io::Result<()> {
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

fn invalid_plan_failure(code: &str) -> LocateFailure {
    LocateFailure::InvalidPlan {
        code: code.to_owned(),
    }
}

pub(super) const fn failed(failure: LocateFailure) -> LocateOutcome {
    LocateOutcome::Failed { failure }
}
