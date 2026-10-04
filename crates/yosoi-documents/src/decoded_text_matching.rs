use memchr::memmem;
use regex::{Captures, Regex, RegexBuilder};

use super::evaluation::TextFindingSink;
use super::limits::{enforce_limit, limit_failure};
use super::{CompiledTextRegex, TextMatch};
use crate::{LocateFailure, ProjectedValue, ResourceBudget, ResourceLimit};

pub(super) use super::limits::{invalid_plan, parse_failed};

const REGEX_PROGRAM_SIZE_LIMIT: usize = 1_048_576;
const REGEX_DFA_SIZE_LIMIT: usize = 2_097_152;

pub(super) fn compile_regex(expression: &str) -> Result<Regex, regex::Error> {
    let mut builder = RegexBuilder::new(expression);
    builder
        .size_limit(REGEX_PROGRAM_SIZE_LIMIT)
        .dfa_size_limit(REGEX_DFA_SIZE_LIMIT)
        .unicode(true);
    builder.build()
}

#[derive(Clone, Copy, Debug, Default)]
pub(super) struct EvaluationTotals {
    matches: u64,
    captures: u64,
    output_bytes: u64,
}

impl EvaluationTotals {
    pub(super) fn account_replayed_value(
        &mut self,
        value: &ProjectedValue,
        limits: ResourceBudget,
    ) -> Result<(), LocateFailure> {
        let (capture_count, output_bytes) = match value {
            ProjectedValue::Text(text) => (0, text.len()),
            ProjectedValue::TextWithCaptures { text, captures } => {
                let mut output_bytes = text.len();
                for (name, captured) in captures {
                    output_bytes = output_bytes
                        .checked_add(name.len())
                        .and_then(|bytes| bytes.checked_add(captured.len()))
                        .ok_or_else(|| {
                            limit_failure(
                                ResourceLimit::OutputBytes,
                                limits.max_output_bytes(),
                                u64::MAX,
                            )
                        })?;
                }
                (captures.len(), output_bytes)
            }
            _ => return Err(invalid_plan("decoded_text_projection_mismatch")),
        };
        let capture_count = u64::try_from(capture_count)
            .map_err(|_| limit_failure(ResourceLimit::Captures, limits.max_captures(), u64::MAX))?;
        let output_bytes = u64::try_from(output_bytes).map_err(|_| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
        account_totals(self, capture_count, output_bytes, limits)
    }
}

pub(super) fn locate_literal(
    text: &str,
    output_index: usize,
    expression: &str,
    limits: ResourceBudget,
    totals: &mut EvaluationTotals,
    sink: &mut TextFindingSink<'_, '_>,
) -> Result<(), LocateFailure> {
    if expression.is_empty() {
        return Err(invalid_plan("empty_text_literal"));
    }
    let mut previous_byte_end = 0_usize;
    let mut previous_scalar_end = 0_u64;
    for start in memmem::find_iter(text.as_bytes(), expression.as_bytes()) {
        let end = start
            .checked_add(expression.len())
            .ok_or_else(|| parse_failed("coordinate_overflow"))?;
        let matched = prepare_match(
            text,
            output_index,
            start,
            end,
            previous_byte_end,
            previous_scalar_end,
            0,
            0,
            limits,
            totals,
        )?;
        previous_byte_end = matched.byte_end;
        previous_scalar_end = matched.scalar_end;
        sink.push_text(matched)?;
    }
    Ok(())
}

pub(super) fn locate_regex(
    text: &str,
    output_index: usize,
    compiled: &CompiledTextRegex,
    requested_captures: &[String],
    limits: ResourceBudget,
    totals: &mut EvaluationTotals,
    sink: &mut TextFindingSink<'_, '_>,
) -> Result<(), LocateFailure> {
    let regex = compiled.regex();
    let requested_capture_groups = compiled.requested_capture_groups();
    if requested_capture_groups.len() != requested_captures.len() {
        return Err(invalid_plan("regex_capture_plan_mismatch"));
    }
    let capture_count = regex
        .captures_len()
        .checked_sub(1)
        .ok_or_else(|| invalid_plan("invalid_regex_capture_count"))?;
    let capture_count =
        u64::try_from(capture_count).map_err(|_| invalid_plan("regex_capture_count_overflow"))?;
    enforce_limit(
        ResourceLimit::Captures,
        limits.max_captures(),
        capture_count,
    )?;

    let mut previous_byte_end = 0_usize;
    let mut previous_scalar_end = 0_u64;
    if requested_captures.is_empty() {
        for found in regex.find_iter(text) {
            let matched = prepare_match(
                text,
                output_index,
                found.start(),
                found.end(),
                previous_byte_end,
                previous_scalar_end,
                0,
                0,
                limits,
                totals,
            )?;
            previous_byte_end = matched.byte_end;
            previous_scalar_end = matched.scalar_end;
            sink.push_text(matched)?;
        }
        return Ok(());
    }

    for captures in regex.captures_iter(text) {
        let Some(found) = captures.get(0) else {
            return Err(invalid_plan("regex_match_missing_group_zero"));
        };
        let (capture_count, capture_output_bytes) = capture_metrics(
            &captures,
            requested_capture_groups,
            requested_captures,
            limits,
        )?;
        let matched = prepare_match(
            text,
            output_index,
            found.start(),
            found.end(),
            previous_byte_end,
            previous_scalar_end,
            capture_count,
            capture_output_bytes,
            limits,
            totals,
        )?;
        previous_byte_end = matched.byte_end;
        previous_scalar_end = matched.scalar_end;
        sink.push_captures(matched, &captures, compiled)?;
    }
    Ok(())
}

fn capture_metrics(
    captures: &Captures<'_>,
    groups: &[usize],
    names: &[String],
    limits: ResourceBudget,
) -> Result<(u64, u64), LocateFailure> {
    let mut capture_count = 0_u64;
    let mut output_bytes = 0_u64;
    for (capture_index, group) in groups.iter().copied().enumerate() {
        let Some(capture) = captures.get(group) else {
            continue;
        };
        let name = names
            .get(capture_index)
            .ok_or_else(|| invalid_plan("regex_capture_name_missing"))?;
        capture_count = capture_count.checked_add(1).ok_or_else(|| {
            limit_failure(ResourceLimit::Captures, limits.max_captures(), u64::MAX)
        })?;
        let name_bytes = u64::try_from(name.len()).map_err(|_| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
        let value_bytes = u64::try_from(capture.as_str().len()).map_err(|_| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
        output_bytes = output_bytes
            .checked_add(name_bytes)
            .and_then(|value| value.checked_add(value_bytes))
            .ok_or_else(|| {
                limit_failure(
                    ResourceLimit::OutputBytes,
                    limits.max_output_bytes(),
                    u64::MAX,
                )
            })?;
    }
    Ok((capture_count, output_bytes))
}

#[allow(clippy::too_many_arguments)]
fn prepare_match(
    text: &str,
    output_index: usize,
    start: usize,
    end: usize,
    previous_byte_end: usize,
    previous_scalar_end: u64,
    capture_count: u64,
    capture_output_bytes: u64,
    limits: ResourceBudget,
    totals: &mut EvaluationTotals,
) -> Result<TextMatch, LocateFailure> {
    if start < previous_byte_end || end < start {
        return Err(parse_failed("non_monotonic_text_match"));
    }
    let gap = text
        .get(previous_byte_end..start)
        .ok_or_else(|| parse_failed("invalid_match_start"))?;
    let matched_text = text
        .get(start..end)
        .ok_or_else(|| parse_failed("invalid_match_end"))?;
    let next_match_count = totals
        .matches
        .checked_add(1)
        .ok_or_else(|| limit_failure(ResourceLimit::Matches, limits.max_matches(), u64::MAX))?;
    enforce_limit(
        ResourceLimit::Matches,
        limits.max_matches(),
        next_match_count,
    )?;

    let next_capture_count = totals
        .captures
        .checked_add(capture_count)
        .ok_or_else(|| limit_failure(ResourceLimit::Captures, limits.max_captures(), u64::MAX))?;
    enforce_limit(
        ResourceLimit::Captures,
        limits.max_captures(),
        next_capture_count,
    )?;

    let match_bytes = u64::try_from(matched_text.len()).map_err(|_| {
        limit_failure(
            ResourceLimit::OutputBytes,
            limits.max_output_bytes(),
            u64::MAX,
        )
    })?;
    let match_output_bytes = match_bytes
        .checked_add(capture_output_bytes)
        .ok_or_else(|| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
    let next_output_bytes = totals
        .output_bytes
        .checked_add(match_output_bytes)
        .ok_or_else(|| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
    enforce_limit(
        ResourceLimit::OutputBytes,
        limits.max_output_bytes(),
        next_output_bytes,
    )?;

    let gap_scalars = scalar_count(gap)?;
    let matched_scalars = scalar_count(matched_text)?;
    let scalar_start = previous_scalar_end
        .checked_add(gap_scalars)
        .ok_or_else(|| parse_failed("scalar_count_overflow"))?;
    let scalar_end = scalar_start
        .checked_add(matched_scalars)
        .ok_or_else(|| parse_failed("scalar_count_overflow"))?;

    totals.matches = next_match_count;
    totals.captures = next_capture_count;
    totals.output_bytes = next_output_bytes;
    Ok(TextMatch {
        output_index,
        byte_start: start,
        byte_end: end,
        scalar_start,
        scalar_end,
    })
}

fn account_totals(
    totals: &mut EvaluationTotals,
    capture_count: u64,
    output_bytes: u64,
    limits: ResourceBudget,
) -> Result<(), LocateFailure> {
    let next_match_count = totals
        .matches
        .checked_add(1)
        .ok_or_else(|| limit_failure(ResourceLimit::Matches, limits.max_matches(), u64::MAX))?;
    enforce_limit(
        ResourceLimit::Matches,
        limits.max_matches(),
        next_match_count,
    )?;
    let next_capture_count = totals
        .captures
        .checked_add(capture_count)
        .ok_or_else(|| limit_failure(ResourceLimit::Captures, limits.max_captures(), u64::MAX))?;
    enforce_limit(
        ResourceLimit::Captures,
        limits.max_captures(),
        next_capture_count,
    )?;
    let next_output_bytes = totals
        .output_bytes
        .checked_add(output_bytes)
        .ok_or_else(|| {
            limit_failure(
                ResourceLimit::OutputBytes,
                limits.max_output_bytes(),
                u64::MAX,
            )
        })?;
    enforce_limit(
        ResourceLimit::OutputBytes,
        limits.max_output_bytes(),
        next_output_bytes,
    )?;
    totals.matches = next_match_count;
    totals.captures = next_capture_count;
    totals.output_bytes = next_output_bytes;
    Ok(())
}

fn scalar_count(value: &str) -> Result<u64, LocateFailure> {
    let count = if value.is_ascii() {
        value.len()
    } else {
        value.chars().count()
    };
    u64::try_from(count).map_err(|_| parse_failed("scalar_count_overflow"))
}
