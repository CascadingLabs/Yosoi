use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::num::NonZeroU64;

use super::{CoordinateError, DecodedTextCoordinate, TreeCoordinate};
use crate::internal::documents::{DocumentEpoch, DocumentId};

/// Native coordinate for a JSON value.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct JsonCoordinate(String);

impl JsonCoordinate {
    /// Owns a JSON Pointer after validating its root syntax and token escapes.
    ///
    /// The empty pointer selects the root; other pointers must begin with `/`,
    /// and `~` escapes must be `~0` or `~1`. Returns [`CoordinateError`] for
    /// violations. This does not verify that the pointer resolves in a document.
    pub fn try_new(pointer: impl Into<String>) -> Result<Self, CoordinateError> {
        let pointer = pointer.into();
        if !pointer.is_empty() && !pointer.starts_with('/') {
            return Err(CoordinateError::InvalidJsonPointerSyntax);
        }
        validate_json_pointer_escapes(&pointer)?;
        Ok(Self(pointer))
    }

    /// Borrows the validated JSON Pointer spelling, including the empty root pointer.
    pub fn as_pointer(&self) -> &str {
        &self.0
    }
}

fn validate_json_pointer_escapes(pointer: &str) -> Result<(), CoordinateError> {
    let mut bytes = pointer.bytes();
    while let Some(byte) = bytes.next() {
        if byte == b'~' && !matches!(bytes.next(), Some(b'0' | b'1')) {
            return Err(CoordinateError::InvalidJsonPointerEscape);
        }
    }
    Ok(())
}

impl<'de> Deserialize<'de> for JsonCoordinate {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        Self::try_new(String::deserialize(deserializer)?).map_err(D::Error::custom)
    }
}

/// Stable identity for one node inside a single rendered DOM snapshot.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct DomNodeId(NonZeroU64);

impl DomNodeId {
    /// Creates a positive snapshot-local node identity, rejecting zero.
    ///
    /// Returns [`CoordinateError::ZeroDomNodeId`] for zero; no DOM membership
    /// or epoch is checked by this scalar constructor.
    pub fn try_new(value: u64) -> Result<Self, CoordinateError> {
        NonZeroU64::new(value)
            .map(Self)
            .ok_or(CoordinateError::ZeroDomNodeId)
    }

    /// Returns the positive numeric node identity without its snapshot epoch.
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

impl TryFrom<u64> for DomNodeId {
    type Error = CoordinateError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        Self::try_new(value)
    }
}

/// Native coordinate for a rendered DOM node within its snapshot epoch.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DomCoordinate {
    document_epoch: DocumentEpoch,
    node_id: DomNodeId,
}

impl DomCoordinate {
    /// Pairs a snapshot epoch and node identity without querying a live DOM.
    ///
    /// Node IDs are meaningful only within the supplied epoch; construction
    /// does not prove that the node exists in that snapshot.
    pub const fn new(document_epoch: DocumentEpoch, node_id: DomNodeId) -> Self {
        Self {
            document_epoch,
            node_id,
        }
    }

    /// Returns the immutable rendered-DOM snapshot epoch that scopes this node.
    pub const fn document_epoch(self) -> DocumentEpoch {
        self.document_epoch
    }

    /// Returns the node identity, which must be interpreted with its document epoch.
    pub const fn node_id(self) -> DomNodeId {
        self.node_id
    }
}

/// Native coordinate for a node in one immutable accessibility-tree epoch.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct AccessibilityCoordinate {
    document_epoch: DocumentEpoch,
    node_id: String,
}

impl AccessibilityCoordinate {
    /// Owns an accessibility node identity within a supplied immutable epoch.
    ///
    /// Returns [`CoordinateError::EmptyIdentity`] for blank `node_id`. The
    /// original spelling is retained; no tree membership or epoch correspondence
    /// is verified against live accessibility evidence.
    pub fn try_new(
        document_epoch: DocumentEpoch,
        node_id: impl Into<String>,
    ) -> Result<Self, CoordinateError> {
        let node_id = node_id.into();
        if node_id.trim().is_empty() {
            Err(CoordinateError::EmptyIdentity)
        } else {
            Ok(Self {
                document_epoch,
                node_id,
            })
        }
    }

    /// Returns the immutable accessibility snapshot epoch that scopes this node.
    pub const fn document_epoch(&self) -> DocumentEpoch {
        self.document_epoch
    }

    /// Borrows the retained node identity without resolving it against a tree.
    pub fn node_id(&self) -> &str {
        &self.node_id
    }
}

impl<'de> Deserialize<'de> for AccessibilityCoordinate {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireCoordinate {
            document_epoch: DocumentEpoch,
            node_id: String,
        }

        let wire = WireCoordinate::deserialize(deserializer)?;
        Self::try_new(wire.document_epoch, wire.node_id).map_err(D::Error::custom)
    }
}

/// Exact representation-native location of a finding.
#[derive(Clone, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "kind", content = "coordinate", rename_all = "snake_case")]
pub enum NativeCoordinate {
    /// Child path and optional exact-byte or expanded-name evidence in HTML/XML source.
    SourceTree(TreeCoordinate),
    /// Validated JSON Pointer spelling, not a proof of resolution in a document.
    Json(JsonCoordinate),
    /// Node identity scoped to one immutable rendered-DOM snapshot epoch.
    RenderedDom(DomCoordinate),
    /// Node identity scoped to one immutable accessibility-tree snapshot epoch.
    Accessibility(AccessibilityCoordinate),
    /// Paired owned-source byte offsets and decoded-text Unicode-scalar offsets.
    DecodedText(DecodedTextCoordinate),
}

/// A projected node reference remains meaningful only with its document ID.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct NodeReference {
    document_id: DocumentId,
    coordinate: NativeCoordinate,
}

impl NodeReference {
    /// Owns a native node coordinate together with its document identity.
    ///
    /// This does not resolve the coordinate or retain document contents; the
    /// caller must retain the corresponding document to interpret the reference.
    pub const fn new(document_id: DocumentId, coordinate: NativeCoordinate) -> Self {
        Self {
            document_id,
            coordinate,
        }
    }

    /// Borrows the identity of the document needed to interpret this reference.
    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    /// Borrows the native location without fetching or retaining the document.
    pub const fn coordinate(&self) -> &NativeCoordinate {
        &self.coordinate
    }
}
