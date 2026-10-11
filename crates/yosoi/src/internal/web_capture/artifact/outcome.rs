use crate::internal::types::ReasonCode;
use serde::{Deserialize, Serialize};

use super::{
    AccessibilityTreeArtifact, CookieArtifact, DecodedSourceArtifact, LayoutArtifact,
    NetworkArtifact, RenderedDomArtifact, RuntimeDiagnosticsArtifact, SourceArtifact,
    SourceRepresentationArtifact, StorageArtifact, VisualArtifact,
};

mod request;
pub use request::{
    ArtifactCollection, ArtifactCollectionError, ArtifactRequest, WebArtifactRequestSet,
};

/// Actual result for one requested artifact family.
///
/// A successful empty logical snapshot is still represented by a retained
/// artifact whose payload contains zero entries. It is never represented as an
/// absent collection.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(tag = "status", rename_all = "snake_case", deny_unknown_fields)]
pub enum ArtifactFamilyResult<T> {
    /// The caller did not request this family.
    NotRequested,
    /// The requested scope was completely represented.
    Complete {
        /// One or more deliberately scoped family artifacts.
        artifacts: ArtifactCollection<T>,
    },
    /// Useful artifacts were produced, but the requested scope was incomplete.
    Partial {
        /// One or more retained or explicitly unavailable family artifacts.
        artifacts: ArtifactCollection<T>,
        /// Stable explanation of the incomplete scope.
        reason: ReasonCode,
    },
    /// Capture was attempted but failed before an artifact could be produced.
    Failed {
        /// Stable explanation of the production failure.
        reason: ReasonCode,
    },
    /// Capture was permitted and supported, but no artifact could be produced.
    Unavailable {
        /// Stable explanation of the runtime unavailability.
        reason: ReasonCode,
    },
    /// Policy prohibited capture or retention of the family.
    OmittedByPolicy {
        /// Stable policy explanation.
        reason: ReasonCode,
    },
    /// The selected provider profile does not support the family.
    Unsupported {
        /// Stable support explanation.
        reason: ReasonCode,
    },
}

impl<T> ArtifactFamilyResult<T> {
    /// Returns whether the family was explicitly not requested.
    pub const fn is_not_requested(&self) -> bool {
        matches!(self, Self::NotRequested)
    }

    /// Returns produced artifacts for complete or partial outcomes.
    pub fn artifacts(&self) -> Option<&[T]> {
        match self {
            Self::Complete { artifacts } | Self::Partial { artifacts, .. } => {
                Some(artifacts.as_slice())
            }
            Self::NotRequested
            | Self::Failed { .. }
            | Self::Unavailable { .. }
            | Self::OmittedByPolicy { .. }
            | Self::Unsupported { .. } => None,
        }
    }
}

/// Exhaustive actual artifact results for one capture attempt.
#[derive(Clone, Debug, Deserialize, Eq, PartialEq, Serialize)]
#[serde(deny_unknown_fields)]
pub struct WebArtifactResults {
    source: ArtifactFamilyResult<SourceArtifact>,
    /// Canonical typed interpretation facts derived from retained source.
    source_representation: ArtifactFamilyResult<SourceRepresentationArtifact>,
    /// A retention-policy-derived UTF-8 view. This is not caller request intent.
    ///
    /// This field is required in the current pre-release v1 wire shape. Older
    /// development fixtures are intentionally not migrated.
    decoded_source: ArtifactFamilyResult<DecodedSourceArtifact>,
    rendered_dom: ArtifactFamilyResult<RenderedDomArtifact>,
    accessibility_tree: ArtifactFamilyResult<AccessibilityTreeArtifact>,
    network: ArtifactFamilyResult<NetworkArtifact>,
    cookies: ArtifactFamilyResult<CookieArtifact>,
    storage: ArtifactFamilyResult<StorageArtifact>,
    layout: ArtifactFamilyResult<LayoutArtifact>,
    visual: ArtifactFamilyResult<VisualArtifact>,
    runtime_diagnostics: ArtifactFamilyResult<RuntimeDiagnosticsArtifact>,
}

