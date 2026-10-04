use super::super::names::{HEAD, HTML};
use super::super::support::{TreeCoordinate, memmem};
use super::{CompactTextSegment, TreeTextNode, TreeTextOpenElement};

pub(super) struct FastTreeTextSelection {
    pub(super) selected: Vec<usize>,
    pub(super) seeds: Vec<(usize, usize, usize)>,
}

pub(super) fn maximum_tree_text_visit_upper_bound(
    needle_len: usize,
    text_len: usize,
    node_count: usize,
    maximum_depth: u32,
    segment_count: usize,
    minimum_match_shift: usize,
) -> Option<u64> {
    let node_count = u64::try_from(node_count).ok()?;
    let edge_count = node_count.saturating_sub(1);
    let needle_len = u64::try_from(needle_len).ok()?;
    let text_len = u64::try_from(text_len).ok()?;
    let maximum_depth = u64::from(maximum_depth);
    let segment_count = u64::try_from(segment_count).ok()?;
    let maximum_occurrences = maximum_match_occurrences(
        usize::try_from(text_len).ok()?,
        usize::try_from(needle_len).ok()?,
        minimum_match_shift,
    )?;
    node_count
        .checked_mul(3)?
        .checked_add(edge_count.checked_mul(2)?)?
        .checked_add(needle_len.checked_mul(3)?)?
        .checked_add(1)?
        .checked_add(text_len.checked_mul(2)?)?
        .checked_add(maximum_occurrences.checked_mul(2)?)?
        .checked_add(segment_count.checked_mul(2)?)?
        .checked_add(
            maximum_occurrences.checked_mul(maximum_depth.checked_add(1)?.checked_mul(2)?)?,
        )
}

pub(super) fn maximum_match_occurrences(
    text_len: usize,
    needle_len: usize,
    minimum_match_shift: usize,
) -> Option<u64> {
    if text_len < needle_len {
        return Some(0);
    }
    u64::try_from(
        text_len
            .checked_sub(needle_len)?
            .checked_div(minimum_match_shift)?
            .checked_add(1)?,
    )
    .ok()
}

pub(super) fn fast_tree_text_selection(
    nodes: &[TreeTextNode],
    normalized: &str,
    segments: &[CompactTextSegment],
    finder: &memmem::Finder<'_>,
    needle_len: usize,
) -> Option<FastTreeTextSelection> {
    if needle_len == 0 {
        return None;
    }
    let mut start_segment = 0_usize;
    let mut end_segment = 0_usize;
    let mut search_from = 0_usize;
    let mut previous_owners = None;
    let mut seeds = Vec::new();
    let mut direct_hits = Vec::new();
    while let Some(relative) = finder.find(normalized.as_bytes().get(search_from..)?) {
        let start = search_from.checked_add(relative)?;
        let end = start.checked_add(needle_len)?;
        let start_owner = fast_text_owner_at(segments, start, &mut start_segment)?;
        let end_owner = fast_text_owner_at(segments, end.checked_sub(1)?, &mut end_segment)?;
        let owners = (start_owner, end_owner);
        if previous_owners != Some(owners) {
            previous_owners = Some(owners);
            let common = fast_lowest_common_ancestor(nodes, start_owner, end_owner)?;
            direct_hits.push(common);
            seeds.push((common, start_segment, end_segment));
        }
        search_from = start.checked_add(1)?;
    }
    direct_hits.sort_unstable();
    direct_hits.dedup();
    seeds.sort_unstable_by_key(|(node, _, _)| *node);
    seeds.dedup_by_key(|(node, _, _)| *node);
    let mut selected = Vec::with_capacity(direct_hits.len());
    for (position, hit) in direct_hits.iter().copied().enumerate() {
        let shadowed = match direct_hits.get(position.checked_add(1)?).copied() {
            Some(next) => fast_is_ancestor(nodes, hit, next)?,
            None => false,
        };
        if !shadowed {
            selected.push(hit);
        }
    }
    Some(FastTreeTextSelection { selected, seeds })
}

fn fast_text_owner_at(
    segments: &[CompactTextSegment],
    position: usize,
    cursor: &mut usize,
) -> Option<usize> {
    while segments
        .get(*cursor)
        .is_some_and(|segment| usize::try_from(segment.end).is_ok_and(|end| end <= position))
    {
        *cursor = cursor.checked_add(1)?;
    }
    segments
        .get(*cursor)
        .filter(|segment| {
            let start = usize::try_from(segment.start).ok();
            let end = usize::try_from(segment.end).ok();
            start.is_some_and(|start| start <= position) && end.is_some_and(|end| position < end)
        })
        .and_then(|segment| usize::try_from(segment.owner).ok())
}

fn fast_lowest_common_ancestor(
    nodes: &[TreeTextNode],
    mut left: usize,
    mut right: usize,
) -> Option<usize> {
    while nodes.get(left)?.depth > nodes.get(right)?.depth {
        left = nodes.get(left)?.parent()?;
    }
    while nodes.get(right)?.depth > nodes.get(left)?.depth {
        right = nodes.get(right)?.parent()?;
    }
    while left != right {
        left = nodes.get(left)?.parent()?;
        right = nodes.get(right)?.parent()?;
    }
    Some(left)
}

