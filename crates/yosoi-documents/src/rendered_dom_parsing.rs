use thiserror::Error;

use crate::{Document, DocumentClass, LocateFailure, ResourceBudget, ResourceLimit};

use super::index::build_index;
use super::types::{RENDERED_DOM_SCHEMA_V1, RenderedDomDocument};
use super::validation::validate_wire_tree;
use super::wire::WireDocument;

/// Invalid canonical rendered-DOM input or a structural budget exceeded.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum RenderedDomParseError {
    #[error("rendered DOM parser only accepts rendered-DOM documents")]
    UnsupportedDocument { document: DocumentClass },
    #[error("rendered DOM input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("rendered DOM node count is {observed}, above the {maximum}-node limit")]
    NodeLimitExceeded { maximum: u64, observed: u64 },
    #[error("rendered DOM node count cannot be represented by the public contract")]
    NodeCountOverflow,
    #[error("rendered DOM input is not valid canonical JSON")]
    InvalidJson,
    #[error("rendered DOM schema identifier is not supported")]
    UnsupportedSchema,
    #[error("rendered DOM tree model is not supported")]
    UnsupportedTreeModel,
    #[error("rendered DOM profile has no document epoch")]
    MissingEpoch,
    #[error("rendered DOM payload epoch {observed} differs from profile epoch {expected}")]
    EpochMismatch { expected: u64, observed: u64 },
    #[error("rendered DOM root must name the single parentless document node")]
    InvalidRoot,
    #[error("rendered DOM document node must have exactly one element child")]
    InvalidDocumentRootChildren,
    #[error("rendered DOM contains a duplicate node identity")]
    DuplicateNodeId,
    #[error("rendered DOM contains a reference to an unknown node identity")]
    UnknownNodeId,
    #[error("rendered DOM parent and child edges disagree")]
    InvalidParentChild,
    #[error("rendered DOM contains an unsupported node shape")]
    InvalidNode,
    #[error("rendered DOM contains an invalid tag, namespace, attribute, or text string")]
    InvalidString,
    #[error("rendered DOM contains a duplicate attribute")]
    DuplicateAttribute,
    #[error("rendered DOM attributes are not in canonical namespace/name order")]
    InvalidAttributeOrder,
    #[error("rendered DOM tree contains a cycle")]
    CycleDetected,
    #[error("rendered DOM tree contains nodes outside the root document")]
    DisconnectedNodes,
    #[error("rendered DOM depth is {observed}, above the {maximum}-level limit")]
    DepthLimitExceeded { maximum: u32, observed: u32 },
    #[error("rendered DOM depth cannot be represented by the public contract")]
    DepthOverflow,
}

pub(super) fn parse_failure(error: &RenderedDomParseError) -> LocateFailure {
    match error {
        RenderedDomParseError::UnsupportedDocument { document } => {
            LocateFailure::UnsupportedCombination {
                document: *document,
            }
        }
        RenderedDomParseError::InputLimitExceeded { maximum, observed } => {
            LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum: *maximum,
                observed: *observed,
            }
        }
        RenderedDomParseError::NodeLimitExceeded { maximum, observed } => {
            LocateFailure::LimitExhausted {
                limit: ResourceLimit::Nodes,
                maximum: *maximum,
                observed: *observed,
            }
        }
        RenderedDomParseError::DepthLimitExceeded { maximum, observed } => {
            LocateFailure::LimitExhausted {
                limit: ResourceLimit::Depth,
                maximum: u64::from(*maximum),
                observed: u64::from(*observed),
            }
        }
        RenderedDomParseError::NodeCountOverflow => {
            parse_failed("rendered_dom_node_count_overflow")
        }
        RenderedDomParseError::InvalidJson => parse_failed("rendered_dom_invalid_json"),
        RenderedDomParseError::UnsupportedSchema => parse_failed("rendered_dom_unsupported_schema"),
        RenderedDomParseError::UnsupportedTreeModel => {
            parse_failed("rendered_dom_unsupported_tree_model")
        }
        RenderedDomParseError::MissingEpoch => parse_failed("rendered_dom_missing_epoch"),
        RenderedDomParseError::EpochMismatch { .. } => parse_failed("rendered_dom_epoch_mismatch"),
        RenderedDomParseError::InvalidRoot => parse_failed("rendered_dom_invalid_root"),
        RenderedDomParseError::InvalidDocumentRootChildren => {
            parse_failed("rendered_dom_invalid_document_children")
        }
        RenderedDomParseError::DuplicateNodeId => parse_failed("rendered_dom_duplicate_node_id"),
        RenderedDomParseError::UnknownNodeId => parse_failed("rendered_dom_unknown_node_id"),
        RenderedDomParseError::InvalidParentChild => {
            parse_failed("rendered_dom_parent_child_mismatch")
        }
        RenderedDomParseError::InvalidNode => parse_failed("rendered_dom_invalid_node"),
        RenderedDomParseError::InvalidString => parse_failed("rendered_dom_invalid_string"),
        RenderedDomParseError::DuplicateAttribute => {
            parse_failed("rendered_dom_duplicate_attribute")
        }
        RenderedDomParseError::InvalidAttributeOrder => {
            parse_failed("rendered_dom_invalid_attribute_order")
        }
        RenderedDomParseError::CycleDetected => parse_failed("rendered_dom_cycle"),
        RenderedDomParseError::DisconnectedNodes => parse_failed("rendered_dom_disconnected_nodes"),
        RenderedDomParseError::DepthOverflow => parse_failed("rendered_dom_depth_overflow"),
    }
}

fn parse_failed(code: &str) -> LocateFailure {
    LocateFailure::ParseFailed {
        code: code.to_owned(),
    }
}

impl RenderedDomDocument {
    /// Parses one immutable canonical rendered-DOM snapshot under fixed limits.
    pub fn parse(
        document: &Document,
        limits: ResourceBudget,
    ) -> Result<Self, RenderedDomParseError> {
        if document.class() != DocumentClass::RenderedDom {
            return Err(RenderedDomParseError::UnsupportedDocument {
                document: document.class(),
            });
        }
        if document.byte_len() > limits.max_input_bytes() {
            return Err(RenderedDomParseError::InputLimitExceeded {
                maximum: limits.max_input_bytes(),
                observed: document.byte_len(),
            });
        }
        let expected_epoch = document
            .profile()
            .epoch()
            .ok_or(RenderedDomParseError::MissingEpoch)?;
        let wire: WireDocument = serde_json::from_slice(document.bytes())
            .map_err(|_| RenderedDomParseError::InvalidJson)?;
        if wire.schema != RENDERED_DOM_SCHEMA_V1 {
            return Err(RenderedDomParseError::UnsupportedSchema);
        }
        if wire.document_epoch != expected_epoch {
            return Err(RenderedDomParseError::EpochMismatch {
                expected: expected_epoch.get(),
                observed: wire.document_epoch.get(),
            });
        }

        let validated = validate_wire_tree(&wire, limits.max_nodes(), limits.max_depth())?;
        let node_count = u64::try_from(wire.nodes.len())
            .map_err(|_| RenderedDomParseError::NodeCountOverflow)?;
        let index = build_index(&wire, &validated)?;
        Ok(Self {
            document_id: document.id().clone(),
            document_epoch: expected_epoch,
            input_bytes: document.byte_len(),
            node_count,
            elements: index.elements,
            normalized_text: index.normalized_text,
            text_segments: index.text_segments,
            max_depth: validated.max_depth,
        })
    }
}
