use serde::{Deserialize, Serialize};
use yosoi_types::ArtifactRef;

use super::{
    DecodedSourceArtifact, DecodedSourceArtifactRef, SourceRepresentationArtifact,
    SourceRepresentationArtifactRef, WebArtifactMetadata,
};

macro_rules! define_artifact_family {
    ($artifact:ident, $reference:ident, $variant:ident, $documentation:literal) => {
        #[doc = $documentation]
        #[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
        #[serde(transparent)]
        pub struct $artifact(WebArtifactMetadata);

        impl $artifact {
            /// Creates a family-typed artifact from validated common metadata.
            pub const fn new(metadata: WebArtifactMetadata) -> Self {
                Self(metadata)
            }

            /// Returns the common artifact metadata.
            pub const fn metadata(&self) -> &WebArtifactMetadata {
                &self.0
            }

            /// Returns a reference that cannot be confused with another family.
            pub const fn reference(&self) -> $reference {
                $reference(self.0.reference())
            }

            /// Removes the family wrapper.
            pub fn into_metadata(self) -> WebArtifactMetadata {
                self.0
            }
        }

        #[doc = concat!("Typed reference to a [`", stringify!($artifact), "`].")]
        #[derive(
            Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize,
        )]
        #[serde(transparent)]
        pub struct $reference(ArtifactRef);

        impl $reference {
            /// Creates a family-typed reference from an existing artifact identity.
            pub const fn from_untyped(reference: ArtifactRef) -> Self {
                Self(reference)
            }

            /// Returns the underlying cross-domain artifact reference.
            pub const fn as_untyped(self) -> ArtifactRef {
                self.0
            }
        }

        impl From<$artifact> for WebArtifact {
            fn from(value: $artifact) -> Self {
                Self::$variant(value)
            }
        }

        impl From<$reference> for WebArtifactRef {
            fn from(value: $reference) -> Self {
                Self::$variant(value)
            }
        }
    };
}

define_artifact_family!(
    SourceArtifact,
    SourceArtifactRef,
    Source,
    "Original document or resource source content."
);
impl From<SourceRepresentationArtifact> for WebArtifact {
    fn from(value: SourceRepresentationArtifact) -> Self {
        Self::SourceRepresentation(value)
    }
}
impl From<SourceRepresentationArtifactRef> for WebArtifactRef {
    fn from(value: SourceRepresentationArtifactRef) -> Self {
        Self::SourceRepresentation(value)
    }
}
define_artifact_family!(
    RenderedDomArtifact,
    RenderedDomArtifactRef,
    RenderedDom,
    "A serialized rendered document observation."
);
define_artifact_family!(
    AccessibilityTreeArtifact,
    AccessibilityTreeArtifactRef,
    AccessibilityTree,
    "A browser accessibility-tree observation."
);
define_artifact_family!(
    NetworkArtifact,
    NetworkArtifactRef,
    Network,
    "A bounded network observation or exchange representation."
);
define_artifact_family!(
    CookieArtifact,
    CookieArtifactRef,
    Cookies,
    "A scoped cookie-state observation."
);
define_artifact_family!(
    StorageArtifact,
    StorageArtifactRef,
    Storage,
    "A scoped web-storage observation."
);
define_artifact_family!(
    LayoutArtifact,
    LayoutArtifactRef,
    Layout,
    "A layout, geometry, style, or paint-order observation."
);
define_artifact_family!(
    VisualArtifact,
    VisualArtifactRef,
    Visual,
    "A visual page representation such as a screenshot or frame."
);
define_artifact_family!(
    RuntimeDiagnosticsArtifact,
    RuntimeDiagnosticsArtifactRef,
    RuntimeDiagnostics,
    "A bounded console and JavaScript runtime-diagnostics observation."
);

