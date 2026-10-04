//! Provider-neutral normalization of complete browser HTML snapshots.

use html5ever::{ParseOpts, parse_document, tendril::TendrilSink, tree_builder::TreeBuilderOpts};
use markup5ever_rcdom::{Handle, NodeData, RcDom};
use thiserror::Error;
use yosoi_documents::{DocumentEpoch, DomNodeId, ResourceBudget};

use crate::Document;

#[path = "dom_wire.rs"]
mod wire;
use wire::{RenderedDomWire, WireAttribute, WireNode, serialize_bounded};

use wire::{RENDERED_DOM_SCHEMA_V1, RENDERED_DOM_TREE_MODEL};

/// Failure while converting complete rendered HTML into a validated DOM document.
#[derive(Debug, Error)]
pub enum RenderedDomNormalizationError {
    #[error("rendered DOM epoch must be greater than zero")]
    InvalidEpoch,
    #[error("rendered HTML is not valid UTF-8")]
    InvalidUtf8,
    #[error("rendered HTML input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("rendered DOM node count is {observed}, above the {maximum}-node limit")]
    NodeLimitExceeded { maximum: u64, observed: u64 },
    #[error("rendered DOM depth is {observed}, above the {maximum}-level limit")]
    DepthLimitExceeded { maximum: u32, observed: u32 },
    #[error("rendered DOM output exceeds the {maximum}-byte limit")]
    OutputLimitExceeded { maximum: u64 },
    #[error("rendered HTML has no document element")]
    MissingDocumentElement,
    #[error("rendered HTML has multiple document elements")]
    MultipleDocumentElements,
    #[error("rendered DOM node identity space is exhausted")]
    NodeIdOverflow,
    #[error("rendered DOM node count cannot be represented")]
    NodeCountOverflow,
    #[error("rendered DOM depth cannot be represented")]
    DepthOverflow,
    #[error("rendered HTML parser produced an unsupported tree shape")]
    InvalidTree,
    #[error("rendered HTML parser produced duplicate canonical attributes")]
    DuplicateAttribute,
    #[error("rendered DOM output limit cannot be represented by this platform")]
    OutputLimitNotAddressable,
    #[error("rendered DOM allocation failed within the configured limits")]
    AllocationFailed,
    #[error("rendered DOM serialization failed")]
    Serialization(#[source] serde_json::Error),
    #[error(transparent)]
    Document(#[from] yosoi_documents::DocumentError),
    #[error(transparent)]
    Parse(#[from] yosoi_documents::DocumentParseError),
    #[error(transparent)]
    DomCoordinate(#[from] yosoi_documents::CoordinateError),
}

struct ChildCursor {
    parent: Handle,
    parent_index: usize,
    parent_id: DomNodeId,
    depth: u32,
    next_child: usize,
}

enum WalkTask {
    Visit {
        handle: Handle,
        parent_index: usize,
        parent_id: DomNodeId,
        depth: u32,
    },
    Children(ChildCursor),
}

/// Normalizes a complete UTF-8 browser HTML snapshot to the v1 light-DOM wire
/// schema, then validates the resulting document with the supplied resource budget.
///
/// The caller must check the browser artifact's availability and extent first. A
/// truncated artifact is incomplete evidence and must not be passed here.
/// Comments, the doctype, and template-content fragments are intentionally omitted.
pub fn normalize_rendered_dom(
    id: impl Into<String>,
    epoch: u64,
    html: Vec<u8>,
    budget: ResourceBudget,
) -> Result<Document, RenderedDomNormalizationError> {
    let epoch =
        DocumentEpoch::try_from(epoch).map_err(|_| RenderedDomNormalizationError::InvalidEpoch)?;
    let observed_input = u64::try_from(html.len()).map_err(|_| {
        RenderedDomNormalizationError::InputLimitExceeded {
            maximum: budget.max_input_bytes(),
            observed: u64::MAX,
        }
    })?;
    if observed_input > budget.max_input_bytes() {
        return Err(RenderedDomNormalizationError::InputLimitExceeded {
            maximum: budget.max_input_bytes(),
            observed: observed_input,
        });
    }
    let html = String::from_utf8(html).map_err(|_| RenderedDomNormalizationError::InvalidUtf8)?;
    let options = ParseOpts {
        tree_builder: TreeBuilderOpts {
            // Browser snapshots come from a scripting-enabled live document.
            // In particular, `<noscript>` contents must remain text rather
            // than becoming selectable element nodes during normalization.
            scripting_enabled: true,
            ..TreeBuilderOpts::default()
        },
        ..ParseOpts::default()
    };
    let dom = parse_document(RcDom::default(), options).one(html);
    let document_element = document_element(&dom.document)?;
    let document_id = DomNodeId::try_new(1)?;
    let mut nodes = Vec::new();
    reserve_one(&mut nodes)?;
    nodes.push(WireNode::Document {
        id: document_id,
        parent: None,
        children: Vec::new(),
    });

    let mut pending = Vec::new();
    push_task(
        &mut pending,
        WalkTask::Visit {
            handle: document_element,
            parent_index: 0,
            parent_id: document_id,
            depth: 1,
        },
    )?;
    walk_dom(&mut pending, &mut nodes, budget)?;

    let wire = RenderedDomWire {
        schema: RENDERED_DOM_SCHEMA_V1,
        document_epoch: epoch,
        tree_model: RENDERED_DOM_TREE_MODEL,
        root: document_id,
        nodes,
    };
    let wire_bytes = serialize_bounded(&wire, budget)?;
    let document = Document::rendered_dom(id, epoch, wire_bytes)?;
    {
        let _parsed = document.parse_with_budget(budget)?;
    }
    Ok(document)
}

fn document_element(document: &Handle) -> Result<Handle, RenderedDomNormalizationError> {
    let children = document.children.borrow();
    let mut found = None;
    for child in children.iter() {
        match &child.data {
            NodeData::Element { .. } => {}
            NodeData::Comment { .. }
            | NodeData::Doctype { .. }
            | NodeData::ProcessingInstruction { .. } => continue,
            NodeData::Text { .. } | NodeData::Document => {
                return Err(RenderedDomNormalizationError::InvalidTree);
            }
        }
        if found.is_some() {
            return Err(RenderedDomNormalizationError::MultipleDocumentElements);
        }
        found = Some(child.clone());
    }
    found.ok_or(RenderedDomNormalizationError::MissingDocumentElement)
}

fn walk_dom(
    pending: &mut Vec<WalkTask>,
    nodes: &mut Vec<WireNode>,
    budget: ResourceBudget,
) -> Result<(), RenderedDomNormalizationError> {
    while let Some(task) = pending.pop() {
        match task {
            WalkTask::Visit {
                handle,
                parent_index,
                parent_id,
                depth,
            } => {
                if depth > budget.max_depth() {
                    return Err(RenderedDomNormalizationError::DepthLimitExceeded {
                        maximum: budget.max_depth(),
                        observed: depth,
                    });
                }
                let current_nodes = u64::try_from(nodes.len())
                    .map_err(|_| RenderedDomNormalizationError::NodeCountOverflow)?;
                let observed_nodes = current_nodes
                    .checked_add(1)
                    .ok_or(RenderedDomNormalizationError::NodeIdOverflow)?;
                if observed_nodes > budget.max_nodes() {
                    return Err(RenderedDomNormalizationError::NodeLimitExceeded {
                        maximum: budget.max_nodes(),
                        observed: observed_nodes,
                    });
                }
                let node_id = DomNodeId::try_new(observed_nodes)?;
                let node = wire_node(&handle, node_id, parent_id)?;
                append_child(nodes, parent_index, node_id)?;
                reserve_one(nodes)?;
                let node_index = nodes.len();
                nodes.push(node);

                if matches!(&handle.data, NodeData::Element { .. }) {
                    let next_depth = depth
                        .checked_add(1)
                        .ok_or(RenderedDomNormalizationError::DepthOverflow)?;
                    push_task(
                        pending,
                        WalkTask::Children(ChildCursor {
                            parent: handle,
                            parent_index: node_index,
                            parent_id: node_id,
                            depth: next_depth,
                            next_child: 0,
                        }),
                    )?;
                }
            }
            WalkTask::Children(mut cursor) => {
                // Template contents live in html5ever's separate fragment, not
                // in Element.children, so this walk deliberately omits them.
                let child = cursor
                    .parent
                    .children
                    .borrow()
                    .get(cursor.next_child)
                    .cloned();
                let Some(child) = child else {
                    continue;
                };
                let parent_index = cursor.parent_index;
                let parent_id = cursor.parent_id;
                let depth = cursor.depth;
                cursor.next_child = cursor
                    .next_child
                    .checked_add(1)
                    .ok_or(RenderedDomNormalizationError::NodeCountOverflow)?;
                push_task(pending, WalkTask::Children(cursor))?;
                match &child.data {
                    NodeData::Element { .. } | NodeData::Text { .. } => push_task(
                        pending,
                        WalkTask::Visit {
                            handle: child,
                            parent_index,
                            parent_id,
                            depth,
                        },
                    )?,
                    NodeData::Comment { .. }
                    | NodeData::Doctype { .. }
                    | NodeData::ProcessingInstruction { .. } => {}
                    NodeData::Document => {
                        return Err(RenderedDomNormalizationError::InvalidTree);
                    }
                }
            }
        }
    }
    Ok(())
}

fn wire_node(
    handle: &Handle,
    id: DomNodeId,
    parent: DomNodeId,
) -> Result<WireNode, RenderedDomNormalizationError> {
    match &handle.data {
        NodeData::Element { name, attrs, .. } => {
            let attributes = attrs.borrow();
            let mut wire_attributes = Vec::new();
            wire_attributes
                .try_reserve(attributes.len())
                .map_err(|_| RenderedDomNormalizationError::AllocationFailed)?;
            for attribute in attributes.iter() {
                wire_attributes.push(WireAttribute {
                    namespace_uri: copy_string(attribute.name.ns.as_ref())?,
                    name: copy_string(attribute.name.local.as_ref())?,
                    value: copy_string(attribute.value.as_ref())?,
                });
            }
            wire_attributes.sort_unstable_by(|left, right| {
                (left.namespace_uri.as_str(), left.name.as_str())
                    .cmp(&(right.namespace_uri.as_str(), right.name.as_str()))
            });
            if wire_attributes
                .iter()
                .zip(wire_attributes.iter().skip(1))
                .any(|(left, right)| {
                    left.namespace_uri == right.namespace_uri && left.name == right.name
                })
            {
                return Err(RenderedDomNormalizationError::DuplicateAttribute);
            }
            Ok(WireNode::Element {
                id,
                parent: Some(parent),
                children: Vec::new(),
                namespace_uri: copy_string(name.ns.as_ref())?,
                tag_name: copy_string(name.local.as_ref())?,
                attributes: wire_attributes,
            })
        }
        NodeData::Text { contents } => Ok(WireNode::Text {
            id,
            parent: Some(parent),
            children: Vec::new(),
            value: copy_string(contents.borrow().as_ref())?,
        }),
        _ => Err(RenderedDomNormalizationError::InvalidTree),
    }
}

fn append_child(
    nodes: &mut [WireNode],
    parent_index: usize,
    child_id: DomNodeId,
) -> Result<(), RenderedDomNormalizationError> {
    let parent = nodes
        .get_mut(parent_index)
        .ok_or(RenderedDomNormalizationError::InvalidTree)?;
    let children = match parent {
        WireNode::Document { children, .. } | WireNode::Element { children, .. } => children,
        WireNode::Text { .. } => return Err(RenderedDomNormalizationError::InvalidTree),
    };
    children
        .try_reserve(1)
        .map_err(|_| RenderedDomNormalizationError::AllocationFailed)?;
    children.push(child_id);
    Ok(())
}

fn push_task(
    pending: &mut Vec<WalkTask>,
    task: WalkTask,
) -> Result<(), RenderedDomNormalizationError> {
    pending
        .try_reserve(1)
        .map_err(|_| RenderedDomNormalizationError::AllocationFailed)?;
    pending.push(task);
    Ok(())
}

fn reserve_one<T>(values: &mut Vec<T>) -> Result<(), RenderedDomNormalizationError> {
    values
        .try_reserve(1)
        .map_err(|_| RenderedDomNormalizationError::AllocationFailed)
}

fn copy_string(value: &str) -> Result<String, RenderedDomNormalizationError> {
    let mut copy = String::new();
    copy.try_reserve(value.len())
        .map_err(|_| RenderedDomNormalizationError::AllocationFailed)?;
    copy.push_str(value);
    Ok(copy)
}

#[cfg(test)]
#[path = "dom_tests.rs"]
mod tests;
