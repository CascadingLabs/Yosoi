use serde::{Deserialize, Serialize};

use super::{
    AccessibilityTreeArtifactRef, LayoutArtifactRef, RenderedDomArtifactRef, SourceArtifactRef,
    VisualArtifactRef,
};

/// Closed semantic relationships permitted between first-version artifacts.
///
/// Immediate computational lineage remains in `Provenance::derived_from`.
/// These typed edges describe representation relationships and cannot connect
/// the wrong artifact families. CAS-292 validates that related artifacts belong
/// to the appropriate capture.
///
/// ```compile_fail
/// use yosoi_web_capture::{LayoutArtifactRef, SourceArtifactRef};
///
/// fn requires_source(_: SourceArtifactRef) {}
/// fn cannot_confuse_families(layout: LayoutArtifactRef) {
///     requires_source(layout);
/// }
/// ```
#[derive(Clone, Copy, Debug, Deserialize, Eq, Hash, PartialEq, Serialize)]
#[serde(tag = "relation", rename_all = "snake_case", deny_unknown_fields)]
pub enum WebArtifactRelationship {
    /// A rendered document representation corresponding to source content.
    RenderedRepresentationOfSource {
        /// Rendered document artifact.
        rendered_dom: RenderedDomArtifactRef,
        /// Source-content artifact.
        source: SourceArtifactRef,
    },
    /// An accessibility representation corresponding to a rendered document.
    AccessibilityRepresentationOfDom {
        /// Accessibility-tree artifact.
        accessibility_tree: AccessibilityTreeArtifactRef,
        /// Rendered document artifact.
        rendered_dom: RenderedDomArtifactRef,
    },
    /// A layout representation corresponding to a rendered document.
    LayoutRepresentationOfDom {
        /// Layout artifact.
        layout: LayoutArtifactRef,
        /// Rendered document artifact.
        rendered_dom: RenderedDomArtifactRef,
    },
    /// A visual representation corresponding to captured layout.
    VisualRepresentationOfLayout {
        /// Visual artifact.
        visual: VisualArtifactRef,
        /// Layout artifact.
        layout: LayoutArtifactRef,
    },
}

impl WebArtifactRelationship {
    /// Returns both family-discriminated endpoints for containment validation.
    pub fn references(self) -> [super::WebArtifactRef; 2] {
        match self {
            Self::RenderedRepresentationOfSource {
                rendered_dom,
                source,
            } => [rendered_dom.into(), source.into()],
            Self::AccessibilityRepresentationOfDom {
                accessibility_tree,
                rendered_dom,
            } => [accessibility_tree.into(), rendered_dom.into()],
            Self::LayoutRepresentationOfDom {
                layout,
                rendered_dom,
            } => [layout.into(), rendered_dom.into()],
            Self::VisualRepresentationOfLayout { visual, layout } => [visual.into(), layout.into()],
        }
    }
}