impl WebArtifactResults {
    /// Creates an exhaustive result manifest.
    #[allow(clippy::too_many_arguments)]
    pub const fn new(
        source: ArtifactFamilyResult<SourceArtifact>,
        rendered_dom: ArtifactFamilyResult<RenderedDomArtifact>,
        accessibility_tree: ArtifactFamilyResult<AccessibilityTreeArtifact>,
        network: ArtifactFamilyResult<NetworkArtifact>,
        cookies: ArtifactFamilyResult<CookieArtifact>,
        storage: ArtifactFamilyResult<StorageArtifact>,
        layout: ArtifactFamilyResult<LayoutArtifact>,
        visual: ArtifactFamilyResult<VisualArtifact>,
        runtime_diagnostics: ArtifactFamilyResult<RuntimeDiagnosticsArtifact>,
    ) -> Self {
        Self::new_with_derived_source(
            source,
            ArtifactFamilyResult::NotRequested,
            ArtifactFamilyResult::NotRequested,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        )
    }

    /// Creates results including the retention-policy-derived decoded source family.
    #[allow(clippy::too_many_arguments)]
    pub const fn new_with_decoded_source(
        source: ArtifactFamilyResult<SourceArtifact>,
        decoded_source: ArtifactFamilyResult<DecodedSourceArtifact>,
        rendered_dom: ArtifactFamilyResult<RenderedDomArtifact>,
        accessibility_tree: ArtifactFamilyResult<AccessibilityTreeArtifact>,
        network: ArtifactFamilyResult<NetworkArtifact>,
        cookies: ArtifactFamilyResult<CookieArtifact>,
        storage: ArtifactFamilyResult<StorageArtifact>,
        layout: ArtifactFamilyResult<LayoutArtifact>,
        visual: ArtifactFamilyResult<VisualArtifact>,
        runtime_diagnostics: ArtifactFamilyResult<RuntimeDiagnosticsArtifact>,
    ) -> Self {
        Self::new_with_derived_source(
            source,
            ArtifactFamilyResult::NotRequested,
            decoded_source,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        )
    }

    /// Creates results including source-derived facts and decoded source.
    #[allow(clippy::too_many_arguments)]
    pub const fn new_with_derived_source(
        source: ArtifactFamilyResult<SourceArtifact>,
        source_representation: ArtifactFamilyResult<SourceRepresentationArtifact>,
        decoded_source: ArtifactFamilyResult<DecodedSourceArtifact>,
        rendered_dom: ArtifactFamilyResult<RenderedDomArtifact>,
        accessibility_tree: ArtifactFamilyResult<AccessibilityTreeArtifact>,
        network: ArtifactFamilyResult<NetworkArtifact>,
        cookies: ArtifactFamilyResult<CookieArtifact>,
        storage: ArtifactFamilyResult<StorageArtifact>,
        layout: ArtifactFamilyResult<LayoutArtifact>,
        visual: ArtifactFamilyResult<VisualArtifact>,
        runtime_diagnostics: ArtifactFamilyResult<RuntimeDiagnosticsArtifact>,
    ) -> Self {
        Self {
            source,
            source_representation,
            decoded_source,
            rendered_dom,
            accessibility_tree,
            network,
            cookies,
            storage,
            layout,
            visual,
            runtime_diagnostics,
        }
    }

    /// Returns source-content results.
    pub const fn source(&self) -> &ArtifactFamilyResult<SourceArtifact> {
        &self.source
    }

    /// Returns canonical source interpretation evidence.
    pub const fn source_representation(
        &self,
    ) -> &ArtifactFamilyResult<SourceRepresentationArtifact> {
        &self.source_representation
    }

    /// Returns the retention-policy-derived decoded UTF-8 source results.
    pub const fn decoded_source(&self) -> &ArtifactFamilyResult<DecodedSourceArtifact> {
        &self.decoded_source
    }

