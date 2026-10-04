use super::super::materialize::{materialize, stream_finding_bytes, stream_text_finding_bytes};
use super::super::names::{BODY, HEAD, HTML, MATH, NameKey, SVG, TABLE};
use super::super::plan::CompiledTreeTextPlan;
use super::super::scanner::{StreamMatch, StreamValue};
use super::super::support::{
    Document, LocateOutcome, ResourceBudget, ResourceLimit, SelectorVisitBudget, limit_failure,
    memchr, select_tree_text,
};
use super::super::tag_rules::{
    is_certified_tree_text_tag, is_formatting_tag, is_unsupported_tag, is_void_html_tag,
};
use super::super::tokenizer::find_tag_end;
use super::selection::{
    fast_tree_text_selection, maximum_match_occurrences, maximum_tree_text_visit_upper_bound,
    selected_tree_text_ranges, selected_tree_text_ranges_full, tree_text_coordinate,
    tree_text_push,
};
use super::{
    CompactTextSegment, TreeTextNode, TreeTextOpenElement, TreeTextRepairState, TreeTextTree,
};

#[allow(
    clippy::cognitive_complexity,
    reason = "one pass keeps HTML repair, normalized-text ownership, projections, and budget proofs aligned"
)]
pub(in crate::html::streaming) fn try_tree_text(
    document: &Document,
    output_name: &str,
    output_id: &crate::OutputId,
    source: &str,
    plan: &CompiledTreeTextPlan,
    budget: ResourceBudget,
) -> Option<LocateOutcome> {
    let bytes = source.as_bytes();
    let node_capacity_limit = usize::try_from(budget.max_nodes()).ok()?.min(65_536);
    let estimated_elements = bytes
        .len()
        .checked_div(24)?
        .checked_add(8)?
        .min(node_capacity_limit);
    let estimated_segments = bytes
        .len()
        .checked_div(32)?
        .checked_add(8)?
        .min(node_capacity_limit);
    let mut tree = TreeTextTree {
        nodes: Vec::with_capacity(estimated_elements),
        children: Vec::new(),
        child_ranges: Vec::new(),
    };
    let mut stack = Vec::<TreeTextOpenElement>::with_capacity(
        usize::try_from(budget.max_depth()).ok()?.min(256),
    );
    let mut normalized_text = String::with_capacity(bytes.len().checked_div(2)?.min(1_048_576));
    let mut text_segments = Vec::<CompactTextSegment>::with_capacity(estimated_segments);
    let mut previous_space = false;
    let mut retained_nodes = 1_u64;
    let mut maximum_depth = 0_u32;
    let mut saw_doctype = false;
    let mut root_opened = false;
    let mut html_children = Vec::<NameKey>::with_capacity(2);
    let mut repair_state = TreeTextRepairState::default();
    let mut cursor = 0_usize;
    while cursor < bytes.len() {
        let Some(relative) = memchr(b'<', bytes.get(cursor..)?) else {
            let text = source.get(cursor..)?;
            if !text.is_empty() {
                retained_nodes = retained_nodes.checked_add(1)?;
            }
            tree_text_push(
                text,
                &stack,
                &tree.nodes,
                &mut normalized_text,
                &mut text_segments,
                &mut previous_space,
            )?;
            break;
        };
        let start = cursor.checked_add(relative)?;
        let text = source.get(cursor..start)?;
        if !text.is_empty() {
            retained_nodes = retained_nodes.checked_add(1)?;
        }
        tree_text_push(
            text,
            &stack,
            &tree.nodes,
            &mut normalized_text,
            &mut text_segments,
            &mut previous_space,
        )?;
        if bytes.get(start..)?.starts_with(b"<!--") {
            return None;
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
            let end = find_tag_end(bytes, name_start)?;
            let token = bytes.get(start..=end)?;
            if saw_doctype
                || !tree.nodes.is_empty()
                || !stack.is_empty()
                || !token.eq_ignore_ascii_case(b"<!doctype html>")
            {
                return None;
            }
            saw_doctype = true;
            retained_nodes = retained_nodes.checked_add(1)?;
            cursor = end.checked_add(1)?;
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
        let end = find_tag_end(bytes, name_end)?;
        if is_unsupported_tag(name) || is_formatting_tag(name) || matches!(name, TABLE | SVG | MATH)
        {
            return None;
        }
        if !is_certified_tree_text_tag(name) {
            return None;
        }
        if closing {
            let open = stack.pop()?;
            if open.name != name {
                return None;
            }
            repair_state.closed(name);
        } else {
            let parent = stack.last().map(|open| open.id);
            if repair_state.requires_repair(name) {
                return None;
            }
            if (name == HTML && parent.is_some())
                || (matches!(name, HEAD | BODY) && parent != Some(0))
                || stack.last().is_some_and(|open| open.name == HEAD)
            {
                return None;
            }
            if parent.is_none() {
                if root_opened || name != HTML {
                    return None;
                }
                root_opened = true;
            }
            if name == BODY
                && stack.last().is_some_and(|open| open.name == HTML)
                && html_children.is_empty()
            {
                let parent = parent?;
                stack.last_mut()?.child_count = 1;
                tree.nodes.push(TreeTextNode {
                    parent: u32::try_from(parent).ok()?,
                    ordinal: 1,
                    depth: 2,
                });
                maximum_depth = maximum_depth.max(2);
                html_children.push(HEAD);
                retained_nodes = retained_nodes.checked_add(1)?;
            }
            if stack.last().is_some_and(|open| open.name == HTML) {
                let expected = match html_children.as_slice() {
                    [] => HEAD,
                    [HEAD] => BODY,
                    _ => return None,
                };
                if name != expected {
                    return None;
                }
                html_children.push(name);
            }
            let ordinal = if parent.is_some() {
                let parent = stack.last_mut()?;
                parent.child_count = parent.child_count.checked_add(1)?;
                parent.child_count
            } else {
                1
            };
            let id = tree.nodes.len();
            let depth = u32::try_from(stack.len()).ok()?.checked_add(1)?;
            tree.nodes.push(TreeTextNode {
                parent: parent
                    .map(u32::try_from)
                    .transpose()
                    .ok()?
                    .unwrap_or(u32::MAX),
                ordinal,
                depth,
            });
            maximum_depth = maximum_depth.max(depth);
            retained_nodes = retained_nodes.checked_add(1)?;
            if !is_void_html_tag(name) {
                stack.push(TreeTextOpenElement {
                    id,
                    name,
                    child_count: 0,
                });
                repair_state.opened(name);
            }
            if retained_nodes > budget.max_nodes()
                || stack.len() > usize::try_from(budget.max_depth()).ok()?
            {
                return None;
            }
        }
        cursor = end.checked_add(1)?;
    }
    if retained_nodes > budget.max_nodes() || !stack.is_empty() || tree.nodes.is_empty() {
        return None;
    }
    if !root_opened
        || tree
            .nodes
            .first()
            .is_none_or(|node| node.parent().is_some())
    {
        return None;
    }
    if html_children != [HEAD, BODY] {
        return None;
    }
    let maximum_occurrences = maximum_match_occurrences(
        normalized_text.len(),
        plan.needle.len(),
        plan.minimum_match_shift,
    )?;
    let fast_budget_is_safe = maximum_tree_text_visit_upper_bound(
        plan.needle.len(),
        normalized_text.len(),
        tree.nodes.len(),
        maximum_depth,
        text_segments.len(),
        plan.minimum_match_shift,
    )? <= budget.max_selector_visits()
        && maximum_occurrences <= budget.max_matches();
    let (selected, seeds) = if fast_budget_is_safe {
        let fast = fast_tree_text_selection(
            &tree.nodes,
            &normalized_text,
            &text_segments,
            &plan.finder,
            plan.needle.len(),
        )?;
        (fast.selected, Some(fast.seeds))
    } else {
        tree.finish_children()?;
        let expanded_segments = text_segments
            .iter()
            .copied()
            .map(CompactTextSegment::expanded)
            .collect::<Option<Vec<_>>>()?;
        let mut selector_budget = SelectorVisitBudget::new(budget.max_selector_visits());
        let selected = match select_tree_text(
            &tree,
            &normalized_text,
            &expanded_segments,
            &plan.needle,
            None,
            budget.max_matches(),
            &mut selector_budget,
        ) {
            Ok(matches) => matches,
            Err(failure) => return Some(LocateOutcome::Failed { failure }),
        };
        (selected, None)
    };
    let selected_count = u64::try_from(selected.len()).ok()?;
    if selected_count > budget.max_matches() {
        return Some(LocateOutcome::Failed {
            failure: limit_failure(
                ResourceLimit::Matches,
                budget.max_matches(),
                budget.max_matches().saturating_add(1),
            ),
        });
    }
    let text_ranges = if plan.node_projection {
        None
    } else {
        Some(match seeds.as_deref() {
            Some(seeds) => {
                selected_tree_text_ranges(&selected, &tree.nodes, &text_segments, seeds)?
            }
            None => selected_tree_text_ranges_full(&selected, &tree.nodes, &text_segments)?,
        })
    };
    let mut matches = Vec::with_capacity(selected.len());
    let mut output_bytes = 0_u64;
    for (selection_index, index) in selected.into_iter().enumerate() {
        let coordinate = tree_text_coordinate(index, &tree.nodes)?;
        if !plan.node_projection {
            let text = text_ranges
                .as_ref()?
                .get(selection_index)
                .copied()
                .flatten()
                .and_then(|(start, end)| normalized_text.get(start..end))
                .unwrap_or("")
                .trim_matches(' ');
            let added = stream_text_finding_bytes(document, output_name, &coordinate, text.len())?;
            let observed = output_bytes.checked_add(added)?;
            if observed > budget.max_output_bytes() {
                return Some(LocateOutcome::Failed {
                    failure: limit_failure(
                        ResourceLimit::OutputBytes,
                        budget.max_output_bytes(),
                        observed,
                    ),
                });
            }
            output_bytes = observed;
            matches.push(StreamMatch {
                coordinate,
                value: StreamValue::Text {
                    value: text.to_owned(),
                    previous_was_space: false,
                },
            });
            continue;
        }
        let value = StreamValue::Node;
        let added = stream_finding_bytes(document, output_name, &coordinate, &value)?;
        let observed = output_bytes.checked_add(added)?;
        if observed > budget.max_output_bytes() {
            return Some(LocateOutcome::Failed {
                failure: limit_failure(
                    ResourceLimit::OutputBytes,
                    budget.max_output_bytes(),
                    observed,
                ),
            });
        }
        output_bytes = observed;
        matches.push(StreamMatch { coordinate, value });
    }
    materialize(document, output_name, output_id, matches, budget)
}
