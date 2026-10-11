//! Projection from retained Chromium accessibility JSON into the portable
//! Yosoi accessibility-tree document schema.
use crate::internal::web_capture as yosoi_web_capture;

mod output;
use output::BoundedOutput;

use std::{
    collections::{HashMap, HashSet},
    mem,
};

use crate::internal::documents::{AccessibilityCompleteness, DocumentEpoch, ResourceBudget};
use crate::internal::types::LossExtent;
use thiserror::Error;

use crate::internal::engine::Document;
use crate::internal::web_capture::BrowserAccessibilityEvidence;

#[path = "accessibility_wire.rs"]
mod accessibility_wire;
use accessibility_wire::{
    AccessibilityNodeWire, AccessibilityTreeWire, CdpAxNode, deduplicate_exact_nodes,
    normalize_node,
};

const CDP_AX_SCHEMA_VERSION: u32 = 1;

/// A safe, payload-free accessibility normalization failure.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum AccessibilityNormalizationError {
    #[error("browser accessibility evidence uses an unsupported schema")]
    UnsupportedSchema,
    #[error("browser accessibility evidence has an unsupported schema version")]
    UnsupportedSchemaVersion,
    #[error("browser accessibility evidence has an unsupported ignored-node policy")]
    UnsupportedIgnoredNodePolicy,
    #[error("browser accessibility evidence has invalid capture metadata")]
    InvalidCaptureMetadata,
    #[error("browser accessibility document epoch must be greater than zero")]
    InvalidEpoch,
    #[error("browser accessibility node accounting is inconsistent")]
    InconsistentNodeAccounting,
    #[error("browser accessibility byte accounting is inconsistent")]
    InconsistentByteAccounting,
    #[error("browser accessibility input exceeds its byte budget")]
    InputLimitExceeded,
    #[error("browser accessibility input exceeds its node budget")]
    NodeLimitExceeded,
    #[error("browser accessibility payload is not a supported CDP AX node array")]
    InvalidCdpPayload,
    #[error("browser accessibility node has no public role")]
    MissingRole,
    #[error("browser accessibility node has an invalid public role value")]
    InvalidRole,
    #[error("browser accessibility node has an invalid accessible-name value")]
    InvalidName,
    #[error("browser accessibility node has an invalid supported state value")]
    InvalidState,
    #[error("browser accessibility payload contains an invalid tree graph")]
    InvalidTreeGraph,
    #[error("browser accessibility output exceeds its byte budget")]
    OutputLimitExceeded,
    #[error("browser accessibility output could not be represented as a validated document")]
    InvalidNormalizedDocument,
    #[error("browser accessibility quantity exceeds its integer representation")]
    QuantityOverflow,
}

/// Converts owned v1 Chromium AX node JSON into a bounded, validated document.
///
/// Provider-only fields are ignored. The public role and computed name are
/// copied only from their exact CDP fields; control values are never projected
/// as text.
pub fn normalize_accessibility(
    id: impl Into<String>,
    evidence: BrowserAccessibilityEvidence,
    budget: ResourceBudget,
) -> Result<Document, AccessibilityNormalizationError> {
    validate_evidence(&evidence)?;

    let input_len = u64::try_from(evidence.canonical_node_bytes.len())
        .map_err(|_| AccessibilityNormalizationError::QuantityOverflow)?;
    if input_len > budget.max_input_bytes() {
        return Err(AccessibilityNormalizationError::InputLimitExceeded);
    }

    let expected_nodes_retained = evidence.nodes_retained;
    let epoch_value = evidence.scope.epoch.0;
    let completeness = initial_completeness(&evidence);
    let canonical_node_bytes = evidence.canonical_node_bytes;
    let raw_nodes: Vec<CdpAxNode> = serde_json::from_slice(&canonical_node_bytes)
        .map_err(|_| AccessibilityNormalizationError::InvalidCdpPayload)?;
    let raw_count = u64::try_from(raw_nodes.len())
        .map_err(|_| AccessibilityNormalizationError::QuantityOverflow)?;
    if raw_count != expected_nodes_retained {
        return Err(AccessibilityNormalizationError::InconsistentNodeAccounting);
    }
    let raw_nodes = deduplicate_exact_nodes(raw_nodes)?;
    let unique_count = u64::try_from(raw_nodes.len())
        .map_err(|_| AccessibilityNormalizationError::QuantityOverflow)?;
    if unique_count > budget.max_nodes() {
        return Err(AccessibilityNormalizationError::NodeLimitExceeded);
    }

    let epoch = DocumentEpoch::try_from(epoch_value)
        .map_err(|_| AccessibilityNormalizationError::InvalidEpoch)?;
    let nodes = raw_nodes
        .into_iter()
        .map(normalize_node)
        .collect::<Result<Vec<_>, _>>()?;
    let (root, nodes, completeness) = close_graph(nodes, completeness)?;

    let wire = AccessibilityTreeWire {
        schema: "yosoi.accessibility-tree.v1",
        document_epoch: epoch.get(),
        root,
        completeness,
        nodes,
    };
    let mut writer = BoundedOutput::new(budget.max_output_bytes());
    let serialization = serde_json::to_writer(&mut writer, &wire);
    if writer.exceeded_limit {
        return Err(AccessibilityNormalizationError::OutputLimitExceeded);
    }
    if writer.capacity_failed {
        return Err(AccessibilityNormalizationError::InvalidNormalizedDocument);
    }
    serialization.map_err(|_| AccessibilityNormalizationError::InvalidNormalizedDocument)?;
    let bytes = writer.into_inner();

    let document = Document::accessibility_tree(id, epoch, bytes)
        .map_err(|_| AccessibilityNormalizationError::InvalidNormalizedDocument)?;
    document
        .parse_with_budget(budget)
        .map_err(|_| AccessibilityNormalizationError::InvalidNormalizedDocument)?;
    Ok(document)
}

