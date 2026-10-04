use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use std::num::NonZeroU64;

use super::{CoordinateError, DecodedTextCoordinate, TreeCoordinate};
use crate::{DocumentEpoch, DocumentId};

/// Native coordinate for a JSON value.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
#[serde(transparent)]
pub struct JsonCoordinate(String);

impl JsonCoordinate {
    pub fn try_new(pointer: impl Into<String>) -> Result<Self, CoordinateError> {
        let pointer = pointer.into();
        if !pointer.is_empty() && !pointer.starts_with('/') {
            return Err(CoordinateError::InvalidJsonPointerSyntax);
        }
        validate_json_pointer_escapes(&pointer)?;
        Ok(Self(pointer))
    }

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
    pub fn try_new(value: u64) -> Result<Self, CoordinateError> {
        NonZeroU64::new(value)
            .map(Self)
            .ok_or(CoordinateError::ZeroDomNodeId)
    }

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
    pub const fn new(document_epoch: DocumentEpoch, node_id: DomNodeId) -> Self {
        Self {
            document_epoch,
            node_id,
        }
    }

    pub const fn document_epoch(self) -> DocumentEpoch {
        self.document_epoch
    }

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

    pub const fn document_epoch(&self) -> DocumentEpoch {
        self.document_epoch
    }

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
    SourceTree(TreeCoordinate),
    Json(JsonCoordinate),
    RenderedDom(DomCoordinate),
    Accessibility(AccessibilityCoordinate),
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
    pub const fn new(document_id: DocumentId, coordinate: NativeCoordinate) -> Self {
        Self {
            document_id,
            coordinate,
        }
    }

    pub const fn document_id(&self) -> &DocumentId {
        &self.document_id
    }
    pub const fn coordinate(&self) -> &NativeCoordinate {
        &self.coordinate
    }
}
