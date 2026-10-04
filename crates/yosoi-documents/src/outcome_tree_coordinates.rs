use serde::{Deserialize, Deserializer, Serialize, de::Error as _};

use super::{ByteRange, CoordinateError};

/// One namespace-qualified XML element identity within a tree path.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct ExpandedNamePathSegment {
    namespace_uri: Option<String>,
    local_name: String,
    same_name_sibling_index: u32,
}

impl ExpandedNamePathSegment {
    pub fn try_new(
        namespace_uri: Option<String>,
        local_name: impl Into<String>,
        same_name_sibling_index: u32,
    ) -> Result<Self, CoordinateError> {
        let local_name = local_name.into();
        if local_name.is_empty() {
            return Err(CoordinateError::EmptyExpandedLocalName);
        }
        if same_name_sibling_index == 0 {
            return Err(CoordinateError::ZeroExpandedSiblingIndex);
        }
        Ok(Self {
            namespace_uri,
            local_name,
            same_name_sibling_index,
        })
    }

    pub fn namespace_uri(&self) -> Option<&str> {
        self.namespace_uri.as_deref()
    }

    pub fn local_name(&self) -> &str {
        &self.local_name
    }

    pub const fn same_name_sibling_index(&self) -> u32 {
        self.same_name_sibling_index
    }
}

impl<'de> Deserialize<'de> for ExpandedNamePathSegment {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireSegment {
            namespace_uri: Option<String>,
            local_name: String,
            same_name_sibling_index: u32,
        }

        let wire = WireSegment::deserialize(deserializer)?;
        Self::try_new(
            wire.namespace_uri,
            wire.local_name,
            wire.same_name_sibling_index,
        )
        .map_err(D::Error::custom)
    }
}

/// Native coordinate for an HTML or XML tree node.
///
/// XML coordinates may include expanded-name segments, which use namespace
/// URIs rather than source prefix spelling.
#[derive(Clone, Debug, Eq, Hash, PartialEq, Serialize)]
pub struct TreeCoordinate {
    child_path: Vec<u32>,
    source_bytes: Option<ByteRange>,
    #[serde(skip_serializing_if = "Option::is_none")]
    expanded_name_path: Option<Vec<ExpandedNamePathSegment>>,
}

impl TreeCoordinate {
    pub fn try_new(
        child_path: Vec<u32>,
        source_bytes: Option<ByteRange>,
    ) -> Result<Self, CoordinateError> {
        validate_child_path(&child_path)?;
        Ok(Self {
            child_path,
            source_bytes,
            expanded_name_path: None,
        })
    }

    pub fn with_expanded_name_path(
        child_path: Vec<u32>,
        source_bytes: Option<ByteRange>,
        expanded_name_path: Vec<ExpandedNamePathSegment>,
    ) -> Result<Self, CoordinateError> {
        validate_child_path(&child_path)?;
        if expanded_name_path.is_empty() {
            return Err(CoordinateError::EmptyExpandedNamePath);
        }
        Ok(Self {
            child_path,
            source_bytes,
            expanded_name_path: Some(expanded_name_path),
        })
    }

    pub fn child_path(&self) -> &[u32] {
        &self.child_path
    }
    pub const fn source_bytes(&self) -> Option<ByteRange> {
        self.source_bytes
    }
    pub fn expanded_name_path(&self) -> Option<&[ExpandedNamePathSegment]> {
        self.expanded_name_path.as_deref()
    }
}

impl<'de> Deserialize<'de> for TreeCoordinate {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireCoordinate {
            child_path: Vec<u32>,
            source_bytes: Option<ByteRange>,
            #[serde(default)]
            expanded_name_path: Option<Vec<ExpandedNamePathSegment>>,
        }

        let wire = WireCoordinate::deserialize(deserializer)?;
        validate_child_path(&wire.child_path).map_err(D::Error::custom)?;
        if wire.expanded_name_path.as_ref().is_some_and(Vec::is_empty) {
            return Err(D::Error::custom(CoordinateError::EmptyExpandedNamePath));
        }
        Ok(Self {
            child_path: wire.child_path,
            source_bytes: wire.source_bytes,
            expanded_name_path: wire.expanded_name_path,
        })
    }
}

fn validate_child_path(child_path: &[u32]) -> Result<(), CoordinateError> {
    if child_path.is_empty() || child_path.contains(&0) {
        Err(CoordinateError::InvalidTreeChildPath)
    } else {
        Ok(())
    }
}