fn validate_evidence(
    evidence: &BrowserAccessibilityEvidence,
) -> Result<(), AccessibilityNormalizationError> {
    if evidence.schema != yosoi_web_capture::BrowserAccessibilitySchema::ChromiumCdpAxNodeJson {
        return Err(AccessibilityNormalizationError::UnsupportedSchema);
    }
    if evidence.schema_version != CDP_AX_SCHEMA_VERSION {
        return Err(AccessibilityNormalizationError::UnsupportedSchemaVersion);
    }
    if evidence.ignored_nodes != yosoi_web_capture::BrowserAccessibilityIgnoredNodes::Included {
        return Err(AccessibilityNormalizationError::UnsupportedIgnoredNodePolicy);
    }
    if evidence.scope.epoch.0 == 0 {
        return Err(AccessibilityNormalizationError::InvalidEpoch);
    }
    let capture_metadata_invalid = match evidence.capture_mode {
        yosoi_web_capture::BrowserAccessibilityCaptureMode::FullTree => {
            evidence.requested_depth.is_some()
        }
        yosoi_web_capture::BrowserAccessibilityCaptureMode::DepthLimited => {
            evidence.requested_depth.is_none_or(|depth| depth < 0)
        }
    };
    if capture_metadata_invalid {
        return Err(AccessibilityNormalizationError::InvalidCaptureMetadata);
    }

    if evidence.nodes_retained > evidence.nodes_observed {
        return Err(AccessibilityNormalizationError::InconsistentNodeAccounting);
    }
    match evidence.nodes_lost {
        LossExtent::Known(lost) => {
            if evidence
                .nodes_retained
                .checked_add(lost)
                .is_none_or(|total| total != evidence.nodes_observed)
            {
                return Err(AccessibilityNormalizationError::InconsistentNodeAccounting);
            }
        }
        LossExtent::Unknown => {}
    }

    let retained_bytes = u64::try_from(evidence.canonical_node_bytes.len())
        .map_err(|_| AccessibilityNormalizationError::QuantityOverflow)?;
    if retained_bytes != evidence.bytes.retained
        || retained_bytes > evidence.bytes.configured_limit
        || evidence.bytes.retained > evidence.bytes.observed
    {
        return Err(AccessibilityNormalizationError::InconsistentByteAccounting);
    }
    match evidence.bytes.lost {
        LossExtent::Known(lost) => {
            if evidence
                .bytes
                .retained
                .checked_add(lost)
                .is_none_or(|total| total != evidence.bytes.observed)
                || evidence.bytes.complete != (lost == 0)
            {
                return Err(AccessibilityNormalizationError::InconsistentByteAccounting);
            }
        }
        LossExtent::Unknown if evidence.bytes.complete => {
            return Err(AccessibilityNormalizationError::InconsistentByteAccounting);
        }
        LossExtent::Unknown => {}
    }
    Ok(())
}