/// Stable semantic identity of a first-version web artifact family.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(rename_all = "snake_case")]
pub enum WebArtifactFamily {
    /// Original source content.
    Source,
    /// Canonical facts derived from source content.
    SourceRepresentation,
    /// Bounded UTF-8 decoding derived from source content.
    DecodedSource,
    /// Rendered document serialization.
    RenderedDom,
    /// Browser accessibility tree.
    AccessibilityTree,
    /// Bounded network evidence.
    Network,
    /// Cookie state.
    Cookies,
    /// Web-storage state.
    Storage,
    /// Layout and geometry evidence.
    Layout,
    /// Visual evidence.
    Visual,
    /// Console messages and JavaScript runtime failures.
    RuntimeDiagnostics,
}

/// Closed first-version vocabulary of web artifact families.
///
/// Each variant carries only family identity and common metadata. Its schema in
/// provenance identifies the independently versioned payload representation.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(
    tag = "family",
    content = "artifact",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum WebArtifact {
    /// Original source content.
    Source(SourceArtifact),
    /// Canonical source representation facts.
    SourceRepresentation(SourceRepresentationArtifact),
    /// Bounded UTF-8 decoding derived from source content.
    DecodedSource(DecodedSourceArtifact),
    /// Rendered document serialization.
    RenderedDom(RenderedDomArtifact),
    /// Browser accessibility tree.
    AccessibilityTree(AccessibilityTreeArtifact),
    /// Bounded network evidence.
    Network(NetworkArtifact),
    /// Cookie state.
    Cookies(CookieArtifact),
    /// Web-storage state.
    Storage(StorageArtifact),
    /// Layout and geometry evidence.
    Layout(LayoutArtifact),
    /// Visual evidence.
    Visual(VisualArtifact),
    /// Console messages and JavaScript runtime failures.
    RuntimeDiagnostics(RuntimeDiagnosticsArtifact),
}

impl WebArtifact {
    /// Returns this artifact's stable semantic family.
    pub const fn family(&self) -> WebArtifactFamily {
        match self {
            Self::Source(_) => WebArtifactFamily::Source,
            Self::SourceRepresentation(_) => WebArtifactFamily::SourceRepresentation,
            Self::DecodedSource(_) => WebArtifactFamily::DecodedSource,
            Self::RenderedDom(_) => WebArtifactFamily::RenderedDom,
            Self::AccessibilityTree(_) => WebArtifactFamily::AccessibilityTree,
            Self::Network(_) => WebArtifactFamily::Network,
            Self::Cookies(_) => WebArtifactFamily::Cookies,
            Self::Storage(_) => WebArtifactFamily::Storage,
            Self::Layout(_) => WebArtifactFamily::Layout,
            Self::Visual(_) => WebArtifactFamily::Visual,
            Self::RuntimeDiagnostics(_) => WebArtifactFamily::RuntimeDiagnostics,
        }
    }

    /// Returns common metadata without erasing the enum's family identity.
    pub const fn metadata(&self) -> &WebArtifactMetadata {
        match self {
            Self::Source(artifact) => artifact.metadata(),
            Self::SourceRepresentation(artifact) => artifact.metadata(),
            Self::DecodedSource(artifact) => artifact.metadata(),
            Self::RenderedDom(artifact) => artifact.metadata(),
            Self::AccessibilityTree(artifact) => artifact.metadata(),
            Self::Network(artifact) => artifact.metadata(),
            Self::Cookies(artifact) => artifact.metadata(),
            Self::Storage(artifact) => artifact.metadata(),
            Self::Layout(artifact) => artifact.metadata(),
            Self::Visual(artifact) => artifact.metadata(),
            Self::RuntimeDiagnostics(artifact) => artifact.metadata(),
        }
    }

