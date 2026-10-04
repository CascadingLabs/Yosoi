use std::num::NonZeroU64;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

/// The semantic representation exposed to locators.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentRepresentation {
    Source,
    RenderedDom,
    AccessibilityTree,
}

/// The syntax of the owned document payload.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceFormat {
    Html,
    Xml,
    Json,
    Text,
}

/// The exact parser/schema profile required to interpret a payload.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentSchemaProfile {
    Html5,
    Xml10,
    JsonRfc8259,
    Utf8Text,
    YosoiRenderedDomV1,
    YosoiAccessibilityTreeV1,
}

/// One of the six document classes in the first locator slice.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentClass {
    SourceHtml,
    SourceXml,
    SourceJson,
    SourceText,
    RenderedDom,
    AccessibilityTree,
}

/// An opaque, document-local generation used to prevent DOM/AX substitution.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct DocumentEpoch(NonZeroU64);

impl DocumentEpoch {
    pub const fn get(self) -> u64 {
        self.0.get()
    }
}

impl TryFrom<u64> for DocumentEpoch {
    type Error = DocumentProfileError;

    fn try_from(value: u64) -> Result<Self, Self::Error> {
        NonZeroU64::new(value)
            .map(Self)
            .ok_or(DocumentProfileError::ZeroEpoch)
    }
}

/// Invalid combinations of representation, payload syntax, schema, and epoch.
#[derive(Clone, Copy, Debug, Eq, Error, PartialEq)]
pub enum DocumentProfileError {
    #[error("document profile combines incompatible representation, format, and schema axes")]
    IncompatibleAxes,
    #[error("source documents must not claim a rendered document epoch")]
    UnexpectedEpoch,
    #[error("rendered DOM and accessibility documents require a document epoch")]
    MissingEpoch,
    #[error("document epoch must be greater than zero")]
    ZeroEpoch,
}

/// Validated interpretation contract for one immutable payload.
#[derive(Clone, Copy, Debug, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct DocumentProfile {
    representation: DocumentRepresentation,
    source_format: SourceFormat,
    schema: DocumentSchemaProfile,
    epoch: Option<DocumentEpoch>,
}

impl DocumentProfile {
    pub fn try_new(
        representation: DocumentRepresentation,
        source_format: SourceFormat,
        schema: DocumentSchemaProfile,
        epoch: Option<DocumentEpoch>,
    ) -> Result<Self, DocumentProfileError> {
        let profile = Self {
            representation,
            source_format,
            schema,
            epoch,
        };
        profile.class()?;
        Ok(profile)
    }

    pub const fn source_html() -> Self {
        Self::source(SourceFormat::Html, DocumentSchemaProfile::Html5)
    }

    pub const fn source_xml() -> Self {
        Self::source(SourceFormat::Xml, DocumentSchemaProfile::Xml10)
    }

    pub const fn source_json() -> Self {
        Self::source(SourceFormat::Json, DocumentSchemaProfile::JsonRfc8259)
    }

    pub const fn source_text() -> Self {
        Self::source(SourceFormat::Text, DocumentSchemaProfile::Utf8Text)
    }

    pub const fn rendered_dom(epoch: DocumentEpoch) -> Self {
        Self {
            representation: DocumentRepresentation::RenderedDom,
            source_format: SourceFormat::Json,
            schema: DocumentSchemaProfile::YosoiRenderedDomV1,
            epoch: Some(epoch),
        }
    }

    pub const fn accessibility_tree_v1(epoch: DocumentEpoch) -> Self {
        Self {
            representation: DocumentRepresentation::AccessibilityTree,
            source_format: SourceFormat::Json,
            schema: DocumentSchemaProfile::YosoiAccessibilityTreeV1,
            epoch: Some(epoch),
        }
    }

    const fn source(source_format: SourceFormat, schema: DocumentSchemaProfile) -> Self {
        Self {
            representation: DocumentRepresentation::Source,
            source_format,
            schema,
            epoch: None,
        }
    }

    pub const fn representation(self) -> DocumentRepresentation {
        self.representation
    }

    pub const fn source_format(self) -> SourceFormat {
        self.source_format
    }

    pub const fn schema(self) -> DocumentSchemaProfile {
        self.schema
    }

    pub const fn epoch(self) -> Option<DocumentEpoch> {
        self.epoch
    }

    pub const fn class(self) -> Result<DocumentClass, DocumentProfileError> {
        match (
            self.representation,
            self.source_format,
            self.schema,
            self.epoch,
        ) {
            (
                DocumentRepresentation::Source,
                SourceFormat::Html,
                DocumentSchemaProfile::Html5,
                None,
            ) => Ok(DocumentClass::SourceHtml),
            (
                DocumentRepresentation::Source,
                SourceFormat::Xml,
                DocumentSchemaProfile::Xml10,
                None,
            ) => Ok(DocumentClass::SourceXml),
            (
                DocumentRepresentation::Source,
                SourceFormat::Json,
                DocumentSchemaProfile::JsonRfc8259,
                None,
            ) => Ok(DocumentClass::SourceJson),
            (
                DocumentRepresentation::Source,
                SourceFormat::Text,
                DocumentSchemaProfile::Utf8Text,
                None,
            ) => Ok(DocumentClass::SourceText),
            (
                DocumentRepresentation::RenderedDom,
                SourceFormat::Json,
                DocumentSchemaProfile::YosoiRenderedDomV1,
                Some(_),
            ) => Ok(DocumentClass::RenderedDom),
            (
                DocumentRepresentation::AccessibilityTree,
                SourceFormat::Json,
                DocumentSchemaProfile::YosoiAccessibilityTreeV1,
                Some(_),
            ) => Ok(DocumentClass::AccessibilityTree),
            (DocumentRepresentation::Source, _, _, Some(_)) => {
                Err(DocumentProfileError::UnexpectedEpoch)
            }
            (
                DocumentRepresentation::RenderedDom | DocumentRepresentation::AccessibilityTree,
                _,
                _,
                None,
            ) => Err(DocumentProfileError::MissingEpoch),
            _ => Err(DocumentProfileError::IncompatibleAxes),
        }
    }
}

impl<'de> Deserialize<'de> for DocumentProfile {
    fn deserialize<D>(deserializer: D) -> Result<Self, D::Error>
    where
        D: Deserializer<'de>,
    {
        #[derive(Deserialize)]
        #[serde(deny_unknown_fields)]
        struct WireProfile {
            representation: DocumentRepresentation,
            source_format: SourceFormat,
            schema: DocumentSchemaProfile,
            epoch: Option<DocumentEpoch>,
        }

        let wire = WireProfile::deserialize(deserializer)?;
        Self::try_new(
            wire.representation,
            wire.source_format,
            wire.schema,
            wire.epoch,
        )
        .map_err(D::Error::custom)
    }
}
