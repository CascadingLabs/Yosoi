use std::collections::BTreeMap;

use serde::{Deserialize, Serialize};
use thiserror::Error;

use crate::{
    AccessibilityStateName, Completeness, DocumentClass, DocumentEpoch, DocumentId,
    IncompleteEvidence, LocateFailure, ResourceLimit,
};

pub(super) const ACCESSIBILITY_SCHEMA_V1: &str = "yosoi.accessibility-tree.v1";
pub(super) const MAX_ACCESSIBILITY_NODES: u64 = 100_000;

/// Whether an immutable accessibility tree can prove that an absent match is absent.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum AccessibilityCompleteness {
    Complete,
    Partial {
        reason_code: String,
        lost_items: Option<u64>,
    },
    Unknown {
        reason_code: String,
    },
}

impl AccessibilityCompleteness {
    pub(super) fn validate(&self) -> Result<(), AccessibilityParseError> {
        match self {
            Self::Partial {
                reason_code,
                lost_items,
            } if reason_code.trim().is_empty() || *lost_items == Some(0) => {
                Err(AccessibilityParseError::InvalidCompleteness)
            }
            Self::Unknown { reason_code } if reason_code.trim().is_empty() => {
                Err(AccessibilityParseError::InvalidCompleteness)
            }
            Self::Complete | Self::Partial { .. } | Self::Unknown { .. } => Ok(()),
        }
    }

    pub(super) fn finding_completeness(&self) -> Completeness {
        match self {
            Self::Complete => Completeness::Complete,
            Self::Partial {
                reason_code,
                lost_items,
            } => Completeness::Partial {
                reason_code: reason_code.clone(),
                lost_items: *lost_items,
            },
            Self::Unknown { reason_code } => Completeness::Unknown {
                reason_code: reason_code.clone(),
            },
        }
    }

    pub(super) fn absence_evidence(&self) -> Option<IncompleteEvidence> {
        match self {
            Self::Complete => None,
            Self::Partial {
                reason_code,
                lost_items,
            } => Some(IncompleteEvidence::Partial {
                reason_code: reason_code.clone(),
                lost_items: *lost_items,
            }),
            Self::Unknown { reason_code } => Some(IncompleteEvidence::Unknown {
                reason_code: reason_code.clone(),
            }),
        }
    }

    pub(super) fn absence_reason(&self) -> Option<String> {
        match self {
            Self::Complete => None,
            Self::Partial { .. } => Some("accessibility_tree_partial".to_owned()),
            Self::Unknown { .. } => Some("accessibility_tree_completeness_unknown".to_owned()),
        }
    }
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AccessibilityTreeWire {
    pub(super) schema: String,
    pub(super) document_epoch: u64,
    pub(super) root: String,
    pub(super) completeness: AccessibilityCompleteness,
    pub(super) nodes: Vec<AccessibilityNodeWire>,
}

#[derive(Clone, Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct AccessibilityNodeWire {
    pub(super) id: String,
    pub(super) parent: Option<String>,
    pub(super) children: Vec<String>,
    pub(super) ignored: bool,
    pub(super) role: String,
    pub(super) accessible_name: Option<String>,
    pub(super) text: Option<String>,
    pub(super) states: BTreeMap<AccessibilityStateName, bool>,
}

#[derive(Clone, Debug)]
pub(super) struct AccessibilityNode {
    pub(super) id: String,
    pub(super) parent: Option<String>,
    pub(super) children: Vec<String>,
    pub(super) ignored: bool,
    pub(super) role: String,
    pub(super) accessible_name: Option<String>,
    pub(super) text: Option<String>,
    pub(super) states: BTreeMap<AccessibilityStateName, bool>,
}

