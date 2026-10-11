use std::collections::{HashMap, HashSet};

use crate::internal::documents::{Document, DocumentClass, DocumentEpoch, ResourceBudget};

use super::types::{
    ACCESSIBILITY_SCHEMA_V1, AccessibilityNode, AccessibilityParseError, AccessibilityTreeWire,
    MAX_ACCESSIBILITY_NODES, ParsedAccessibilityDocument,
};

impl ParsedAccessibilityDocument {
    /// Parses one static accessibility-tree v1 payload under the supplied limits.
    #[allow(clippy::manual_let_else)] // Graph invariants map to distinct typed errors.
    pub fn parse(
        document: &Document,
        limits: ResourceBudget,
    ) -> Result<Self, AccessibilityParseError> {
        if document.class() != DocumentClass::AccessibilityTree {
            return Err(AccessibilityParseError::UnsupportedDocument {
                document: document.class(),
            });
        }
        if document.byte_len() > limits.max_input_bytes() {
            return Err(AccessibilityParseError::InputLimitExceeded {
                maximum: limits.max_input_bytes(),
                observed: document.byte_len(),
            });
        }

        let wire: AccessibilityTreeWire = serde_json::from_slice(document.bytes())
            .map_err(|_| AccessibilityParseError::InvalidJson)?;
        if wire.schema != ACCESSIBILITY_SCHEMA_V1 {
            return Err(AccessibilityParseError::UnsupportedSchema);
        }
        let document_epoch = DocumentEpoch::try_from(wire.document_epoch)
            .map_err(|_| AccessibilityParseError::InvalidEpoch)?;
        if document.profile().epoch() != Some(document_epoch) {
            return Err(AccessibilityParseError::EpochMismatch);
        }
        let observed_nodes = u64::try_from(wire.nodes.len())
            .map_err(|_| AccessibilityParseError::QuantityOverflow)?;
        let maximum_nodes = limits.max_nodes().min(MAX_ACCESSIBILITY_NODES);
        if observed_nodes > maximum_nodes {
            return Err(AccessibilityParseError::NodeCountLimitExceeded {
                maximum: maximum_nodes,
                observed: observed_nodes,
            });
        }
        wire.completeness.validate()?;
        if wire.root.trim().is_empty() {
            return Err(AccessibilityParseError::EmptyRootId);
        }

        let mut nodes = Vec::with_capacity(wire.nodes.len());
        for node in wire.nodes {
            if node.id.trim().is_empty() || node.role.trim().is_empty() {
                return Err(AccessibilityParseError::EmptyNodeIdentity);
            }
            nodes.push(AccessibilityNode {
                id: node.id,
                parent: node.parent,
                children: node.children,
                ignored: node.ignored,
                role: node.role,
                accessible_name: node.accessible_name,
                text: node.text,
                states: node.states,
            });
        }

        let mut node_indexes = HashMap::with_capacity(nodes.len());
        for (index, node) in nodes.iter().enumerate() {
            if node_indexes.insert(node.id.clone(), index).is_some() {
                return Err(AccessibilityParseError::DuplicateNodeId);
            }
        }
        let root_index = match node_indexes.get(&wire.root).copied() {
            Some(index) => index,
            None => return Err(AccessibilityParseError::MissingRoot),
        };
        let root_node = nodes
            .get(root_index)
            .ok_or(AccessibilityParseError::MissingRoot)?;
        if root_node.parent.is_some() {
            return Err(AccessibilityParseError::RootHasParent);
        }

        validate_relations(&nodes, &node_indexes, root_index)?;
        validate_cycles(&nodes, &node_indexes)?;
        let (tree_order, max_depth) = tree_order(&nodes, &node_indexes, root_index, limits)?;

        Ok(Self {
            document_id: document.id().clone(),
            document_epoch,
            input_bytes: document.byte_len(),
            node_count: observed_nodes,
            completeness: wire.completeness,
            nodes,
            tree_order,
            max_depth,
        })
    }

    pub const fn document_epoch(&self) -> DocumentEpoch {
        self.document_epoch
    }

    pub const fn completeness(&self) -> &super::types::AccessibilityCompleteness {
        &self.completeness
    }

    pub const fn node_count(&self) -> usize {
        self.nodes.len()
    }

    pub const fn max_depth(&self) -> u32 {
        self.max_depth
    }
}