    /// Returns rendered-DOM results.
    pub const fn rendered_dom(&self) -> &ArtifactFamilyResult<RenderedDomArtifact> {
        &self.rendered_dom
    }

    /// Returns accessibility-tree results.
    pub const fn accessibility_tree(&self) -> &ArtifactFamilyResult<AccessibilityTreeArtifact> {
        &self.accessibility_tree
    }

    /// Returns network-observation results.
    pub const fn network(&self) -> &ArtifactFamilyResult<NetworkArtifact> {
        &self.network
    }

    /// Returns cookie-state results.
    pub const fn cookies(&self) -> &ArtifactFamilyResult<CookieArtifact> {
        &self.cookies
    }

    /// Returns web-storage results.
    pub const fn storage(&self) -> &ArtifactFamilyResult<StorageArtifact> {
        &self.storage
    }

    /// Returns layout-observation results.
    pub const fn layout(&self) -> &ArtifactFamilyResult<LayoutArtifact> {
        &self.layout
    }

    /// Returns visual-artifact results.
    pub const fn visual(&self) -> &ArtifactFamilyResult<VisualArtifact> {
        &self.visual
    }

    /// Returns runtime-diagnostics results.
    pub const fn runtime_diagnostics(&self) -> &ArtifactFamilyResult<RuntimeDiagnosticsArtifact> {
        &self.runtime_diagnostics
    }

    /// Collects every produced artifact with its family discriminator.
    ///
    /// Foundation validation and external producer finalization use this
    /// closed traversal to validate ownership without exposing mutable access
    /// to the exhaustive family fields. The returned artifacts are snapshots.
    pub fn all_artifacts(&self) -> Vec<super::WebArtifact> {
        let mut artifacts = Vec::new();
        extend_artifacts(&mut artifacts, &self.source);
        extend_artifacts(&mut artifacts, &self.source_representation);
        extend_artifacts(&mut artifacts, &self.decoded_source);
        extend_artifacts(&mut artifacts, &self.rendered_dom);
        extend_artifacts(&mut artifacts, &self.accessibility_tree);
        extend_artifacts(&mut artifacts, &self.network);
        extend_artifacts(&mut artifacts, &self.cookies);
        extend_artifacts(&mut artifacts, &self.storage);
        extend_artifacts(&mut artifacts, &self.layout);
        extend_artifacts(&mut artifacts, &self.visual);
        extend_artifacts(&mut artifacts, &self.runtime_diagnostics);
        artifacts
    }

    /// Returns whether all requested families completed fully.
    pub(in crate::internal::web_capture) const fn all_complete_or_not_requested(&self) -> bool {
        is_complete_or_not_requested(&self.source)
            && is_complete_or_not_requested(&self.source_representation)
            && is_complete_or_not_requested(&self.decoded_source)
            && is_complete_or_not_requested(&self.rendered_dom)
            && is_complete_or_not_requested(&self.accessibility_tree)
            && is_complete_or_not_requested(&self.network)
            && is_complete_or_not_requested(&self.cookies)
            && is_complete_or_not_requested(&self.storage)
            && is_complete_or_not_requested(&self.layout)
            && is_complete_or_not_requested(&self.visual)
            && is_complete_or_not_requested(&self.runtime_diagnostics)
    }
}

fn extend_artifacts<T>(artifacts: &mut Vec<super::WebArtifact>, result: &ArtifactFamilyResult<T>)
where
    T: Clone + Into<super::WebArtifact>,
{
    if let Some(produced) = result.artifacts() {
        artifacts.extend(produced.iter().cloned().map(Into::into));
    }
}

const fn is_complete_or_not_requested<T>(result: &ArtifactFamilyResult<T>) -> bool {
    matches!(
        result,
        ArtifactFamilyResult::NotRequested | ArtifactFamilyResult::Complete { .. }
    )
}
