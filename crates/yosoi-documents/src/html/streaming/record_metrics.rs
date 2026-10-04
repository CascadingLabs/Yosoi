use super::config::PARALLEL_MAX_WORKERS;
use super::names::{COL, COLGROUP, NameKey, TABLE, TBODY, TD, TR};
use super::plan::CompiledSelectorPlan;
use super::scanner::{ImpliedKind, RecordMeasure, RecordMetrics};
use super::support::{OnceLock, ThreadPool, ThreadPoolBuilder, basic, memchr, thread};
use super::tag_rules::{classify_tag, could_close_outer_record, is_slow_record_name};
use super::tokenizer::{compound_tests_match, find_tag_end, parse_closing_tag, parse_start_tag};

static RECORD_POOL: OnceLock<Result<ThreadPool, ()>> = OnceLock::new();

pub(super) fn record_pool() -> Option<&'static ThreadPool> {
    RECORD_POOL
        .get_or_init(|| {
            let available = thread::available_parallelism().map_or(1, usize::from);
            ThreadPoolBuilder::new()
                .num_threads(available.clamp(1, PARALLEL_MAX_WORKERS))
                .thread_name(|index| format!("yosoi-html-record-{index}"))
                .build()
                .map_err(|_| ())
        })
        .as_ref()
        .ok()
}

pub(super) fn fast_record_metrics(
    bytes: &[u8],
    plan: &CompiledSelectorPlan,
    exact_selector_metrics: bool,
    outer_implied: ImpliedKind,
) -> RecordMeasure {
    let mut needs_sequential = false;
    match fast_record_metrics_inner(
        bytes,
        plan,
        exact_selector_metrics,
        outer_implied,
        &mut needs_sequential,
    ) {
        Some(metrics) => RecordMeasure::Metrics(metrics),
        None if needs_sequential => RecordMeasure::NeedsSequential,
        None => RecordMeasure::Invalid,
    }
}