fn initial_completeness(evidence: &BrowserAccessibilityEvidence) -> AccessibilityCompleteness {
    if matches!(evidence.nodes_lost, LossExtent::Unknown) {
        return AccessibilityCompleteness::Unknown {
            reason_code: "browser_accessibility_node_loss_unknown".to_owned(),
        };
    }
    if matches!(evidence.bytes.lost, LossExtent::Unknown) {
        return AccessibilityCompleteness::Unknown {
            reason_code: "browser_accessibility_byte_loss_unknown".to_owned(),
        };
    }
    if evidence.capture_mode == yosoi_web_capture::BrowserAccessibilityCaptureMode::DepthLimited {
        return AccessibilityCompleteness::Partial {
            reason_code: "browser_accessibility_depth_limited".to_owned(),
            lost_items: None,
        };
    }
    if let LossExtent::Known(lost) = evidence.nodes_lost
        && lost > 0
    {
        return AccessibilityCompleteness::Partial {
            reason_code: "browser_accessibility_node_truncation".to_owned(),
            lost_items: Some(lost),
        };
    }
    if let LossExtent::Known(lost) = evidence.bytes.lost
        && lost > 0
    {
        return AccessibilityCompleteness::Partial {
            reason_code: "browser_accessibility_byte_truncation".to_owned(),
            lost_items: None,
        };
    }
    AccessibilityCompleteness::Complete
}

fn close_graph(
    mut nodes: Vec<AccessibilityNodeWire>,
    mut completeness: AccessibilityCompleteness,
) -> Result<
    (
        String,
        Vec<AccessibilityNodeWire>,
        AccessibilityCompleteness,
    ),
    AccessibilityNormalizationError,
> {
    let mut indexes = HashMap::with_capacity(nodes.len());
    for (index, node) in nodes.iter().enumerate() {
        if indexes.insert(node.id.clone(), index).is_some() {
            return Err(AccessibilityNormalizationError::InvalidTreeGraph);
        }
    }
    let mut root_index = None;
    for (index, node) in nodes.iter().enumerate() {
        if node.parent.is_none() && root_index.replace(index).is_some() {
            return Err(AccessibilityNormalizationError::InvalidTreeGraph);
        }
    }
    let root_index = root_index.ok_or(AccessibilityNormalizationError::InvalidTreeGraph)?;
    let incomplete = !matches!(&completeness, AccessibilityCompleteness::Complete);

    for node in &mut nodes {
        let mut seen_children = HashSet::with_capacity(node.children.len());
        if node
            .children
            .iter()
            .any(|child| !seen_children.insert(child.as_str()))
        {
            return Err(AccessibilityNormalizationError::InvalidTreeGraph);
        }
        let mut retained_children = Vec::with_capacity(node.children.len());
        for child in mem::take(&mut node.children) {
            match indexes.contains_key(child.as_str()) {
                true => retained_children.push(child),
                false if !incomplete => {
                    return Err(AccessibilityNormalizationError::InvalidTreeGraph);
                }
                false => {}
            }
        }
        node.children = retained_children;
    }

    let mut reachable = HashSet::with_capacity(nodes.len());
    let mut pending = vec![root_index];
    while let Some(index) = pending.pop() {
        if !reachable.insert(index) {
            continue;
        }
        let node = nodes
            .get(index)
            .ok_or(AccessibilityNormalizationError::InvalidTreeGraph)?;
        for child in &node.children {
            let child_index = indexes
                .get(child.as_str())
                .copied()
                .ok_or(AccessibilityNormalizationError::InvalidTreeGraph)?;
            pending.push(child_index);
        }
    }
    let unreachable_count = nodes
        .len()
        .checked_sub(reachable.len())
        .ok_or(AccessibilityNormalizationError::QuantityOverflow)?;
    if unreachable_count > 0 && !incomplete {
        return Err(AccessibilityNormalizationError::InvalidTreeGraph);
    }
    if unreachable_count > 0 {
        add_pruned_node_loss(&mut completeness, unreachable_count)?;
    }
    let root = nodes
        .get(root_index)
        .map(|node| node.id.clone())
        .ok_or(AccessibilityNormalizationError::InvalidTreeGraph)?;
    let mut retained = Vec::with_capacity(reachable.len());
    for (index, node) in nodes.into_iter().enumerate() {
        if reachable.contains(&index) {
            retained.push(node);
        }
    }
    Ok((root, retained, completeness))
}

fn add_pruned_node_loss(
    completeness: &mut AccessibilityCompleteness,
    unreachable_count: usize,
) -> Result<(), AccessibilityNormalizationError> {
    let additional = u64::try_from(unreachable_count)
        .map_err(|_| AccessibilityNormalizationError::QuantityOverflow)?;
    if let AccessibilityCompleteness::Partial { lost_items, .. } = completeness {
        let prior_loss = lost_items.unwrap_or(0);
        *lost_items = Some(
            prior_loss
                .checked_add(additional)
                .ok_or(AccessibilityNormalizationError::QuantityOverflow)?,
        );
    }
    Ok(())
}

#[cfg(test)]
#[path = "accessibility_tests.rs"]
mod tests;
