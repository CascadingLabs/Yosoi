use super::scanner::{StreamMatch, StreamValue};
use super::support::{
    Completeness, Document, Finding, LocateOutcome, LocateResult, NativeCoordinate, NodeReference,
    ProjectedValue, ResourceBudget, ResourceLimit, TreeCoordinate, limit_failure,
    tree_coordinate_bytes,
};

pub(super) fn materialize(
    document: &Document,
    output_name: &str,
    output_id: &crate::OutputId,
    matches: Vec<StreamMatch>,
    budget: ResourceBudget,
) -> Option<LocateOutcome> {
    let match_count = u64::try_from(matches.len()).ok()?;
    if match_count > budget.max_matches() {
        return Some(LocateOutcome::Failed {
            failure: limit_failure(
                ResourceLimit::Matches,
                budget.max_matches(),
                budget.max_matches().saturating_add(1),
            ),
        });
    }
    if matches.is_empty() {
        return Some(LocateOutcome::NoMatch {
            document_id: document.id().clone(),
        });
    }
    let mut findings = Vec::with_capacity(matches.len());
    let mut output_bytes = 0_u64;
    for (order, found) in matches.into_iter().enumerate() {
        let coordinate = found.coordinate;
        let value = match found.value {
            StreamValue::Text { value, .. } => {
                if value.starts_with(' ') || value.ends_with(' ') {
                    ProjectedValue::Text(value.trim_matches(' ').to_owned())
                } else {
                    ProjectedValue::Text(value)
                }
            }
            StreamValue::Attribute { name, value } => ProjectedValue::Attribute { name, value },
            StreamValue::Node => ProjectedValue::Node(NodeReference::new(
                document.id().clone(),
                NativeCoordinate::SourceTree(coordinate.clone()),
            )),
        };
        let added = finding_bytes(document, output_name, &coordinate, &value)?;
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
        findings.push(
            Finding::try_new(
                document.id().clone(),
                output_id.clone(),
                u64::try_from(order).ok()?,
                NativeCoordinate::SourceTree(coordinate),
                value,
                Completeness::Complete,
                None,
            )
            .ok()?,
        );
        output_bytes = observed;
    }
    Some(LocateOutcome::Matched {
        result: LocateResult::try_new(document.id().clone(), findings).ok()?,
    })
}

pub(super) fn stream_finding_bytes(
    document: &Document,
    output_id: &str,
    coordinate: &TreeCoordinate,
    value: &StreamValue,
) -> Option<u64> {
    let mut bytes = u64::try_from(document.id().as_str().len()).ok()?;
    bytes = bytes.checked_add(u64::try_from(output_id.len()).ok()?)?;
    let coordinate_bytes = tree_coordinate_bytes(coordinate)?;
    bytes = bytes.checked_add(coordinate_bytes)?;
    let value_bytes = match value {
        StreamValue::Text { value, .. } => u64::try_from(value.trim_matches(' ').len()).ok()?,
        StreamValue::Attribute { name, value } => u64::try_from(name.len())
            .ok()?
            .checked_add(u64::try_from(value.len()).ok()?)?,
        StreamValue::Node => u64::try_from(document.id().as_str().len())
            .ok()?
            .checked_add(coordinate_bytes)?,
    };
    bytes.checked_add(value_bytes)
}

pub(super) fn stream_text_finding_bytes(
    document: &Document,
    output_id: &str,
    coordinate: &TreeCoordinate,
    text_bytes: usize,
) -> Option<u64> {
    u64::try_from(document.id().as_str().len())
        .ok()?
        .checked_add(u64::try_from(output_id.len()).ok()?)?
        .checked_add(tree_coordinate_bytes(coordinate)?)?
        .checked_add(u64::try_from(text_bytes).ok()?)
}
fn finding_bytes(
    document: &Document,
    output_id: &str,
    coordinate: &TreeCoordinate,
    value: &ProjectedValue,
) -> Option<u64> {
    let mut bytes = u64::try_from(document.id().as_str().len()).ok()?;
    bytes = bytes.checked_add(u64::try_from(output_id.len()).ok()?)?;
    bytes = bytes.checked_add(tree_coordinate_bytes(coordinate)?)?;
    let value_bytes = match value {
        ProjectedValue::Text(value) => u64::try_from(value.len()).ok()?,
        ProjectedValue::Attribute { name, value } => u64::try_from(name.len())
            .ok()?
            .checked_add(u64::try_from(value.len()).ok()?)?,
        ProjectedValue::Node(_) => u64::try_from(document.id().as_str().len())
            .ok()?
            .checked_add(tree_coordinate_bytes(coordinate)?)?,
        ProjectedValue::TextWithCaptures { .. } | ProjectedValue::Json(_) => return None,
    };
    bytes.checked_add(value_bytes)
}
