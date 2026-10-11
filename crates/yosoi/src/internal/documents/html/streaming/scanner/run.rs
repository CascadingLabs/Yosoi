use std::mem;

use super::super::config::PARALLEL_MIN_BYTES;
use super::super::names::{BODY, HEAD, NameKey, TITLE};
use super::super::plan::CompiledSelectorPlan;
use super::super::support::{
    HashMap, HashSet, ResourceBudget, append_normalized_text, memchr, memmem,
};
use super::super::tag_rules::{classify_tag, is_formatting_tag};
use super::super::tokenizer::{
    find_tag_end, parse_closing_tag, parse_start_tag, simple_raw_text_island,
};
use super::{FOREIGN_CONTEXT, ImpliedKind, ScanAttempt, ScanResult, Scanner, StreamValue};

pub(super) fn scan(
    source: &str,
    plan: &CompiledSelectorPlan,
    budget: ResourceBudget,
) -> ScanAttempt {
    let mut scanner = Scanner::new(source, plan, budget);
    match scanner.run() {
        Some(result) => ScanAttempt::Complete(result),
        None => ScanAttempt::Rejected {
            resource_proof_incomplete: scanner.resource_proof_incomplete,
            parser_offset: scanner.parser_offset,
            candidate_work: scanner.scan_work,
        },
    }
}

impl<'source, 'plan> Scanner<'source, 'plan> {
    fn new(
        source: &'source str,
        plan: &'plan CompiledSelectorPlan,
        budget: ResourceBudget,
    ) -> Self {
        Self {
            source,
            plan,
            budget,
            stack: Vec::with_capacity(32),
            matches: Vec::with_capacity(8),
            active_match: None,
            next_id: 1,
            root_count: 0,
            html_children: Vec::with_capacity(2),
            candidate_parent: None,
            grid_parent: None,
            candidate_roots: HashSet::with_capacity(8),
            hazard_roots: HashSet::with_capacity(8),
            first_table_by_root: HashMap::with_capacity(16),
            retained_node_upper: 2,
            element_upper: 0,
            scan_work: 0,
            max_depth: 0,
            rightmost_match_count: 0,
            rightmost_depth_sum_upper: 0,
            max_attribute_count: 0,
            projected_value_bytes: 0,
            parser_offset: None,
            resource_proof_incomplete: false,
            table_depth: 0,
            foreign_depth: 0,
            deferred_records: Vec::new(),
        }
    }