fn fast_is_ancestor(nodes: &[TreeTextNode], ancestor: usize, mut candidate: usize) -> Option<bool> {
    let ancestor_depth = nodes.get(ancestor)?.depth;
    while nodes.get(candidate)?.depth > ancestor_depth {
        candidate = nodes.get(candidate)?.parent()?;
    }
    Some(candidate == ancestor)
}

pub(super) fn tree_text_push(
    value: &str,
    stack: &[TreeTextOpenElement],
    nodes: &[TreeTextNode],
    normalized: &mut String,
    segments: &mut Vec<CompactTextSegment>,
    previous_space: &mut bool,
) -> Option<()> {
    if value.is_empty() {
        return Some(());
    }
    let open = stack.last()?;
    let owner = open.id;
    let owner_name = open.name;
    if matches!(owner_name, HTML | HEAD) || nodes.get(owner).is_none() {
        return None;
    }
    let start = normalized.len();
    append_tree_text(value, normalized, previous_space)?;
    let end = normalized.len();
    if end > start {
        segments.push(CompactTextSegment {
            start: u32::try_from(start).ok()?,
            end: u32::try_from(end).ok()?,
            owner: u32::try_from(owner).ok()?,
        });
    }
    Some(())
}

fn append_tree_text(source: &str, target: &mut String, previous_space: &mut bool) -> Option<()> {
    let bytes = source.as_bytes();
    let mut cursor = 0_usize;
    while cursor < bytes.len() {
        if bytes.get(cursor)?.is_ascii_whitespace() {
            if !*previous_space {
                target.push(' ');
            }
            *previous_space = true;
            cursor = cursor.checked_add(1)?;
            continue;
        }
        let span = bytes.get(cursor..)?;
        let length = span
            .iter()
            .position(u8::is_ascii_whitespace)
            .unwrap_or(span.len());
        let end = cursor.checked_add(length)?;
        target.push_str(source.get(cursor..end)?);
        *previous_space = false;
        cursor = end;
    }
    Some(())
}

pub(super) fn selected_tree_text_ranges(
    selected: &[usize],
    nodes: &[TreeTextNode],
    segments: &[CompactTextSegment],
    seeds: &[(usize, usize, usize)],
) -> Option<Vec<Option<(usize, usize)>>> {
    let mut intervals = Vec::with_capacity(selected.len());
    let mut scan = 0_usize;
    for start in selected.iter().copied() {
        let depth = nodes.get(start)?.depth;
        scan = scan.max(start.checked_add(1)?);
        while nodes.get(scan).is_some_and(|node| node.depth > depth) {
            scan = scan.checked_add(1)?;
        }
        intervals.push(start..scan);
    }
    let mut ranges = Vec::with_capacity(selected.len());
    for (selection, interval) in selected.iter().zip(&intervals) {
        let seed_index = seeds
            .binary_search_by_key(selection, |(node, _, _)| *node)
            .ok()?;
        let (_, mut first, mut last) = *seeds.get(seed_index)?;
        while let Some(previous) = first.checked_sub(1) {
            let owner = usize::try_from(segments.get(previous)?.owner).ok()?;
            if !interval.contains(&owner) {
                break;
            }
            first = previous;
        }
        while let Some(next) = last.checked_add(1) {
            let Some(segment) = segments.get(next) else {
                break;
            };
            let owner = usize::try_from(segment.owner).ok()?;
            if !interval.contains(&owner) {
                break;
            }
            last = next;
        }
        ranges.push(Some((
            usize::try_from(segments.get(first)?.start).ok()?,
            usize::try_from(segments.get(last)?.end).ok()?,
        )));
    }
    Some(ranges)
}

pub(super) fn selected_tree_text_ranges_full(
    selected: &[usize],
    nodes: &[TreeTextNode],
    segments: &[CompactTextSegment],
) -> Option<Vec<Option<(usize, usize)>>> {
    let mut intervals = Vec::with_capacity(selected.len());
    let mut scan = 0_usize;
    for start in selected.iter().copied() {
        let depth = nodes.get(start)?.depth;
        scan = scan.max(start.checked_add(1)?);
        while nodes.get(scan).is_some_and(|node| node.depth > depth) {
            scan = scan.checked_add(1)?;
        }
        intervals.push(start..scan);
    }
    let mut ranges = vec![None::<(usize, usize)>; selected.len()];
    for segment in segments {
        let owner = usize::try_from(segment.owner).ok()?;
        let insertion = intervals.partition_point(|interval| interval.start <= owner);
        let Some(interval_index) = insertion.checked_sub(1) else {
            continue;
        };
        if intervals.get(interval_index)?.contains(&owner) {
            let value = (
                usize::try_from(segment.start).ok()?,
                usize::try_from(segment.end).ok()?,
            );
            let target = ranges.get_mut(interval_index)?;
            *target = Some(match *target {
                Some((start, end)) => (start.min(value.0), end.max(value.1)),
                None => value,
            });
        }
    }
    Some(ranges)
}

pub(super) fn tree_text_coordinate(index: usize, nodes: &[TreeTextNode]) -> Option<TreeCoordinate> {
    let mut path = Vec::new();
    let mut current = Some(index);
    while let Some(index) = current {
        let node = nodes.get(index)?;
        path.push(node.ordinal);
        current = node.parent();
    }
    path.reverse();
    TreeCoordinate::try_new(path, None).ok()
}
