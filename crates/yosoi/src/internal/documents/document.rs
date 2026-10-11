use crate::internal::documents as yosoi_documents;

#[path = "document_profile.rs"]
mod profile;
pub use profile::{
    DocumentClass, DocumentEpoch, DocumentProfile, DocumentProfileError, DocumentRepresentation,
    DocumentSchemaProfile, SourceFormat,
};

use std::fmt;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

use crate::internal::documents::{LocateFailure, Plan, ResourceBudget};

/// Stable caller-provided identity for an immutable document.
#[derive(Clone, Debug, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct DocumentId(String);

impl DocumentId {
    pub fn try_new(value: impl Into<String>) -> Result<Self, DocumentError> {
        let value = value.into();
        if value.trim().is_empty() {
            Err(DocumentError::EmptyId)
        } else {
            Ok(Self(value))
        }
    }

    pub fn as_str(&self) -> &str {
        &self.0
    }
}

impl fmt::Display for DocumentId {
    fn fmt(&self, formatter: &mut fmt::Formatter<'_>) -> fmt::Result {
        self.0.fmt(formatter)
    }
}

impl<'de> Deserialize<'de> for DocumentId {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        String::deserialize(deserializer)?
            .try_into()
            .map_err(D::Error::custom)
    }
}

impl TryFrom<String> for DocumentId {
    type Error = DocumentError;

    fn try_from(value: String) -> Result<Self, Self::Error> {
        Self::try_new(value)
    }
}

/// Invalid immutable document input.
#[derive(Clone, Debug, Eq, Error, PartialEq)]
pub enum DocumentError {
    #[error("document identity cannot be empty")]
    EmptyId,
    #[error("non-text document payload cannot be empty")]
    EmptyPayload,
    #[error("document payload length cannot be represented as u64")]
    PayloadLengthOverflow,
    #[error(transparent)]
    InvalidProfile(#[from] DocumentProfileError),
}

/// Owned immutable bytes plus their exact interpretation contract.
#[derive(Clone, Debug, Eq, PartialEq)]
pub struct Document {
    id: DocumentId,
    profile: DocumentProfile,
    class: DocumentClass,
    bytes: Vec<u8>,
    byte_len: u64,
}

impl Document {
    /// Creates an immutable source HTML document.
    pub fn html(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        Self::from_profile(
            DocumentId::try_new(id)?,
            DocumentProfile::source_html(),
            bytes,
        )
    }

    /// Creates an immutable source XML document.
    pub fn xml(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        Self::from_profile(
            DocumentId::try_new(id)?,
            DocumentProfile::source_xml(),
            bytes,
        )
    }

    /// Creates an immutable source JSON document.
    pub fn json(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        Self::from_profile(
            DocumentId::try_new(id)?,
            DocumentProfile::source_json(),
            bytes,
        )
    }

    /// Creates an immutable strictly decoded text document.
    pub fn text(id: impl Into<String>, bytes: impl Into<Vec<u8>>) -> Result<Self, DocumentError> {
        Self::from_profile(
            DocumentId::try_new(id)?,
            DocumentProfile::source_text(),
            bytes,
        )
    }

    /// Creates an immutable rendered-DOM snapshot tied to one document epoch.
    pub fn rendered_dom(
        id: impl Into<String>,
        epoch: DocumentEpoch,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        Self::from_profile(
            DocumentId::try_new(id)?,
            DocumentProfile::rendered_dom(epoch),
            bytes,
        )
    }

    /// Creates an immutable accessibility-tree snapshot tied to one document epoch.
    pub fn accessibility_tree(
        id: impl Into<String>,
        epoch: DocumentEpoch,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        Self::from_profile(
            DocumentId::try_new(id)?,
            DocumentProfile::accessibility_tree_v1(epoch),
            bytes,
        )
    }

    /// Reconstructs a Document from its validated durable interpretation data.
    ///
    /// This is the domain-owned boundary used after archived bytes are resolved.
    /// It preserves the exact source, rendered-DOM, or accessibility profile and
    /// never infers one representation from another.
    pub fn from_profile(
        id: DocumentId,
        profile: DocumentProfile,
        bytes: impl Into<Vec<u8>>,
    ) -> Result<Self, DocumentError> {
        let class = profile.class()?;
        let bytes = bytes.into();
        if bytes.is_empty() && class != DocumentClass::SourceText {
            return Err(DocumentError::EmptyPayload);
        }
        let byte_len =
            u64::try_from(bytes.len()).map_err(|_| DocumentError::PayloadLengthOverflow)?;
        Ok(Self {
            id,
            profile,
            class,
            bytes,
            byte_len,
        })
    }

    pub const fn id(&self) -> &DocumentId {
        &self.id
    }

    pub const fn profile(&self) -> DocumentProfile {
        self.profile
    }

    pub const fn class(&self) -> DocumentClass {
        self.class
    }

    pub fn bytes(&self) -> &[u8] {
        &self.bytes
    }

    pub const fn byte_len(&self) -> u64 {
        self.byte_len
    }

    /// Validates document and plan work against one operation's resource budget.
    pub(in crate::internal::documents) fn validate_plan(
        &self,
        plan: &Plan,
        budget: ResourceBudget,
    ) -> Result<(), LocateFailure> {
        let class = self.class();
        if !plan.requirement().accepts(class) {
            return Err(LocateFailure::UnsupportedCombination { document: class });
        }
        let maximum = budget.max_input_bytes();
        if self.byte_len > maximum {
            return Err(LocateFailure::LimitExhausted {
                limit: yosoi_documents::ResourceLimit::InputBytes,
                maximum,
                observed: self.byte_len,
            });
        }
        plan.validate_budget(budget)
    }
}
