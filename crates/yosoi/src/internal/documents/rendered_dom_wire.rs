use serde::Deserialize;

use crate::internal::documents::{DocumentEpoch, DomNodeId, html::HTML_NAMESPACE};

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WireDocument {
    pub(super) schema: String,
    pub(super) document_epoch: DocumentEpoch,
    pub(super) tree_model: String,
    pub(super) root: DomNodeId,
    pub(super) nodes: Vec<WireNode>,
}

#[derive(Debug, Deserialize)]
#[serde(untagged)]
pub(super) enum ParentField {
    Node(DomNodeId),
    Null(()),
}

impl ParentField {
    pub(super) const fn node_id(&self) -> Option<DomNodeId> {
        match self {
            Self::Node(node_id) => Some(*node_id),
            Self::Null(()) => None,
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(tag = "kind", rename_all = "snake_case", deny_unknown_fields)]
pub(super) enum WireNode {
    Document {
        id: DomNodeId,
        parent: ParentField,
        children: Vec<DomNodeId>,
    },
    Element {
        id: DomNodeId,
        parent: ParentField,
        children: Vec<DomNodeId>,
        namespace_uri: String,
        tag_name: String,
        attributes: Vec<WireAttribute>,
    },
    Text {
        id: DomNodeId,
        parent: ParentField,
        children: Vec<DomNodeId>,
        value: String,
    },
}

impl WireNode {
    pub(super) const fn id(&self) -> DomNodeId {
        match self {
            Self::Document { id, .. } | Self::Element { id, .. } | Self::Text { id, .. } => *id,
        }
    }

    pub(super) const fn parent(&self) -> Option<DomNodeId> {
        match self {
            Self::Document { parent, .. }
            | Self::Element { parent, .. }
            | Self::Text { parent, .. } => parent.node_id(),
        }
    }

    pub(super) fn children(&self) -> &[DomNodeId] {
        match self {
            Self::Document { children, .. }
            | Self::Element { children, .. }
            | Self::Text { children, .. } => children,
        }
    }

    pub(super) const fn is_document(&self) -> bool {
        matches!(self, Self::Document { .. })
    }

    pub(super) fn strings_are_valid(&self) -> bool {
        match self {
            Self::Document { .. } => true,
            Self::Element {
                namespace_uri,
                tag_name,
                attributes,
                ..
            } => {
                (namespace_uri.is_empty() || valid_uri(namespace_uri))
                    && valid_name(tag_name, namespace_uri == HTML_NAMESPACE)
                    && attributes.iter().all(WireAttribute::strings_are_valid)
            }
            Self::Text { value, .. } => valid_text(value),
        }
    }
}

#[derive(Debug, Deserialize)]
#[serde(deny_unknown_fields)]
pub(super) struct WireAttribute {
    pub(super) namespace_uri: String,
    pub(super) name: String,
    pub(super) value: String,
}

impl WireAttribute {
    fn strings_are_valid(&self) -> bool {
        (self.namespace_uri.is_empty() || valid_uri(&self.namespace_uri))
            && valid_name(&self.name, self.namespace_uri.is_empty())
            && valid_text(&self.value)
    }
}

pub(super) fn valid_uri(value: &str) -> bool {
    !value.is_empty()
        && value
            .chars()
            .all(|character| !character.is_control() && !character.is_whitespace())
}

fn valid_name(value: &str, allow_colon: bool) -> bool {
    !value.is_empty()
        && value.chars().all(|character| {
            !character.is_control()
                && !character.is_whitespace()
                && !matches!(character, '<' | '>' | '=' | '"' | '\'' | '`' | '/')
                && (allow_colon || character != ':')
        })
}

fn valid_text(value: &str) -> bool {
    value.chars().all(|character| {
        character != '\0' && (!character.is_control() || character.is_ascii_whitespace())
    })
}
