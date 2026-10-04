use std::collections::{HashMap, HashSet};

use crate::{DomNodeId, html::HTML_NAMESPACE};

use super::parsing::RenderedDomParseError;
use super::types::RENDERED_DOM_TREE_MODEL;
use super::wire::{WireDocument, WireNode};

pub(super) struct ValidatedTree {
    pub(super) node_order: Vec<usize>,
    pub(super) wire_index_by_id: HashMap<DomNodeId, usize>,
    pub(super) max_depth: u32,
}

pub(super) fn validate_wire_tree(
    wire: &WireDocument,
    maximum_nodes: u64,
    maximum_depth: u32,
) -> Result<ValidatedTree, RenderedDomParseError> {
    if wire.tree_model != RENDERED_DOM_TREE_MODEL {
        return Err(RenderedDomParseError::UnsupportedTreeModel);
    }
    let node_count =
        u64::try_from(wire.nodes.len()).map_err(|_| RenderedDomParseError::NodeCountOverflow)?;
    if node_count == 0 {
        return Err(RenderedDomParseError::InvalidRoot);
    }
    if node_count > maximum_nodes {
        return Err(RenderedDomParseError::NodeLimitExceeded {
            maximum: maximum_nodes,
            observed: node_count,
        });
    }

    let mut wire_index_by_id = HashMap::with_capacity(wire.nodes.len());
    for (index, node) in wire.nodes.iter().enumerate() {
        if wire_index_by_id.insert(node.id(), index).is_some() {
            return Err(RenderedDomParseError::DuplicateNodeId);
        }
        if !node.strings_are_valid() {
            return Err(RenderedDomParseError::InvalidString);
        }
        validate_attributes(node)?;
        if matches!(node, WireNode::Text { .. }) && !node.children().is_empty() {
            return Err(RenderedDomParseError::InvalidNode);
        }
    }

    let Some(root_index) = wire_index_by_id.get(&wire.root).copied() else {
        return Err(RenderedDomParseError::InvalidRoot);
    };
    let Some(root) = wire.nodes.get(root_index) else {
        return Err(RenderedDomParseError::InvalidRoot);
    };
    if !root.is_document() || root.parent().is_some() {
        return Err(RenderedDomParseError::InvalidRoot);
    }
    let [document_element_id] = root.children() else {
        return Err(RenderedDomParseError::InvalidDocumentRootChildren);
    };
    let Some(document_element_index) = wire_index_by_id.get(document_element_id).copied() else {
        return Err(RenderedDomParseError::UnknownNodeId);
    };
    let Some(document_element) = wire.nodes.get(document_element_index) else {
        return Err(RenderedDomParseError::UnknownNodeId);
    };
    if !matches!(document_element, WireNode::Element { .. }) {
        return Err(RenderedDomParseError::InvalidDocumentRootChildren);
    }

    let document_count = wire.nodes.iter().filter(|node| node.is_document()).count();
    if document_count != 1 {
        return Err(RenderedDomParseError::InvalidNode);
    }

    let mut incoming_parent = HashMap::<DomNodeId, DomNodeId>::with_capacity(wire.nodes.len());
    for node in &wire.nodes {
        let mut seen_children = HashSet::with_capacity(node.children().len());
        for child_id in node.children() {
            if !seen_children.insert(*child_id) {
                return Err(RenderedDomParseError::InvalidParentChild);
            }
            let Some(child_index) = wire_index_by_id.get(child_id).copied() else {
                return Err(RenderedDomParseError::UnknownNodeId);
            };
            let Some(child) = wire.nodes.get(child_index) else {
                return Err(RenderedDomParseError::UnknownNodeId);
            };
            if child.parent() != Some(node.id())
                || incoming_parent.insert(*child_id, node.id()).is_some()
            {
                return Err(RenderedDomParseError::InvalidParentChild);
            }
        }
    }

    for node in &wire.nodes {
        if node.id() == wire.root {
            if node.parent().is_some() || incoming_parent.contains_key(&node.id()) {
                return Err(RenderedDomParseError::InvalidParentChild);
            }
            continue;
        }
        let Some(parent_id) = node.parent() else {
            return Err(RenderedDomParseError::InvalidParentChild);
        };
        if !wire_index_by_id.contains_key(&parent_id)
            || incoming_parent.get(&node.id()).copied() != Some(parent_id)
            || node.is_document()
        {
            return Err(RenderedDomParseError::InvalidParentChild);
        }
    }

    reject_cycles(&wire.nodes, &wire_index_by_id)?;
    let (node_order, max_depth) =
        preorder(&wire.nodes, &wire_index_by_id, wire.root, maximum_depth)?;
    if node_order.len() != wire.nodes.len() {
        return Err(RenderedDomParseError::DisconnectedNodes);
    }

    Ok(ValidatedTree {
        node_order,
        wire_index_by_id,
        max_depth,
    })
}

