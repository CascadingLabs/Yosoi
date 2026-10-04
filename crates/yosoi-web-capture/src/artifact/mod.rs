//! Typed web artifact families, provider capabilities, and capture outcomes.
//!
//! Artifact payload schemas remain independently versioned. This module
//! describes what a payload means, whether a provider can produce it, and what
//! happened when capture was requested; it does not define DOM, accessibility,
//! network, storage, layout, visual, or runtime-event payloads.

mod capability;
mod decoded_source;
mod family;
mod manifest;
mod media_type;
mod metadata;
mod outcome;
mod relationship;
mod source_representation;

pub use capability::{
    AcquisitionCapabilityProfile, ArtifactCapability, ArtifactMultiplicity,
    BrowserNavigationCapabilityProfile, WebArtifactCapabilitySet, WebProviderCapabilityProfile,
    WebProviderCapabilityProfileError,
};
pub use decoded_source::{
    DECODED_SOURCE_POLICY_VERSION, DecodedExtent, DecodedSourceArtifact,
    DecodedSourceArtifactError, DecodedSourceArtifactRef, DecodedSourceInterpretation,
    DecodingBasis, DecodingConflict,
};
pub use family::{
    AccessibilityTreeArtifact, AccessibilityTreeArtifactRef, CookieArtifact, CookieArtifactRef,
    LayoutArtifact, LayoutArtifactRef, NetworkArtifact, NetworkArtifactRef, RenderedDomArtifact,
    RenderedDomArtifactRef, RuntimeDiagnosticsArtifact, RuntimeDiagnosticsArtifactRef,
    SourceArtifact, SourceArtifactRef, StorageArtifact, StorageArtifactRef, VisualArtifact,
    VisualArtifactRef, WebArtifact, WebArtifactFamily, WebArtifactRef,
};
pub use manifest::{WebArtifactManifest, WebArtifactManifestError};
pub use media_type::{MediaType, MediaTypeError};
pub use metadata::{
    ArtifactByteExtent, ArtifactByteExtentError, ArtifactSensitivity, TruncatedArtifactExtent,
    WebArtifactMetadata, WebArtifactMetadataError,
};
pub use outcome::{
    ArtifactCollection, ArtifactCollectionError, ArtifactFamilyResult, ArtifactRequest,
    WebArtifactRequestSet, WebArtifactResults,
};
pub use relationship::WebArtifactRelationship;
pub use source_representation::{
    SourceRepresentationArtifact, SourceRepresentationArtifactError,
    SourceRepresentationArtifactRef,
};