/// A checked parse failure for the static accessibility-tree v1 schema.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum AccessibilityParseError {
    #[error("accessibility parsing requires an accessibility-tree document, got {document:?}")]
    UnsupportedDocument { document: DocumentClass },
    #[error("accessibility input is {observed} bytes, above the {maximum}-byte limit")]
    InputLimitExceeded { maximum: u64, observed: u64 },
    #[error("accessibility JSON is invalid or contains unsupported fields")]
    InvalidJson,
    #[error("accessibility schema is not yosoi.accessibility-tree.v1")]
    UnsupportedSchema,
    #[error("accessibility tree epoch must be greater than zero")]
    InvalidEpoch,
    #[error("accessibility tree epoch does not match its document profile")]
    EpochMismatch,
    #[error("accessibility tree completeness is invalid")]
    InvalidCompleteness,
    #[error("accessibility tree root identity cannot be empty")]
    EmptyRootId,
    #[error("accessibility node identity or role cannot be empty")]
    EmptyNodeIdentity,
    #[error("accessibility tree contains a duplicate node identity")]
    DuplicateNodeId,
    #[error("accessibility tree root is absent")]
    MissingRoot,
    #[error("accessibility tree root must not have a parent")]
    RootHasParent,
    #[error("accessibility node refers to a missing parent")]
    MissingParent,
    #[error("accessibility node refers to a missing child")]
    MissingChild,
    #[error("accessibility parent and child references disagree")]
    ParentChildMismatch,
    #[error("accessibility node lists the same child more than once")]
    DuplicateChild,
    #[error("accessibility tree contains a cycle")]
    Cycle,
    #[error("accessibility tree contains nodes outside the root tree")]
    UnreachableNode,
    #[error("accessibility tree depth is {observed}, above the {maximum}-level limit")]
    DepthLimitExceeded { maximum: u32, observed: u32 },
    #[error("accessibility tree has {observed} nodes, above the {maximum}-node limit")]
    NodeCountLimitExceeded { maximum: u64, observed: u64 },
    #[error("accessibility tree quantity cannot be represented by the public contract")]
    QuantityOverflow,
}

impl AccessibilityParseError {
    pub(super) fn into_failure(self) -> LocateFailure {
        match self {
            Self::UnsupportedDocument { document } => {
                LocateFailure::UnsupportedCombination { document }
            }
            Self::InputLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
                limit: ResourceLimit::InputBytes,
                maximum,
                observed,
            },
            Self::DepthLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
                limit: ResourceLimit::Depth,
                maximum: u64::from(maximum),
                observed: u64::from(observed),
            },
            Self::NodeCountLimitExceeded { maximum, observed } => LocateFailure::LimitExhausted {
                limit: ResourceLimit::Nodes,
                maximum,
                observed,
            },
            Self::InvalidJson => parse_failure("invalid_accessibility_json"),
            Self::UnsupportedSchema => parse_failure("unsupported_accessibility_schema"),
            Self::InvalidEpoch => parse_failure("invalid_accessibility_epoch"),
            Self::EpochMismatch => parse_failure("accessibility_epoch_mismatch"),
            Self::InvalidCompleteness => parse_failure("invalid_accessibility_completeness"),
            Self::EmptyRootId => parse_failure("empty_accessibility_root_id"),
            Self::EmptyNodeIdentity => parse_failure("empty_accessibility_node_identity"),
            Self::DuplicateNodeId => parse_failure("duplicate_accessibility_node_id"),
            Self::MissingRoot => parse_failure("accessibility_root_not_found"),
            Self::RootHasParent => parse_failure("accessibility_root_has_parent"),
            Self::MissingParent => parse_failure("accessibility_parent_not_found"),
            Self::MissingChild => parse_failure("accessibility_child_not_found"),
            Self::ParentChildMismatch => parse_failure("accessibility_parent_child_mismatch"),
            Self::DuplicateChild => parse_failure("duplicate_accessibility_child"),
            Self::Cycle => parse_failure("accessibility_tree_cycle"),
            Self::UnreachableNode => parse_failure("accessibility_node_unreachable"),
            Self::QuantityOverflow => parse_failure("accessibility_quantity_overflow"),
        }
    }
}

/// A validated, immutable accessibility tree ready for exact synchronous queries.
#[derive(Clone, Debug)]
pub struct ParsedAccessibilityDocument {
    pub(super) document_id: DocumentId,
    pub(super) document_epoch: DocumentEpoch,
    pub(super) input_bytes: u64,
    pub(super) node_count: u64,
    pub(super) completeness: AccessibilityCompleteness,
    pub(super) nodes: Vec<AccessibilityNode>,
    pub(super) tree_order: Vec<usize>,
    pub(super) max_depth: u32,
}

pub(super) fn parse_failure(code: &str) -> LocateFailure {
    LocateFailure::ParseFailed {
        code: code.to_owned(),
    }
}