#[allow(
    clippy::cognitive_complexity,
    reason = "allocation-free skipped-record certification keeps grammar, selector metrics, and bounds in one pass"
)]
fn fast_record_metrics_inner(
    bytes: &[u8],
    plan: &CompiledSelectorPlan,
    exact_selector_metrics: bool,
    outer_implied: ImpliedKind,
    needs_sequential: &mut bool,
) -> Option<RecordMetrics> {
    let source = exact_selector_metrics
        .then(|| basic::from_utf8(bytes).ok())
        .flatten();
    let mut cursor = 0_usize;
    let mut elements = 0_u64;
    let mut text_runs = 0_u64;
    let mut tables = 0_u64;
    let mut paragraphs = 0_i32;
    let mut list_items = 0_i32;
    let mut headings = 0_i32;
    let mut work = 0_u64;
    let mut rightmost_matches = 0_u64;
    let mut max_attribute_count = 0_u64;
    let mut stack = [None; 64];
    let mut stack_len = 0_usize;
    while cursor < bytes.len() {
        let Some(relative) = memchr(b'<', bytes.get(cursor..)?) else {
            text_runs = text_runs.checked_add(u64::from(!bytes.get(cursor..)?.is_empty()))?;
            if stack.get(..stack_len)?.contains(&Some(TABLE))
                && stack.get(stack_len.checked_sub(1)?).copied().flatten() != Some(TD)
                && bytes
                    .get(cursor..)?
                    .iter()
                    .any(|byte| !byte.is_ascii_whitespace())
            {
                *needs_sequential = true;
                return None;
            }
            break;
        };
        let start = cursor.checked_add(relative)?;
        text_runs = text_runs.checked_add(u64::from(start > cursor))?;
        if stack.get(..stack_len)?.contains(&Some(TABLE))
            && stack.get(stack_len.checked_sub(1)?).copied().flatten() != Some(TD)
            && bytes
                .get(cursor..start)?
                .iter()
                .any(|byte| !byte.is_ascii_whitespace())
        {
            *needs_sequential = true;
            return None;
        }
        if bytes.get(start..)?.starts_with(b"<!--") {
            *needs_sequential = true;
            return None;
        }
        let mut name_start = start.checked_add(1)?;
        let closing = bytes.get(name_start) == Some(&b'/');
        if closing {
            name_start = name_start.checked_add(1)?;
        }
        let mut name_end = name_start;
        while bytes
            .get(name_end)
            .is_some_and(|byte| byte.is_ascii_alphanumeric() || matches!(*byte, b'-' | b'_'))
        {
            name_end = name_end.checked_add(1)?;
        }
        let name = bytes.get(name_start..name_end)?;
        if bytes
            .get(name_end)
            .is_none_or(|byte| !byte.is_ascii_whitespace() && !matches!(*byte, b'/' | b'>'))
        {
            return None;
        }
        if name.is_empty() || name.iter().any(u8::is_ascii_uppercase) || is_slow_record_name(name) {
            *needs_sequential = true;
            return None;
        }
        let name_key = NameKey::from_lower(name)?;
        let facts = classify_tag(name_key, plan, false);
        if facts.unsupported || facts.foreign || facts.leftmost {
            *needs_sequential = true;
            return None;
        }
        if !closing
            && could_close_outer_record(outer_implied, facts.implied, facts.closes_paragraph)
        {
            *needs_sequential = true;
            return None;
        }
        if !closing && facts.closes_paragraph && paragraphs > 0 {
            *needs_sequential = true;
            return None;
        }
        match (closing, name) {
            (false, b"p") => paragraphs = paragraphs.checked_add(1)?,
            (true, b"p") => {
                paragraphs = paragraphs.checked_sub(1)?;
            }
            (false, b"li") => list_items = list_items.checked_add(1)?,
            (true, b"li") => list_items = list_items.checked_sub(1)?,
            (false, b"h1" | b"h2" | b"h3" | b"h4" | b"h5" | b"h6") => {
                headings = headings.checked_add(1)?;
            }
            (true, b"h1" | b"h2" | b"h3" | b"h4" | b"h5" | b"h6") => {
                headings = headings.checked_sub(1)?;
            }
            (false, b"table") => tables = tables.checked_add(1)?,
            _ => {}
        }
        elements = elements.checked_add(u64::from(!closing))?;
        if closing {
            let top = stack_len.checked_sub(1)?;
            if stack.get(top).copied().flatten() != Some(name_key) {
                *needs_sequential = true;
                return None;
            }
            stack_len = top;
            cursor = parse_closing_tag(bytes, name_end)?;
        } else {
            let next = if let Some(source) = source {
                let parsed = parse_start_tag(source, name_end, plan, facts.rightmost)?;
                if parsed.self_closing && !facts.void {
                    *needs_sequential = true;
                    return None;
                }
                work = work.checked_add(parsed.attributes.source_count.checked_add(1)?)?;
                max_attribute_count = max_attribute_count.max(parsed.attributes.source_count);
                if facts.rightmost && compound_tests_match(&parsed.attributes, &plan.rightmost) {
                    rightmost_matches = rightmost_matches.checked_add(1)?;
                }
                parsed.next
            } else {
                let end = find_tag_end(bytes, name_end)?;
                let tag_tail = bytes.get(name_end..end)?;
                if !facts.void && memchr(b'/', tag_tail).is_some() {
                    *needs_sequential = true;
                    return None;
                }
                let attribute_count_upper = u64::try_from(tag_tail.len())
                    .ok()?
                    .checked_add(1)?
                    .checked_div(2)?;
                work = work.checked_add(attribute_count_upper.checked_add(1)?)?;
                max_attribute_count = max_attribute_count.max(attribute_count_upper);
                if facts.rightmost {
                    rightmost_matches = rightmost_matches.checked_add(1)?;
                }
                end.checked_add(1)?
            };
            let parent = stack_len
                .checked_sub(1)
                .and_then(|index| stack.get(index))
                .copied()
                .flatten();
            if name_key == TABLE {
                if stack.get(..stack_len)?.contains(&Some(TABLE)) {
                    *needs_sequential = true;
                    return None;
                }
            } else if stack.get(..stack_len)?.contains(&Some(TABLE))
                && !matches!((parent, name_key), (Some(TABLE), TR) | (Some(TR), TD))
            {
                *needs_sequential = true;
                return None;
            }
            if !facts.void {
                *stack.get_mut(stack_len)? = Some(name_key);
                stack_len = stack_len.checked_add(1)?;
            }
            cursor = next;
        }
    }
    if paragraphs != 0 || list_items != 0 || headings != 0 || stack_len != 0 {
        *needs_sequential = true;
        return None;
    }
    let synthetic_element_upper = tables.checked_mul(4)?;
    let synthetic_rightmost_upper = u64::from(matches!(
        plan.rightmost.tag,
        TABLE | TBODY | TR | TD | COLGROUP | COL
    ))
    .checked_mul(synthetic_element_upper)?;
    let retained_nodes = elements
        .checked_add(text_runs)?
        .checked_add(1)?
        .checked_add(synthetic_element_upper)?;
    Some(RecordMetrics {
        retained_nodes,
        elements: elements.checked_add(synthetic_element_upper)?,
        depth: elements.checked_add(synthetic_element_upper)?,
        work,
        rightmost_matches: rightmost_matches.checked_add(synthetic_rightmost_upper)?,
        max_attribute_count,
    })
}