    /// Returns a family-discriminated artifact reference.
    pub const fn reference(&self) -> WebArtifactRef {
        match self {
            Self::Source(artifact) => WebArtifactRef::Source(artifact.reference()),
            Self::SourceRepresentation(artifact) => {
                WebArtifactRef::SourceRepresentation(artifact.reference())
            }
            Self::DecodedSource(artifact) => WebArtifactRef::DecodedSource(artifact.reference()),
            Self::RenderedDom(artifact) => WebArtifactRef::RenderedDom(artifact.reference()),
            Self::AccessibilityTree(artifact) => {
                WebArtifactRef::AccessibilityTree(artifact.reference())
            }
            Self::Network(artifact) => WebArtifactRef::Network(artifact.reference()),
            Self::Cookies(artifact) => WebArtifactRef::Cookies(artifact.reference()),
            Self::Storage(artifact) => WebArtifactRef::Storage(artifact.reference()),
            Self::Layout(artifact) => WebArtifactRef::Layout(artifact.reference()),
            Self::Visual(artifact) => WebArtifactRef::Visual(artifact.reference()),
            Self::RuntimeDiagnostics(artifact) => {
                WebArtifactRef::RuntimeDiagnostics(artifact.reference())
            }
        }
    }
}

/// Family-discriminated reference to a web artifact.
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, Ord, PartialEq, PartialOrd, Serialize)]
#[serde(
    tag = "family",
    content = "reference",
    rename_all = "snake_case",
    deny_unknown_fields
)]
pub enum WebArtifactRef {
    /// Source artifact reference.
    Source(SourceArtifactRef),
    /// Source representation facts reference.
    SourceRepresentation(SourceRepresentationArtifactRef),
    /// Decoded-source artifact reference.
    DecodedSource(DecodedSourceArtifactRef),
    /// Rendered-DOM artifact reference.
    RenderedDom(RenderedDomArtifactRef),
    /// Accessibility-tree artifact reference.
    AccessibilityTree(AccessibilityTreeArtifactRef),
    /// Network artifact reference.
    Network(NetworkArtifactRef),
    /// Cookie artifact reference.
    Cookies(CookieArtifactRef),
    /// Storage artifact reference.
    Storage(StorageArtifactRef),
    /// Layout artifact reference.
    Layout(LayoutArtifactRef),
    /// Visual artifact reference.
    Visual(VisualArtifactRef),
    /// Runtime-diagnostics artifact reference.
    RuntimeDiagnostics(RuntimeDiagnosticsArtifactRef),
}

impl WebArtifactRef {
    /// Returns this reference's stable semantic family.
    pub const fn family(self) -> WebArtifactFamily {
        match self {
            Self::Source(_) => WebArtifactFamily::Source,
            Self::SourceRepresentation(_) => WebArtifactFamily::SourceRepresentation,
            Self::DecodedSource(_) => WebArtifactFamily::DecodedSource,
            Self::RenderedDom(_) => WebArtifactFamily::RenderedDom,
            Self::AccessibilityTree(_) => WebArtifactFamily::AccessibilityTree,
            Self::Network(_) => WebArtifactFamily::Network,
            Self::Cookies(_) => WebArtifactFamily::Cookies,
            Self::Storage(_) => WebArtifactFamily::Storage,
            Self::Layout(_) => WebArtifactFamily::Layout,
            Self::Visual(_) => WebArtifactFamily::Visual,
            Self::RuntimeDiagnostics(_) => WebArtifactFamily::RuntimeDiagnostics,
        }
    }

    /// Returns the underlying generic artifact reference.
    pub const fn as_untyped(self) -> ArtifactRef {
        match self {
            Self::Source(reference) => reference.as_untyped(),
            Self::SourceRepresentation(reference) => reference.as_untyped(),
            Self::DecodedSource(reference) => reference.as_untyped(),
            Self::RenderedDom(reference) => reference.as_untyped(),
            Self::AccessibilityTree(reference) => reference.as_untyped(),
            Self::Network(reference) => reference.as_untyped(),
            Self::Cookies(reference) => reference.as_untyped(),
            Self::Storage(reference) => reference.as_untyped(),
            Self::Layout(reference) => reference.as_untyped(),
            Self::Visual(reference) => reference.as_untyped(),
            Self::RuntimeDiagnostics(reference) => reference.as_untyped(),
        }
    }
}
