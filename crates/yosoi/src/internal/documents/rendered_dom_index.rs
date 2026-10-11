use crate::internal::documents::html::{TextSegment, append_normalized_text};

use super::parsing::RenderedDomParseError;
use super::types::{DomAttribute, RenderedDomElement};
use super::validation::ValidatedTree;
use super::wire::{WireDocument, WireNode};

pub(super) struct RenderedDomIndex {
    pub(super) elements: Vec<RenderedDomElement>,
    pub(super) normalized_text: String,
    pub(super) text_segments: Vec<TextSegment>,
}

pub(super) fn build_index(
    wire: &WireDocument,
    validated: &ValidatedTree,
) -> Result<RenderedDomIndex, RenderedDomParseError> {
    let mut elements = Vec::new();
    let mut nearest_element_by_wire_index = vec![None; wire.nodes.len()];
    let mut normalized_text = String::new();
    let mut text_segments = Vec::new();
    let mut previous_was_space = false;

    for wire_index in validated.node_order.iter().copied() {
        let node = wire
            .nodes
            .get(wire_index)
            .ok_or(RenderedDomParseError::InvalidParentChild)?;
        let parent_element = match node.parent() {
            Some(parent_id) => {
                let parent_index = validated
                    .wire_index_by_id
                    .get(&parent_id)
                    .copied()
                    .ok_or(RenderedDomParseError::UnknownNodeId)?;
                nearest_element_by_wire_index
                    .get(parent_index)
                    .copied()
                    .flatten()
            }
            None => None,
        };

        match node {
            WireNode::Element {
                id,
                namespace_uri,
                tag_name,
                attributes,
                ..
            } => {
                let element_index = elements.len();
                elements.push(RenderedDomElement {
                    id: *id,
                    parent: parent_element,
                    children: Vec::new(),
                    namespace_uri: namespace_uri.clone(),
                    tag_name: tag_name.clone(),
                    attributes: attributes
                        .iter()
                        .map(|attribute| DomAttribute {
                            namespace_uri: attribute.namespace_uri.clone(),
                            name: attribute.name.clone(),
                            value: attribute.value.clone(),
                        })
                        .collect(),
                    text_range: None,
                });
                if let Some(parent_index) = parent_element {
                    elements
                        .get_mut(parent_index)
                        .ok_or(RenderedDomParseError::InvalidParentChild)?
                        .children
                        .push(element_index);
                }
                let slot = nearest_element_by_wire_index
                    .get_mut(wire_index)
                    .ok_or(RenderedDomParseError::InvalidParentChild)?;
                *slot = Some(element_index);
            }
            WireNode::Text { value, .. } => {
                if let Some(owner) = parent_element {
                    let start = normalized_text.len();
                    append_normalized_text(value, &mut normalized_text, &mut previous_was_space);
                    let end = normalized_text.len();
                    if end > start {
                        text_segments.push(TextSegment { start, end, owner });
                        merge_range(
                            &mut elements
                                .get_mut(owner)
                                .ok_or(RenderedDomParseError::InvalidParentChild)?
                                .text_range,
                            (start, end),
                        );
                    }
                }
                let slot = nearest_element_by_wire_index
                    .get_mut(wire_index)
                    .ok_or(RenderedDomParseError::InvalidParentChild)?;
                *slot = parent_element;
            }
            WireNode::Document { .. } => {
                let slot = nearest_element_by_wire_index
                    .get_mut(wire_index)
                    .ok_or(RenderedDomParseError::InvalidParentChild)?;
                *slot = None;
            }
        }
    }

    for element_index in (0..elements.len()).rev() {
        let Some(child) = elements.get(element_index) else {
            return Err(RenderedDomParseError::InvalidParentChild);
        };
        if let (Some(parent_index), Some(range)) = (child.parent, child.text_range) {
            let parent = elements
                .get_mut(parent_index)
                .ok_or(RenderedDomParseError::InvalidParentChild)?;
            merge_range(&mut parent.text_range, range);
        }
    }

    Ok(RenderedDomIndex {
        elements,
        normalized_text,
        text_segments,
    })
}

fn merge_range(target: &mut Option<(usize, usize)>, incoming: (usize, usize)) {
    match target {
        Some((start, end)) => {
            *start = (*start).min(incoming.0);
            *end = (*end).max(incoming.1);
        }
        None => *target = Some(incoming),
    }
}
