#[cfg(test)]
use std::env;

use super::config::{
    MAX_CERTIFIED_FORMATTING_DEPTH, REPAIR_DEPTH_ALLOWANCE, REPAIR_NODE_ALLOWANCE,
};
use super::names::{COL, COLGROUP, NameKey, P, PATH, SVG, TABLE, TBODY, TD, TITLE, TR};
use super::plan::CompiledSelectorPlan;
use super::scanner::{ImpliedKind, RecordMetrics};
use super::support::{basic, memchr};
use super::tag_rules::{classify_tag, could_close_outer_record, is_formatting_tag};
use super::tokenizer::{compound_tests_match, parse_closing_tag, parse_start_tag};

#[allow(
    clippy::cognitive_complexity,
    reason = "bounded hazardous-record certification keeps repair and containment proof in one pass"
)]
pub(super) fn certify_hazardous_record(
    bytes: &[u8],
    plan: &CompiledSelectorPlan,
    outer_implied: ImpliedKind,
) -> Option<RecordMetrics> {
    let source = basic::from_utf8(bytes).ok()?;
    let mut cursor = 0_usize;
    macro_rules! reject {
        ($reason:literal) => {{
            #[cfg(test)]
            if env::var_os("YOSOI_ISLAND_TRACE").is_some() {
                eprintln!("island reject at byte {}: {}", cursor, $reason);
            }
            return None;
        }};
    }
    let mut elements = 0_u64;
    let mut text_runs = 0_u64;
    let mut tables = 0_u64;
    let mut repair_allowance = 0_u64;
    let mut work = 0_u64;
    let mut rightmost_matches = 0_u64;
    let mut max_attribute_count = 0_u64;
    let mut max_depth = 0_u64;
    let mut stack = Vec::<NameKey>::with_capacity(32);
    let mut formatting = Vec::<NameKey>::with_capacity(8);
    while cursor < bytes.len() {
        let Some(relative) = memchr(b'<', bytes.get(cursor..)?) else {
            text_runs = text_runs.checked_add(u64::from(!bytes.get(cursor..)?.is_empty()))?;
            if stack.contains(&TABLE)
                && stack.last().copied() != Some(TD)
                && bytes
                    .get(cursor..)?
                    .iter()
                    .any(|byte| !byte.is_ascii_whitespace())
            {
                reject!("non-whitespace table tail");
            }
            break;
        };
        let start = cursor.checked_add(relative)?;
        text_runs = text_runs.checked_add(u64::from(start > cursor))?;
        if stack.contains(&TABLE)
            && stack.last().copied() != Some(TD)
            && bytes
                .get(cursor..start)?
                .iter()
                .any(|byte| !byte.is_ascii_whitespace())
        {
            reject!("non-whitespace table text");
        }
        if bytes.get(start..)?.starts_with(b"<!--") {
            reject!("comment");
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
        if bytes
            .get(name_end)
            .is_none_or(|byte| !byte.is_ascii_whitespace() && !matches!(*byte, b'/' | b'>'))
        {
            reject!("invalid tag-name delimiter");
        }
        let name = NameKey::from_lower(bytes.get(name_start..name_end)?)?;
        let parsed = (!closing)
            .then(|| parse_start_tag(source, name_end, plan, true))
            .flatten();
        let self_closing = parsed
            .as_ref()
            .is_some_and(|start_tag| start_tag.self_closing);
        let in_svg = stack.contains(&SVG);
        let facts = classify_tag(name, plan, in_svg);
        if !closing
            && could_close_outer_record(outer_implied, facts.implied, facts.closes_paragraph)
        {
            reject!("tag can close the outer skipped record");
        }
        if facts.leftmost
            || (facts.unsupported && !(in_svg && name == TITLE))
            || (in_svg && !matches!(name, TITLE | PATH | SVG))
            || (!in_svg && name == PATH)
        {
            reject!("unsupported selector or foreign tag");
        }
        if !facts.formatting && !formatting.is_empty() {
            reject!("structural token inside formatting island");
        }
        if !closing && facts.closes_paragraph && stack.contains(&P) {
            reject!("implied paragraph closure inside skipped record");
        }
        let attribute_count = parsed
            .as_ref()
            .map_or(0, |start_tag| start_tag.attributes.source_count);
        work = work.checked_add(attribute_count.checked_add(1)?)?;
        max_attribute_count = max_attribute_count.max(attribute_count);
        if facts.rightmost
            && parsed.as_ref().is_some_and(|start_tag| {
                compound_tests_match(&start_tag.attributes, &plan.rightmost)
            })
        {
            rightmost_matches = rightmost_matches.checked_add(1)?;
        }
        if facts.formatting {
            repair_allowance = repair_allowance.checked_add(REPAIR_NODE_ALLOWANCE)?;
            if closing {
                let position = formatting.iter().rposition(|open| *open == name)?;
                formatting.remove(position);
            } else {
                if formatting.len() >= MAX_CERTIFIED_FORMATTING_DEPTH {
                    reject!("formatting depth exceeds repair proof");
                }
                formatting.push(name);
                elements = elements.checked_add(1)?;
            }
        } else if closing {
            if stack.last().copied() != Some(name) {
                reject!("mismatched structural close");
            }
            stack.pop();
        } else {
            let parent = stack.last().copied();
            if name == TABLE {
                if in_svg || stack.contains(&TABLE) {
                    reject!("nested table or table in foreign content");
                }
                tables = tables.checked_add(1)?;
            } else if stack.contains(&TABLE)
                && !matches!((parent, name), (Some(TABLE), TR) | (Some(TR), TD))
            {
                reject!("unsupported table child");
            }
            if name == SVG && in_svg {
                reject!("nested svg");
            }
            if self_closing && !facts.void && name != PATH {
                reject!("unsupported self-closing html tag");
            }
            elements = elements.checked_add(1)?;
            if !facts.void && !self_closing {
                stack.push(name);
            }
        }
        let depth = u64::try_from(stack.len().checked_add(formatting.len())?).ok()?;
        max_depth = max_depth.max(depth);
        cursor = if closing {
            parse_closing_tag(bytes, name_end)?
        } else {
            parsed?.next
        };
    }
    if stack.as_slice() == [P] {
        stack.clear();
    }
    if !stack.is_empty() || !formatting.is_empty() {
        reject!("unclosed structural or formatting state");
    }
    let table_element_upper = tables.checked_mul(4)?;
    let synthetic_element_upper = table_element_upper.checked_add(repair_allowance)?;
    let retained_nodes = elements
        .checked_add(text_runs)?
        .checked_add(1)?
        .checked_add(synthetic_element_upper)?;
    let element_upper = elements.checked_add(synthetic_element_upper)?;
    // Adoption agency only clones formatting tags. Table repair only inserts
    // table-family tags. A different rightmost tag cannot match those nodes.
    let formatting_matches =
        u64::from(is_formatting_tag(plan.rightmost.tag)).checked_mul(repair_allowance)?;
    let table_matches = u64::from(matches!(
        plan.rightmost.tag,
        TABLE | TBODY | TR | TD | COLGROUP | COL
    ))
    .checked_mul(table_element_upper)?;
    let rightmost_match_upper = rightmost_matches
        .checked_add(formatting_matches)?
        .checked_add(table_matches)?;
    // At most eight active formatting entries can be reconstructed across
    // eight adoption passes; total repaired node count need not be one chain.
    let repair_depth = u64::from(repair_allowance > 0).checked_mul(REPAIR_DEPTH_ALLOWANCE)?;
    let depth_upper = max_depth
        .checked_add(table_element_upper)?
        .checked_add(repair_depth)?;
    Some(RecordMetrics {
        retained_nodes,
        elements: element_upper,
        depth: depth_upper,
        work,
        rightmost_matches: rightmost_match_upper,
        max_attribute_count,
    })
}