fn validate_attributes(node: &WireNode) -> Result<(), RenderedDomParseError> {
    let WireNode::Element {
        namespace_uri,
        attributes,
        ..
    } = node
    else {
        return Ok(());
    };
    let is_html_element = namespace_uri == HTML_NAMESPACE;
    let mut seen = HashSet::with_capacity(attributes.len());
    let mut previous: Option<(&str, &str)> = None;
    for attribute in attributes {
        let sort_key = (attribute.namespace_uri.as_str(), attribute.name.as_str());
        if previous.is_some_and(|previous_key| previous_key >= sort_key) {
            return Err(RenderedDomParseError::InvalidAttributeOrder);
        }
        previous = Some(sort_key);

        let local_name = if is_html_element && attribute.namespace_uri.is_empty() {
            attribute.name.to_ascii_lowercase()
        } else {
            attribute.name.clone()
        };
        if !seen.insert((attribute.namespace_uri.clone(), local_name)) {
            return Err(RenderedDomParseError::DuplicateAttribute);
        }
    }
    Ok(())
}

fn reject_cycles(
    nodes: &[WireNode],
    wire_index_by_id: &HashMap<DomNodeId, usize>,
) -> Result<(), RenderedDomParseError> {
    let mut state = vec![0_u8; nodes.len()];
    for start in 0..nodes.len() {
        if state.get(start).copied() != Some(0) {
            continue;
        }
        let mut pending = vec![(start, false)];
        while let Some((index, leaving)) = pending.pop() {
            let Some(current_state) = state.get(index).copied() else {
                return Err(RenderedDomParseError::InvalidParentChild);
            };
            if leaving {
                let Some(slot) = state.get_mut(index) else {
                    return Err(RenderedDomParseError::InvalidParentChild);
                };
                *slot = 2;
                continue;
            }
            match current_state {
                1 => return Err(RenderedDomParseError::CycleDetected),
                2 => continue,
                _ => {}
            }
            let Some(slot) = state.get_mut(index) else {
                return Err(RenderedDomParseError::InvalidParentChild);
            };
            *slot = 1;
            pending.push((index, true));
            let Some(node) = nodes.get(index) else {
                return Err(RenderedDomParseError::InvalidParentChild);
            };
            for child_id in node.children().iter().rev() {
                let Some(child_index) = wire_index_by_id.get(child_id).copied() else {
                    return Err(RenderedDomParseError::UnknownNodeId);
                };
                pending.push((child_index, false));
            }
        }
    }
    Ok(())
}

fn preorder(
    nodes: &[WireNode],
    wire_index_by_id: &HashMap<DomNodeId, usize>,
    root: DomNodeId,
    maximum_depth: u32,
) -> Result<(Vec<usize>, u32), RenderedDomParseError> {
    let Some(root_index) = wire_index_by_id.get(&root).copied() else {
        return Err(RenderedDomParseError::InvalidRoot);
    };
    let mut order = Vec::with_capacity(nodes.len());
    let mut visited = vec![false; nodes.len()];
    let mut pending = vec![(root_index, 0_u32)];
    let mut max_depth = 0_u32;
    while let Some((index, depth)) = pending.pop() {
        if depth > maximum_depth {
            return Err(RenderedDomParseError::DepthLimitExceeded {
                maximum: maximum_depth,
                observed: depth,
            });
        }
        let Some(seen) = visited.get_mut(index) else {
            return Err(RenderedDomParseError::InvalidParentChild);
        };
        if *seen {
            return Err(RenderedDomParseError::CycleDetected);
        }
        *seen = true;
        max_depth = max_depth.max(depth);
        order.push(index);
        let Some(node) = nodes.get(index) else {
            return Err(RenderedDomParseError::InvalidParentChild);
        };
        for child_id in node.children().iter().rev() {
            let Some(child_index) = wire_index_by_id.get(child_id).copied() else {
                return Err(RenderedDomParseError::UnknownNodeId);
            };
            let child_depth = depth
                .checked_add(1)
                .ok_or(RenderedDomParseError::DepthOverflow)?;
            pending.push((child_index, child_depth));
        }
    }
    Ok((order, max_depth))
}