#[allow(clippy::manual_let_else)] // Missing relations map to distinct typed errors.
fn validate_relations(
    nodes: &[AccessibilityNode],
    indexes: &HashMap<String, usize>,
    root_index: usize,
) -> Result<(), AccessibilityParseError> {
    let mut child_reference_counts = vec![0_u32; nodes.len()];
    for node in nodes {
        let mut seen_children = HashSet::with_capacity(node.children.len());
        for child_id in &node.children {
            if !seen_children.insert(child_id.as_str()) {
                return Err(AccessibilityParseError::DuplicateChild);
            }
            let child_index = match indexes.get(child_id).copied() {
                Some(index) => index,
                None => return Err(AccessibilityParseError::MissingChild),
            };
            let child = nodes
                .get(child_index)
                .ok_or(AccessibilityParseError::MissingChild)?;
            if child.parent.as_deref() != Some(node.id.as_str()) {
                return Err(AccessibilityParseError::ParentChildMismatch);
            }
            let count = child_reference_counts
                .get_mut(child_index)
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
            *count = count
                .checked_add(1)
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
        }
    }

    for (node_index, node) in nodes.iter().enumerate() {
        let incoming_references = child_reference_counts
            .get(node_index)
            .copied()
            .ok_or(AccessibilityParseError::QuantityOverflow)?;
        if node_index == root_index {
            if incoming_references != 0 {
                return Err(AccessibilityParseError::ParentChildMismatch);
            }
            continue;
        }
        let Some(parent_id) = node.parent.as_deref() else {
            return Err(AccessibilityParseError::MissingParent);
        };
        if !indexes.contains_key(parent_id) {
            return Err(AccessibilityParseError::MissingParent);
        }
        if incoming_references != 1 {
            return Err(AccessibilityParseError::ParentChildMismatch);
        }
    }
    Ok(())
}

fn validate_cycles(
    nodes: &[AccessibilityNode],
    indexes: &HashMap<String, usize>,
) -> Result<(), AccessibilityParseError> {
    let mut visit_state = vec![0_u8; nodes.len()];
    for (start, _) in nodes.iter().enumerate() {
        let start_state = visit_state
            .get(start)
            .copied()
            .ok_or(AccessibilityParseError::QuantityOverflow)?;
        if start_state == 2 {
            continue;
        }
        let mut trail = Vec::new();
        let mut current = Some(start);
        while let Some(node_index) = current {
            let state = visit_state
                .get(node_index)
                .copied()
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
            if state == 1 {
                return Err(AccessibilityParseError::Cycle);
            }
            if state == 2 {
                break;
            }
            let node = nodes
                .get(node_index)
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
            let marker = visit_state
                .get_mut(node_index)
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
            *marker = 1;
            trail.push(node_index);
            current = match node.parent.as_deref() {
                Some(parent_id) => Some(
                    indexes
                        .get(parent_id)
                        .copied()
                        .ok_or(AccessibilityParseError::MissingParent)?,
                ),
                None => None,
            };
        }
        for node_index in trail {
            let marker = visit_state
                .get_mut(node_index)
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
            *marker = 2;
        }
    }
    Ok(())
}

fn tree_order(
    nodes: &[AccessibilityNode],
    indexes: &HashMap<String, usize>,
    root_index: usize,
    limits: ResourceBudget,
) -> Result<(Vec<usize>, u32), AccessibilityParseError> {
    let mut pending = vec![(root_index, 1_u32)];
    let mut visited = HashSet::with_capacity(nodes.len());
    let mut ordered = Vec::with_capacity(nodes.len());
    let mut maximum_depth = 0_u32;
    while let Some((node_index, depth)) = pending.pop() {
        if depth > limits.max_depth() {
            return Err(AccessibilityParseError::DepthLimitExceeded {
                maximum: limits.max_depth(),
                observed: depth,
            });
        }
        if !visited.insert(node_index) {
            return Err(AccessibilityParseError::Cycle);
        }
        maximum_depth = maximum_depth.max(depth);
        ordered.push(node_index);
        let node = nodes
            .get(node_index)
            .ok_or(AccessibilityParseError::QuantityOverflow)?;
        for child_id in node.children.iter().rev() {
            let child_index = indexes
                .get(child_id)
                .copied()
                .ok_or(AccessibilityParseError::MissingChild)?;
            let child_depth = depth
                .checked_add(1)
                .ok_or(AccessibilityParseError::QuantityOverflow)?;
            pending.push((child_index, child_depth));
        }
    }
    if ordered.len() != nodes.len() {
        return Err(AccessibilityParseError::UnreachableNode);
    }
    Ok((ordered, maximum_depth))
}