    #[allow(
        clippy::cognitive_complexity,
        reason = "one pass must keep validation, repair proof, selector state, coordinates, and text synchronized"
    )]
    fn run(&mut self) -> Option<ScanResult> {
        if !self
            .source
            .trim_start_matches(|character| {
                matches!(character, ' ' | '\t' | '\n' | '\u{000C}' | '\r')
            })
            .get(..15)
            .is_some_and(|prefix| prefix.eq_ignore_ascii_case("<!doctype html>"))
        {
            return None;
        }
        let bytes = self.source.as_bytes();
        let mut cursor = 0_usize;
        while cursor < bytes.len() {
            let Some(relative) = memchr(b'<', bytes.get(cursor..)?) else {
                self.push_text(self.source.get(cursor..)?)?;
                cursor = bytes.len();
                self.parser_offset = u64::try_from(cursor).ok();
                continue;
            };
            let start = cursor.checked_add(relative)?;
            self.push_text(self.source.get(cursor..start)?)?;
            self.parser_offset = u64::try_from(start).ok();
            if bytes.get(start..)?.starts_with(b"<!--") {
                let comment = bytes.get(start.checked_add(4)?..)?;
                let end = memmem::find(comment, b"-->")?;
                let next = start.checked_add(4)?.checked_add(end)?.checked_add(3)?;
                self.add_nodes(1)?;
                cursor = next;
                self.parser_offset = u64::try_from(cursor).ok();
                continue;
            }
            let mut name_start = start.checked_add(1)?;
            let closing = bytes.get(name_start) == Some(&b'/');
            if closing {
                name_start = name_start.checked_add(1)?;
            }
            if bytes
                .get(name_start)
                .is_none_or(|byte| !byte.is_ascii_alphabetic())
            {
                let next = find_tag_end(bytes, name_start)?.checked_add(1)?;
                self.add_nodes(1)?;
                cursor = next;
                self.parser_offset = u64::try_from(cursor).ok();
                continue;
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
                return None;
            }
            let name = NameKey::from_lower(bytes.get(name_start..name_end)?)?;
            let inside_foreign = self
                .stack
                .last()
                .is_some_and(|element| element.has_flag(FOREIGN_CONTEXT));
            let mut facts = classify_tag(name, self.plan, inside_foreign);
            if name == TITLE {
                let certified = if closing {
                    self.stack
                        .last()
                        .is_some_and(|element| element.name == TITLE)
                } else {
                    self.stack
                        .last()
                        .is_some_and(|element| element.name == HEAD)
                        && simple_raw_text_island(bytes, name_end, b"</title>")
                };
                if !certified {
                    return None;
                }
                facts.unsupported = false;
            }
            if facts.unsupported {
                return None;
            }
            let next =
                if closing {
                    let next = parse_closing_tag(bytes, name_end)?;
                    self.close(name, facts, start)?;
                    self.parser_offset = u64::try_from(next).ok();
                    next
                } else {
                    self.apply_implied_closes(facts.implied, facts.closes_paragraph)?;
                    let parsed = parse_start_tag(
                        self.source,
                        name_end,
                        self.plan,
                        facts.leftmost || facts.rightmost,
                    )?;
                    self.parser_offset = u64::try_from(parsed.next).ok();
                    if parsed.self_closing && !facts.foreign && !facts.void {
                        return None;
                    }
                    let skip_record = self.open(
                        name,
                        facts,
                        &parsed.attributes,
                        start,
                        parsed.self_closing || facts.void,
                    )?;
                    if skip_record {
                        // The record certifier receives the row's implied-close
                        // kind. Earlier ancestors are outside its local proof.
                        let outer_depth = self.stack.len();
                        let row = self.stack.last()?;
                        if is_formatting_tag(row.name)
                            || self.stack.iter().take(outer_depth.saturating_sub(1)).any(
                                |element| {
                                    element.implied != ImpliedKind::Other
                                        || is_formatting_tag(element.name)
                                },
                            )
                        {
                            return None;
                        }
                        let outer_implied = row.implied;
                        let remaining = bytes.get(parsed.next..)?;
                        let relative = self.plan.leftmost_close.find(remaining)?;
                        let close_start = parsed.next.checked_add(relative)?;
                        let interior = bytes.get(parsed.next..close_start)?;
                        if bytes.len() >= PARALLEL_MIN_BYTES {
                            self.deferred_records.push((
                                parsed.next,
                                close_start,
                                outer_depth,
                                outer_implied,
                            ));
                        } else if !self.fast_measure_skipped_record(interior, outer_implied)? {
                            return None;
                        }
                        let after = close_start.checked_add(self.plan.leftmost_close_len)?;
                        self.close(name, facts, close_start)?;
                        cursor = after;
                        self.parser_offset = u64::try_from(cursor).ok();
                        continue;
                    }
                    parsed.next
                };
            cursor = next;
            self.parser_offset = u64::try_from(cursor).ok();
        }
        self.finish_deferred_records()?;
        if !self.stack.is_empty()
            || self.active_match.is_some()
            || self.root_count != 1
            || self.html_children != [HEAD, BODY]
            || self.table_depth != 0
            || self.foreign_depth != 0
            || self.candidate_roots.is_empty()
            || self
                .candidate_roots
                .iter()
                .any(|candidate| self.hazard_roots.contains(candidate))
        {
            return None;
        }
        Some(ScanResult {
            matches: mem::take(&mut self.matches),
            retained_node_upper: self.retained_node_upper,
            element_upper: self.element_upper,
            depth_upper: self.max_depth.checked_add(8)?,
            rightmost_match_count: self.rightmost_match_count,
            rightmost_depth_sum_upper: self.rightmost_depth_sum_upper,
            max_attribute_count: self.max_attribute_count,
            scan_work: self.scan_work,
        })
    }

    pub(super) fn add_nodes(&mut self, count: u64) -> Option<()> {
        self.retained_node_upper = self.retained_node_upper.checked_add(count)?;
        if self.retained_node_upper > self.budget.max_nodes() {
            self.resource_proof_incomplete = true;
            return None;
        }
        Some(())
    }

    fn push_text(&mut self, value: &str) -> Option<()> {
        if !self
            .stack
            .iter()
            .any(|element| matches!(element.name, BODY | TITLE))
            && value
                .bytes()
                .any(|byte| !matches!(byte, b' ' | b'\t' | b'\n' | 0x0c | b'\r'))
        {
            return None;
        }
        if !value.is_empty() {
            self.add_nodes(1)?;
        }
        if let Some(active) = self.active_match {
            if self
                .projected_value_bytes
                .checked_add(u64::try_from(value.len()).ok()?)?
                > self.budget.max_output_bytes()
            {
                self.resource_proof_incomplete = true;
                return None;
            }
            let found = self.matches.get_mut(active)?;
            let StreamValue::Text {
                value: text,
                previous_was_space,
            } = &mut found.value
            else {
                return None;
            };
            let before = text.len();
            append_normalized_text(value, text, previous_was_space);
            let added = u64::try_from(text.len().checked_sub(before)?).ok()?;
            self.projected_value_bytes = self.projected_value_bytes.checked_add(added)?;
        }
        Some(())
    }
}
