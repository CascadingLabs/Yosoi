use std::num::NonZeroU64;

use serde::{Deserialize, Deserializer, Serialize, de::Error as _};
use thiserror::Error;

/// The semantic representation exposed to locators.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentRepresentation {
    /// Owned source payload rather than a live or rendered browser snapshot.
    Source,
    /// Versioned immutable rendered-DOM snapshot scoped to a document epoch.
    RenderedDom,
    /// Versioned immutable accessibility-tree snapshot scoped to a document epoch.
    AccessibilityTree,
}

/// The syntax of the owned document payload.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum SourceFormat {
    /// HTML payload interpreted using the selected HTML schema profile.
    Html,
    /// XML payload interpreted using the selected XML schema profile.
    Xml,
    /// JSON payload, including structured rendered or accessibility snapshots.
    Json,
    /// UTF-8 text payload without tree or JSON capabilities.
    Text,
}

/// The exact parser/schema profile required to interpret a payload.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentSchemaProfile {
    /// HTML5 source-tree interpretation.
    Html5,
    /// XML 1.0 source-tree interpretation.
    Xml10,
    /// RFC 8259 source JSON interpretation.
    JsonRfc8259,
    /// Decoded UTF-8 text interpretation.
    Utf8Text,
    /// Yosoi version-1 rendered-DOM JSON schema with snapshot-local node identities.
    YosoiRenderedDomV1,
    /// Yosoi version-1 accessibility-tree JSON schema with snapshot-local node identities.
    YosoiAccessibilityTreeV1,
}

/// One of the six document classes in the first locator slice.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum DocumentClass {
    /// HTML source bytes supporting the source-tree locator vocabulary.
    SourceHtml,
    /// XML source bytes supporting namespace-aware tree locators.
    SourceXml,
    /// Source JSON values supporting the JSON locator vocabulary.
    SourceJson,
    /// Source text supporting literal and regular-expression ranges.
    SourceText,
    /// Immutable rendered-DOM evidence supporting snapshot-local node coordinates.
    RenderedDom,
    /// Immutable accessibility evidence supporting role, name, text, and state locators.
    AccessibilityTree,
}

/// An opaque, document-local generation used to prevent DOM/AX substitution.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(transparent)]
pub struct DocumentEpoch(NonZeroU64);

impl DocumentEpoch {
    /// Returns the positive document-local generation without a global browser identity claim.
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
    /// Representation, payload syntax, and selected schema do not form a supported class.
    #[error("document profile combines incompatible representation, format, and schema axes")]
    IncompatibleAxes,
    /// Source payloads incorrectly declare a browser snapshot epoch.
    #[error("source documents must not claim a rendered document epoch")]
    UnexpectedEpoch,
    /// Rendered-DOM or accessibility evidence omits its required snapshot epoch.
    #[error("rendered DOM and accessibility documents require a document epoch")]
    MissingEpoch,
    /// A snapshot generation is zero rather than a positive document-local epoch.
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
    /// Validates representation, payload syntax, schema, and optional epoch as one profile.
    /// Returns [`DocumentProfileError`] for incompatible axes or incorrect epoch
    /// presence. This validates interpretation metadata, not payload bytes or
    /// live browser state; parsing and evidence acquisition are separate phases.
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

    /// Creates HTML5 source metadata without a snapshot epoch or document acquisition.
    pub const fn source_html() -> Self {
        Self::source(SourceFormat::Html, DocumentSchemaProfile::Html5)
    }

    /// Creates XML 1.0 source metadata without an epoch or document acquisition.
    pub const fn source_xml() -> Self {
        Self::source(SourceFormat::Xml, DocumentSchemaProfile::Xml10)
    }

    /// Creates RFC 8259 source JSON metadata without an epoch or acquisition.
    pub const fn source_json() -> Self {
        Self::source(SourceFormat::Json, DocumentSchemaProfile::JsonRfc8259)
    }

    /// Creates UTF-8 source text metadata without an epoch or acquisition.
    pub const fn source_text() -> Self {
        Self::source(SourceFormat::Text, DocumentSchemaProfile::Utf8Text)
    }

    /// Declares a version-1 rendered-DOM JSON snapshot at the supplied positive epoch.
    /// This does not capture a browser or validate payload membership in that epoch.
    pub const fn rendered_dom(epoch: DocumentEpoch) -> Self {
        Self {
            representation: DocumentRepresentation::RenderedDom,
            source_format: SourceFormat::Json,
            schema: DocumentSchemaProfile::YosoiRenderedDomV1,
            epoch: Some(epoch),
        }
    }

    /// Declares a version-1 accessibility JSON snapshot at the supplied positive epoch.
    /// This does not capture a browser or validate payload membership in that epoch.
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

    /// Returns whether this profile interprets source, rendered-DOM, or accessibility evidence.
    pub const fn representation(self) -> DocumentRepresentation {
        self.representation
    }

    /// Returns the syntax expected for the owned payload bytes.
    pub const fn source_format(self) -> SourceFormat {
        self.source_format
    }

    /// Returns the exact parser or versioned snapshot-schema interpretation.
    pub const fn schema(self) -> DocumentSchemaProfile {
        self.schema
    }

    /// Returns snapshot-local generation for rendered evidence, absent for source payloads.
    pub const fn epoch(self) -> Option<DocumentEpoch> {
        self.epoch
    }

    /// Resolves a supported capability class after checking all metadata axes together.
    /// Returns [`DocumentProfileError`] for incompatible schema/syntax or epoch
    /// presence. Resolution does not parse bytes or prove evidence completeness.
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
